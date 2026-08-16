import json
from collections.abc import Sequence

import pytest

from car_flip_search import (
    AccessStatus,
    AuctionLotId,
    AuthenticationChallengeError,
    AutoTraderAcquisition,
    AutoTraderCredentials,
    AutoTraderListingId,
    AutoTraderSourceClient,
    BackoffPolicy,
    BcaAcquisition,
    BcaCredentials,
    BcaSourceClient,
    BotChallengeDetectedError,
    HttpRequest,
    HttpResponse,
    HttpTransport,
    OpportunitySearch,
    RepeatedThrottlingError,
    SourceCache,
    SourceClientOptions,
    assess_auto_trader_access,
    assess_bca_access,
    detect_bot_challenge,
    parse_retry_after,
)


class FakeHttpTransport(HttpTransport):
    """Deterministic in-memory transport implementing the HttpTransport protocol."""

    def __init__(self, responses: Sequence[HttpResponse] | None = None) -> None:
        self._responses = list(responses or [])
        self.sent_requests: list[HttpRequest] = []

    def queue_response(self, response: HttpResponse) -> None:
        self._responses.append(response)

    def send(self, request: HttpRequest) -> HttpResponse:
        self.sent_requests.append(request)
        if not self._responses:
            return HttpResponse(status_code=404, headers={}, body="{}")
        return self._responses.pop(0)


def sample_bca_payload() -> str:
    return json.dumps(
        {
            "id": "YF66 FEJ",
            "identity": {
                "make": "BMW",
                "model_variant": "320d",
                "registration_year": 2016,
                "fuel_type": "Diesel",
                "transmission": "Automatic",
                "body_style": "Saloon",
                "door_count": 4,
            },
            "mileage": 130319,
            "cap_clean_price": 5450,
            "clean_condition": True,
            "write_off_reported": False,
            "accident_damage_reported": False,
            "trim": "M Sport",
        }
    )


def sample_autotrader_payload() -> str:
    return json.dumps(
        {
            "id": "202603271072975",
            "identity": {
                "make": "BMW",
                "model_variant": "320d",
                "registration_year": 2016,
                "fuel_type": "Diesel",
                "transmission": "Automatic",
                "body_style": "Saloon",
                "door_count": 4,
            },
            "mileage": 117004,
            "cash_price": 8995,
            "seller_type": "dealer",
            "trim": "M Sport",
        }
    )


def test_assess_bca_access_distinguishes_permitted_and_manual_routes() -> None:
    no_creds_decision = assess_bca_access(None)
    assert no_creds_decision.status == AccessStatus.NO_GO_MANUAL_REQUIRED
    assert "manual" in no_creds_decision.reason.lower()

    valid_creds = BcaCredentials(api_key="bca-secret-key-123")
    permitted_decision = assess_bca_access(valid_creds)
    assert permitted_decision.status == AccessStatus.PERMITTED_AUTOMATED
    assert "bca" in permitted_decision.mechanism.lower()


def test_assess_autotrader_access_distinguishes_permitted_and_manual_routes() -> None:
    no_creds_decision = assess_auto_trader_access(None)
    assert no_creds_decision.status == AccessStatus.NO_GO_MANUAL_REQUIRED
    assert "manual" in no_creds_decision.reason.lower()

    valid_creds = AutoTraderCredentials(
        client_id="at-client", client_secret="at-secret"
    )
    permitted_decision = assess_auto_trader_access(valid_creds)
    assert permitted_decision.status == AccessStatus.PERMITTED_AUTOMATED
    assert "connect" in permitted_decision.mechanism.lower()


def test_credentials_mask_secrets_and_prevent_leakage() -> None:
    bca_creds = BcaCredentials(api_key="secret-api-key-999", bearer_token="jwt-token")
    assert "secret-api-key-999" not in repr(bca_creds)
    assert "jwt-token" not in str(bca_creds)
    assert "***" in repr(bca_creds)

    at_creds = AutoTraderCredentials(
        client_id="my-client-id",
        client_secret="my-super-secret",
        access_token="bearer-token-123",
    )
    assert "my-super-secret" not in repr(at_creds)
    assert "bearer-token-123" not in str(at_creds)
    assert "***" in repr(at_creds)


def test_credentials_memory_revocation() -> None:
    bca_creds = BcaCredentials(api_key="secret-key", bearer_token="token")
    assert bca_creds.is_valid()
    bca_creds.revoke()
    assert not bca_creds.is_valid()
    assert bca_creds.api_key == ""
    assert bca_creds.bearer_token is None

    at_creds = AutoTraderCredentials(
        client_id="client-1", client_secret="secret-1", access_token="token-1"
    )
    assert at_creds.is_valid()
    at_creds.revoke()
    assert not at_creds.is_valid()
    assert at_creds.client_id == ""
    assert at_creds.client_secret == ""
    assert at_creds.access_token is None


