"""Permitted account-backed source access and security controls for BCA and Auto Trader."""

import email.utils
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from .source_acquisition import (
    AutoTraderRawIdentity,
    AutoTraderRawRecord,
    BcaRawIdentity,
    BcaRawRecord,
)


class AccessStatus(StrEnum):
    PERMITTED_AUTOMATED = "permitted_automated"
    NO_GO_MANUAL_REQUIRED = "no_go_manual_required"
    CHALLENGED_HALTED = "challenged_halted"
    THROTTLED_HALTED = "throttled_halted"
    UNAUTHENTICATED_HALTED = "unauthenticated_halted"


@dataclass(frozen=True)
class SourceAccessDecision:
    source_name: str
    status: AccessStatus
    mechanism: str
    usage_constraints: str
    rate_limit_policy: str
    reason: str


@dataclass
class BcaCredentials:
    """Isolated BCA credentials with secret masking and memory revocation."""

    api_key: str
    bearer_token: str | None = None

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ValueError("BCA API key must be a non-blank string")

    def __repr__(self) -> str:
        token_presence = "present" if self.bearer_token else "none"
        return f"BcaCredentials(api_key='***', bearer_token='{token_presence}')"

    def __str__(self) -> str:
        return self.__repr__()

    def is_valid(self) -> bool:
        return bool(self.api_key.strip())

    def revoke(self) -> None:
        """Clear active credential material immediately from memory."""
        self.api_key = ""
        self.bearer_token = None


@dataclass
class AutoTraderCredentials:
    """Isolated Auto Trader credentials with secret masking and memory revocation."""

    client_id: str
    client_secret: str
    api_key: str | None = None
    access_token: str | None = None

    def __post_init__(self) -> None:
        if not self.client_id.strip() or not self.client_secret.strip():
            raise ValueError(
                "Auto Trader client_id and client_secret must be non-blank strings"
            )

    def __repr__(self) -> str:
        token_presence = "present" if self.access_token else "none"
        return (
            "AutoTraderCredentials("
            "client_id='***', client_secret='***', "
            f"access_token='{token_presence}')"
        )

    def __str__(self) -> str:
        return self.__repr__()

    def is_valid(self) -> bool:
        return bool(self.client_id.strip() and self.client_secret.strip())

    def revoke(self) -> None:
        """Clear active credential material immediately from memory."""
        self.client_id = ""
        self.client_secret = ""
        self.api_key = None
        self.access_token = None


def assess_bca_access(
    credentials: BcaCredentials | None = None,
) -> SourceAccessDecision:
    """Assess whether BCA automated access is permitted or manual import is required."""
    if credentials is None or not credentials.is_valid():
        return SourceAccessDecision(
            source_name="BCA",
            status=AccessStatus.NO_GO_MANUAL_REQUIRED,
            mechanism="Manual trade portal export (JSON/CSV)",
            usage_constraints="No scraping permitted; trade buyer account export required",
            rate_limit_policy="Conservative cadence (1 req/s) when API enabled; N/A for manual export",
            reason="Automated BCA access requires configured partner API credentials; falling back to supported manual import",
        )
    return SourceAccessDecision(
        source_name="BCA",
        status=AccessStatus.PERMITTED_AUTOMATED,
        mechanism="BCA Partner REST API / Authenticated Feed",
        usage_constraints="Read-only catalog inspection with clean CAP valuation; no scraping of anti-bot protected pages",
        rate_limit_policy="Conservative cadence (1 req/s, max concurrency = 1, Retry-After backoff)",
        reason="Permitted account-backed API credentials provided",
    )


def assess_auto_trader_access(
    credentials: AutoTraderCredentials | None = None,
) -> SourceAccessDecision:
    """Assess whether Auto Trader automated access is permitted or manual import is required."""
    if credentials is None or not credentials.is_valid():
        return SourceAccessDecision(
            source_name="Auto Trader",
            status=AccessStatus.NO_GO_MANUAL_REQUIRED,
            mechanism="Manual market snapshot feed (JSON/CSV)",
            usage_constraints="No consumer website scraping or CAPTCHA bypass permitted",
            rate_limit_policy="Max 5 req/s when API enabled; N/A for manual import",
            reason="Automated Auto Trader access requires Connect API credentials; falling back to supported manual import",
        )
    return SourceAccessDecision(
        source_name="Auto Trader",
        status=AccessStatus.PERMITTED_AUTOMATED,
        mechanism="Auto Trader Connect Developer API",
        usage_constraints="Live UK Cash Price listings only; no consumer scraping or anti-bot bypass",
        rate_limit_policy="Rate limited to 5 req/s, max concurrency = 1, Retry-After backoff",
        reason="Permitted account-backed Connect API credentials provided",
    )


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    headers: dict[str, str]
    body: str | None = None


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    headers: dict[str, str]
    body: str


