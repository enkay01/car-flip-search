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
    BotChallengeDetectedError,
    HttpRequest,
    HttpResponse,
    HttpTransport,
    ManualBcaImporter,
    OpportunitySearch,
    RepeatedThrottlingError,
    SourceClientOptions,
    assess_auto_trader_access,
    assess_auto_trader_capture_access,
    assess_bca_access,
    detect_bot_challenge,
    detect_challenge_markers,
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


def test_assess_bca_access_describes_user_assisted_capture() -> None:
    decision = assess_bca_access()
    assert decision.status == AccessStatus.PERMITTED_USER_ASSISTED
    assert "headed browser" in decision.mechanism.lower()
    assert "api" not in decision.mechanism.lower()


def test_assess_auto_trader_capture_access_describes_unauthenticated_capture() -> None:
    decision = assess_auto_trader_capture_access()
    assert decision.status == AccessStatus.PERMITTED_USER_ASSISTED
    assert "headed browser" in decision.mechanism.lower()
    assert "does not require login" in decision.reason.lower()
    assert "capture" in decision.mechanism.lower()


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
    at_creds = AutoTraderCredentials(
        client_id="my-client-id",
        client_secret="my-super-secret",
        access_token="bearer-token-123",
    )
    assert "my-super-secret" not in repr(at_creds)
    assert "bearer-token-123" not in str(at_creds)
    assert "***" in repr(at_creds)


def test_credentials_memory_revocation() -> None:
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
        AutoTraderCredentials(client_id="", client_secret="secret")
    with pytest.raises(ValueError, match="non-blank"):
        AutoTraderCredentials(client_id="client", client_secret="  ")


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


def test_detect_challenge_markers_reports_descriptive_reason() -> None:
    assert (
        detect_challenge_markers(
            "<html><title>Attention Required! | Cloudflare</title></html>"
        )
        is not None
    )
    assert (
        detect_challenge_markers("<html><body>normal search results</body></html>")
        is None
    )


def test_detect_challenge_markers_reports_auth_and_access_denial_pages() -> None:
    assert "access-denial" in (
        detect_challenge_markers("<html><title>Access Denied</title></html>") or ""
    )
    assert "sign-in" in (
        detect_challenge_markers("<html><body>Sign in to continue</body></html>") or ""
    )
    assert (
        detect_challenge_markers(
            '<script>const loginUrl = "/login";</script><body>search results</body>'
        )
        is None
    )


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


def sample_bca_live_card_html() -> str:
    return """
    <!DOCTYPE html>
    <html>
    <body>
        <div class="VehicleResultCardDesktop">
            <a data-testid="card-link-desktop" href="https://www.bca.co.uk/lot/YF66%20FEJ?q=test"></a>
            <a class="VehicleResultCardDesktop__StyledLink-sc-123" href="https://www.bca.co.uk/lot/YF66%20FEJ">BMW 320d M Sport Saloon</a>
            <ul>
                <li><p color="grey-blue">130,319 miles (Warranted)</p></li>
                <li><p color="grey-blue">2016 (16 reg)</p></li>
                <li><p color="grey-blue">Diesel</p></li>
                <li><p color="grey-blue">Automatic</p></li>
                <li><p color="grey-blue">4 doors</p></li>
            </ul>
            <div data-testid="condition-report-icon">BCA Assured</div>
            <div>
                <p>CAP Clean</p>
                <p>£5,450</p>
            </div>
        </div>
    </body>
    </html>
    """


def test_end_to_end_source_acquisition_pipeline_with_opportunity_search() -> None:
    # 1. BCA acquisition through the user-assisted capture/import route
    auction_lots = ManualBcaImporter().import_from_html(sample_bca_live_card_html())
    assert len(auction_lots) == 1
    assert auction_lots[0].id == AuctionLotId("YF66 FEJ")

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

    # 3. Parse Auto Trader into domain entities through the acquisition seam
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