def test_credentials_reject_empty_values() -> None:
    with pytest.raises(ValueError, match="non-blank"):
        BcaCredentials(api_key="  ")
    with pytest.raises(ValueError, match="non-blank"):
        AutoTraderCredentials(client_id="", client_secret="secret")
    with pytest.raises(ValueError, match="non-blank"):
        AutoTraderCredentials(client_id="client", client_secret="  ")


def test_bca_source_client_demonstrates_minimal_authenticated_read() -> None:
    transport = FakeHttpTransport(
        [
            HttpResponse(
                status_code=200,
                headers={"Content-Type": "application/json"},
                body=sample_bca_payload(),
            )
        ]
    )
    creds = BcaCredentials(api_key="bca-test-key", bearer_token="test-bearer")
    client = BcaSourceClient(creds, transport)

    record = client.read_lot("YF66 FEJ")
    assert record is not None
    assert record["id"] == "YF66 FEJ"
    assert record["cap_clean_price"] == 5450
    assert record["mileage"] == 130319

    assert len(transport.sent_requests) == 1
    req = transport.sent_requests[0]
    assert req.headers["X-API-Key"] == "bca-test-key"
    assert req.headers["Authorization"] == "Bearer test-bearer"
    assert "YF66 FEJ" in req.url


def test_bca_source_client_caches_and_deduplicates() -> None:
    transport = FakeHttpTransport(
        [
            HttpResponse(
                status_code=200,
                headers={"Content-Type": "application/json"},
                body=sample_bca_payload(),
            )
        ]
    )
    creds = BcaCredentials(api_key="bca-key")
    cache = SourceCache()
    client = BcaSourceClient(
        creds, transport, options=SourceClientOptions(cache=cache)
    )

    # Reading the same lot twice hits cache
    record_1 = client.read_lot("YF66 FEJ")
    record_2 = client.read_lot("YF66 FEJ")
    assert record_1 == record_2
    assert len(transport.sent_requests) == 1

    # Batch read with duplicates only fetches once
    records = client.read_lots(["YF66 FEJ", "YF66 FEJ", "  ", "YF66 FEJ"])
    assert len(records) == 1
    assert len(transport.sent_requests) == 1


def test_bca_source_client_hard_stops_on_authentication_challenge() -> None:
    transport = FakeHttpTransport(
        [
            HttpResponse(
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
                body='{"error": "Unauthorized"}',
            )
        ]
    )
    creds = BcaCredentials(api_key="expired-key")
    client = BcaSourceClient(creds, transport)

    with pytest.raises(AuthenticationChallengeError, match="401"):
        client.read_lot("YF66 FEJ")


def test_bca_source_client_hard_stops_on_bot_challenge() -> None:
    transport = FakeHttpTransport(
        [
            HttpResponse(
                status_code=403,
                headers={"cf-mitigated": "challenge"},
                body="<html><title>Attention Required! | Cloudflare</title></html>",
            )
        ]
    )
    creds = BcaCredentials(api_key="valid-key")
    client = BcaSourceClient(creds, transport)

    with pytest.raises(BotChallengeDetectedError, match="Anti-bot"):
        client.read_lot("YF66 FEJ")


def test_bca_source_client_retries_transient_throttling_and_halts_on_repeated() -> None:
    # 1. Transient 429 then success
    transport_success = FakeHttpTransport(
        [
            HttpResponse(
                status_code=429,
                headers={"Retry-After": "1"},
                body="Too Many Requests",
            ),
            HttpResponse(
                status_code=200,
                headers={},
                body=sample_bca_payload(),
            ),
        ]
    )
    creds = BcaCredentials(api_key="valid-key")
    client_success = BcaSourceClient(creds, transport_success)
    record = client_success.read_lot("YF66 FEJ")
    assert record is not None
    assert len(transport_success.sent_requests) == 2

    # 2. Repeated 429 exceeding max retries -> RepeatedThrottlingError
    transport_throttled = FakeHttpTransport(
        [
            HttpResponse(status_code=429, headers={}, body="Too Many Requests"),
            HttpResponse(status_code=429, headers={}, body="Too Many Requests"),
            HttpResponse(status_code=429, headers={}, body="Too Many Requests"),
            HttpResponse(status_code=429, headers={}, body="Too Many Requests"),
        ]
    )
    client_throttled = BcaSourceClient(
        creds,
        transport_throttled,
        options=SourceClientOptions(backoff_policy=BackoffPolicy(max_retries=2)),
    )
    with pytest.raises(RepeatedThrottlingError, match="Repeated throttling"):
        client_throttled.read_lot("YF66 FEJ")


def test_autotrader_source_client_demonstrates_minimal_authenticated_read() -> None:
    transport = FakeHttpTransport(
        [
            HttpResponse(
                status_code=200,
                headers={"Content-Type": "application/json"},
                body=sample_autotrader_payload(),
            )
        ]
    )
    creds = AutoTraderCredentials(
        client_id="client-abc",
        client_secret="secret-xyz",
        access_token="token-999",
        api_key="api-key-123",
    )
    client = AutoTraderSourceClient(creds, transport)

    record = client.read_listing("202603271072975")
    assert record is not None
    assert record["id"] == "202603271072975"
    assert record["cash_price"] == 8995
    assert record["seller_type"] == "dealer"

    assert len(transport.sent_requests) == 1
    req = transport.sent_requests[0]
    assert req.headers["Authorization"] == "Bearer token-999"
    assert req.headers["X-API-Key"] == "api-key-123"