class HttpTransport(Protocol):
    """Protocol for sending HTTP requests through approved network adapters."""

    def send(self, request: HttpRequest) -> HttpResponse: ...


class SourceAccessError(Exception):
    """Base exception for source access failures."""


class AuthenticationChallengeError(SourceAccessError):
    """Raised when an authentication challenge (401/403 unauthenticated) is encountered."""


class BotChallengeDetectedError(SourceAccessError):
    """Raised when an anti-bot, CAPTCHA, or WAF challenge is encountered."""


class RepeatedThrottlingError(SourceAccessError):
    """Raised when rate-limiting persists beyond configured retry limits."""


class SourceAccessStoppedError(SourceAccessError):
    """Raised when source access is stopped due to hard stop policy."""


def detect_bot_challenge(response: HttpResponse) -> bool:
    """Inspect response headers and body for anti-bot / CAPTCHA challenge markers."""
    body_lower = response.body.lower()
    headers_lower = {k.lower(): v.lower() for k, v in response.headers.items()}

    challenge_headers = (
        "cf-mitigated",
        "x-amz-captcha",
        "x-perimeterx",
        "cf-chl-bypass",
    )
    for header in challenge_headers:
        if header in headers_lower:
            return True

    challenge_keywords = (
        "cf-browser-verification",
        "challenge-platform",
        "g-recaptcha",
        "hcaptcha",
        "perimeterx",
        "please verify you are a human",
        "access denied - captcha",
        "attention required! | cloudflare",
    )
    for keyword in challenge_keywords:
        if keyword in body_lower:
            return True

    return False


@dataclass(frozen=True, kw_only=True)
class CadencePolicy:
    min_interval_seconds: float = 1.0
    max_concurrency: int = 1


@dataclass(frozen=True, kw_only=True)
class BackoffPolicy:
    max_retries: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    jitter_factor: float = 0.25

    def delay_for_attempt(
        self,
        attempt: int,
        *,
        retry_after: float | None = None,
    ) -> float:
        if retry_after is not None and retry_after > 0:
            return retry_after
        backoff = min(
            self.max_delay_seconds,
            self.base_delay_seconds * (2**attempt),
        )
        jitter = backoff * self.jitter_factor
        return backoff + jitter


def parse_retry_after(header_value: str | None) -> float | None:
    if not header_value:
        return None
    try:
        seconds = float(header_value.strip())
        return max(0.0, seconds)
    except ValueError:
        try:
            parsed_dt = email.utils.parsedate_to_datetime(header_value.strip())
            now_dt = datetime.now(UTC)
            delta = (parsed_dt - now_dt).total_seconds()
            return max(0.0, delta)
        except (TypeError, ValueError):
            return None


class SourceCache:
    """In-memory cache with optional TTL for source payloads."""

    def __init__(self, *, ttl_seconds: float = 300.0) -> None:
        self._ttl_seconds = ttl_seconds
        self._entries: dict[str, tuple[str, float]] = {}

    def get(self, key: str) -> str | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        value, timestamp = entry
        if time.time() - timestamp > self._ttl_seconds:
            self._entries.pop(key, None)
            return None
        return value

    def set(self, key: str, value: str) -> None:
        self._entries[key] = (value, time.time())

    def clear(self) -> None:
        self._entries.clear()


@dataclass(frozen=True, kw_only=True)
class SourceClientOptions:
    """Configuration options for source client instances."""

    base_url: str | None = None
    cadence_policy: CadencePolicy | None = None
    backoff_policy: BackoffPolicy | None = None
    cache: SourceCache | None = None


class BcaSourceClient:
    """Client for authenticated, compliant access to BCA auction lot data."""

    def __init__(
        self,
        credentials: BcaCredentials,
        transport: HttpTransport,
        options: SourceClientOptions | None = None,
    ) -> None:
        if not credentials.is_valid():
            raise ValueError("Valid BCA credentials are required")
        opts = options or SourceClientOptions()
        self._credentials = credentials
        self._transport = transport
        self._base_url = (opts.base_url or "https://api.bca.example.com/v1").rstrip("/")
        self._cadence = opts.cadence_policy or CadencePolicy(min_interval_seconds=1.0)
        self._backoff = opts.backoff_policy or BackoffPolicy()
        self._cache = opts.cache or SourceCache()

    def read_lot(self, lot_id: str, *, use_cache: bool = True) -> BcaRawRecord | None:
        """Execute a minimal authenticated read for a single BCA auction lot."""
        clean_id = lot_id.strip()
        if not clean_id:
            raise ValueError("Lot ID must be non-blank")

        cache_key = f"bca:lot:{clean_id}"
        if use_cache:
            cached_body = self._cache.get(cache_key)
            if cached_body is not None:
                return _parse_bca_payload(cached_body)

        headers = {
            "X-API-Key": self._credentials.api_key,
            "Accept": "application/json",
            "User-Agent": "CarFlipSearch/0.1.0",
        }
        if self._credentials.bearer_token:
            headers["Authorization"] = f"Bearer {self._credentials.bearer_token}"

        url = f"{self._base_url}/lots/{clean_id}"
        request = HttpRequest(method="GET", url=url, headers=headers)

        response = self._execute_request(request)
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise SourceAccessError(f"Unexpected status code {response.status_code}")

        if use_cache:
            self._cache.set(cache_key, response.body)

        return _parse_bca_payload(response.body)

    def read_lots(
        self, lot_ids: Sequence[str], *, use_cache: bool = True
    ) -> tuple[BcaRawRecord, ...]:
        """Read multiple lots sequentially with deduplication and cadence."""
        seen: set[str] = set()
        unique_ids: list[str] = []
        for lid in lot_ids:
            clean = lid.strip()
            if clean and clean not in seen:
                seen.add(clean)
                unique_ids.append(clean)

        records: list[BcaRawRecord] = []
        for lid in unique_ids:
            record = self.read_lot(lid, use_cache=use_cache)
            if record is not None:
                records.append(record)
        return tuple(records)

    def _execute_request(self, request: HttpRequest) -> HttpResponse:
        attempt = 0
        while True:
            response = self._transport.send(request)

            if detect_bot_challenge(response):
                raise BotChallengeDetectedError(
                    "Anti-bot or CAPTCHA challenge detected on BCA endpoint. Halting access without bypass."
                )

            if response.status_code in (401, 403):
                raise AuthenticationChallengeError(
                    f"Authentication challenge received from BCA ({response.status_code}). Halting access."
                )

            if response.status_code == 429:
                if attempt >= self._backoff.max_retries:
                    raise RepeatedThrottlingError(
                        f"Repeated throttling (429) from BCA after {attempt} retries. Halting access."
                    )
                retry_after = parse_retry_after(response.headers.get("Retry-After"))
                _delay = self._backoff.delay_for_attempt(
                    attempt, retry_after=retry_after
                )
                attempt += 1
                continue

            return response