def test_autotrader_source_client_hard_stops_on_bot_and_auth_challenges() -> None:
    creds = AutoTraderCredentials(client_id="cid", client_secret="csec")

    # Bot challenge
    transport_bot = FakeHttpTransport(
        [
            HttpResponse(
                status_code=403,
                headers={},
                body="<html><body>Please verify you are a human g-recaptcha</body></html>",
            )
        ]
    )
    client_bot = AutoTraderSourceClient(creds, transport_bot)
    with pytest.raises(BotChallengeDetectedError, match="Anti-bot"):
        client_bot.read_listing("123")

    # Auth challenge
    transport_auth = FakeHttpTransport(
        [HttpResponse(status_code=403, headers={}, body='{"error": "Forbidden"}')]
    )
    client_auth = AutoTraderSourceClient(creds, transport_auth)
    with pytest.raises(AuthenticationChallengeError, match="403"):
        client_auth.read_listing("123")


def test_autotrader_source_client_handles_repeated_throttling() -> None:
    creds = AutoTraderCredentials(client_id="cid", client_secret="csec")
    transport = FakeHttpTransport(
        [
            HttpResponse(status_code=429, headers={}, body="Rate limit exceeded"),
            HttpResponse(status_code=429, headers={}, body="Rate limit exceeded"),
        ]
    )
    client = AutoTraderSourceClient(
        creds,
        transport,
        options=SourceClientOptions(backoff_policy=BackoffPolicy(max_retries=1)),
    )
    with pytest.raises(RepeatedThrottlingError, match="Repeated throttling"):
        client.read_listing("123")


def test_parse_retry_after_and_backoff_calculations() -> None:
    assert parse_retry_after("5") == 5.0
    assert parse_retry_after("0") == 0.0
    assert parse_retry_after(None) is None
    assert parse_retry_after("invalid") is None

    policy = BackoffPolicy(
        base_delay_seconds=2.0, max_delay_seconds=20.0, jitter_factor=0.0
    )
    assert policy.delay_for_attempt(0) == 2.0
    assert policy.delay_for_attempt(1) == 4.0
    assert policy.delay_for_attempt(2) == 8.0
    assert policy.delay_for_attempt(0, retry_after=15.0) == 15.0


def test_bot_challenge_detector_markers() -> None:
    assert detect_bot_challenge(
        HttpResponse(status_code=200, headers={"cf-mitigated": "1"}, body="")
    )
    assert detect_bot_challenge(
        HttpResponse(
            status_code=403,
            headers={},
            body="<html><title>Just a moment...</title>challenge-platform</html>",
        )
    )
    assert not detect_bot_challenge(
        HttpResponse(status_code=200, headers={}, body='{"id": "123"}')
    )


def test_end_to_end_source_acquisition_pipeline_with_opportunity_search() -> None:
    # 1. Read authenticated BCA lot
    bca_transport = FakeHttpTransport(
        [
            HttpResponse(
                status_code=200,
                headers={"Content-Type": "application/json"},
                body=sample_bca_payload(),
            )
        ]
    )
    bca_client = BcaSourceClient(
        BcaCredentials(api_key="bca-key"),
        bca_transport,
    )
    bca_record = bca_client.read_lot("YF66 FEJ")
    assert bca_record is not None

    # 2. Read authenticated Auto Trader listing
    at_transport = FakeHttpTransport(
        [
            HttpResponse(
                status_code=200,
                headers={"Content-Type": "application/json"},
                body=sample_autotrader_payload(),
            )
        ]
    )
    at_client = AutoTraderSourceClient(
        AutoTraderCredentials(client_id="cid", client_secret="csec"),
        at_transport,
    )
    at_record = at_client.read_listing("202603271072975")
    assert at_record is not None

    # 3. Parse into domain entities through acquisition seam
    auction_lots = BcaAcquisition().acquire([bca_record])
    assert len(auction_lots) == 1
    assert auction_lots[0].id == AuctionLotId("YF66 FEJ")

    market_snapshot = AutoTraderAcquisition().acquire_snapshot([at_record])
    assert len(market_snapshot.listings) == 1
    assert market_snapshot.listings[0].id == AutoTraderListingId("202603271072975")

    # 4. Run Opportunity Search
    opportunities = OpportunitySearch().search(auction_lots, market_snapshot)
    assert len(opportunities.candidates) == 1

    candidate = opportunities.candidates[0]
    assert candidate.auction_lot.id == AuctionLotId("YF66 FEJ")
    assert candidate.comparable_supply == 1
    assert candidate.price_spread.pounds == 8995 - 5450