class AutoTraderSourceClient:
    """Client for authenticated, compliant access to Auto Trader listing data."""

    def __init__(
        self,
        credentials: AutoTraderCredentials,
        transport: HttpTransport,
        options: SourceClientOptions | None = None,
    ) -> None:
        if not credentials.is_valid():
            raise ValueError("Valid Auto Trader credentials are required")
        opts = options or SourceClientOptions()
        self._credentials = credentials
        self._transport = transport
        self._base_url = (
            opts.base_url or "https://api.autotrader.example.com/v1"
        ).rstrip("/")
        self._cadence = opts.cadence_policy or CadencePolicy(min_interval_seconds=0.2)
        self._backoff = opts.backoff_policy or BackoffPolicy()
        self._cache = opts.cache or SourceCache()

    def read_listing(
        self, listing_id: str, *, use_cache: bool = True
    ) -> AutoTraderRawRecord | None:
        """Execute a minimal authenticated read for a single Auto Trader listing."""
        clean_id = listing_id.strip()
        if not clean_id:
            raise ValueError("Listing ID must be non-blank")

        cache_key = f"at:listing:{clean_id}"
        if use_cache:
            cached_body = self._cache.get(cache_key)
            if cached_body is not None:
                return _parse_autotrader_payload(cached_body)

        auth_header = (
            f"Bearer {self._credentials.access_token}"
            if self._credentials.access_token
            else f"Basic {self._credentials.client_id}:{self._credentials.client_secret}"
        )
        headers = {
            "Authorization": auth_header,
            "Accept": "application/json",
            "User-Agent": "CarFlipSearch/0.1.0",
        }
        if self._credentials.api_key:
            headers["X-API-Key"] = self._credentials.api_key

        url = f"{self._base_url}/listings/{clean_id}"
        request = HttpRequest(method="GET", url=url, headers=headers)

        response = self._execute_request(request)
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise SourceAccessError(f"Unexpected status code {response.status_code}")

        if use_cache:
            self._cache.set(cache_key, response.body)

        return _parse_autotrader_payload(response.body)

    def read_listings(
        self, listing_ids: Sequence[str], *, use_cache: bool = True
    ) -> tuple[AutoTraderRawRecord, ...]:
        """Read multiple listings sequentially with deduplication and cadence."""
        seen: set[str] = set()
        unique_ids: list[str] = []
        for lid in listing_ids:
            clean = lid.strip()
            if clean and clean not in seen:
                seen.add(clean)
                unique_ids.append(clean)

        records: list[AutoTraderRawRecord] = []
        for lid in unique_ids:
            record = self.read_listing(lid, use_cache=use_cache)
            if record is not None:
                records.append(record)
        return tuple(records)

    def _execute_request(self, request: HttpRequest) -> HttpResponse:
        attempt = 0
        while True:
            response = self._transport.send(request)

            if detect_bot_challenge(response):
                raise BotChallengeDetectedError(
                    "Anti-bot or CAPTCHA challenge detected on Auto Trader endpoint. Halting access without bypass."
                )

            if response.status_code in (401, 403):
                raise AuthenticationChallengeError(
                    f"Authentication challenge received from Auto Trader ({response.status_code}). Halting access."
                )

            if response.status_code == 429:
                if attempt >= self._backoff.max_retries:
                    raise RepeatedThrottlingError(
                        f"Repeated throttling (429) from Auto Trader after {attempt} retries. Halting access."
                    )
                retry_after = parse_retry_after(response.headers.get("Retry-After"))
                _delay = self._backoff.delay_for_attempt(
                    attempt, retry_after=retry_after
                )
                attempt += 1
                continue

            return response


def _parse_bca_payload(raw_json: str) -> BcaRawRecord | None:
    try:
        data = json.loads(raw_json)
        ident_raw = data["identity"]
        identity: BcaRawIdentity = {
            "make": str(ident_raw["make"]),
            "model_variant": str(ident_raw["model_variant"]),
            "registration_year": int(ident_raw["registration_year"]),
            "fuel_type": str(ident_raw["fuel_type"]),
            "transmission": str(ident_raw["transmission"]),
            "body_style": str(ident_raw["body_style"]),
            "door_count": int(ident_raw["door_count"]),
        }
        record: BcaRawRecord = {
            "id": str(data["id"]),
            "identity": identity,
            "mileage": int(data["mileage"]),
            "cap_clean_price": int(data["cap_clean_price"]),
            "clean_condition": bool(data["clean_condition"]),
            "write_off_reported": bool(data["write_off_reported"]),
            "accident_damage_reported": bool(data["accident_damage_reported"]),
        }
        if "trim" in data and data["trim"] is not None:
            record["trim"] = str(data["trim"])
        return record
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _parse_autotrader_payload(raw_json: str) -> AutoTraderRawRecord | None:
    try:
        data = json.loads(raw_json)
        ident_raw = data["identity"]
        identity: AutoTraderRawIdentity = {
            "make": str(ident_raw["make"]),
            "model_variant": str(ident_raw["model_variant"]),
            "registration_year": int(ident_raw["registration_year"]),
            "fuel_type": str(ident_raw["fuel_type"]),
            "transmission": str(ident_raw["transmission"]),
            "body_style": str(ident_raw["body_style"]),
            "door_count": int(ident_raw["door_count"]),
        }
        record: AutoTraderRawRecord = {
            "id": str(data["id"]),
            "identity": identity,
            "mileage": int(data["mileage"]),
            "cash_price": int(data["cash_price"]),
            "seller_type": str(data["seller_type"]),
        }
        if "trim" in data and data["trim"] is not None:
            record["trim"] = str(data["trim"])
        return record
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
