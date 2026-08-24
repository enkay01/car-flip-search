"""Unified JSON-first command line interface for Car Flip Search.

The browser commands deliberately keep the browser boundary here: credentials are
never read by this module, and Playwright is used only for visible, user-assisted
sessions. The comparison and capture kernels remain reusable and testable without
browser dependencies.
"""

from __future__ import annotations

import json
import sys
import time
from argparse import ArgumentParser, Namespace
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any, Protocol, TextIO, TypedDict
from urllib.parse import urlsplit

from .autotrader_url import build_autotrader_search_url
from .capture import (
    CaptureChallengeError,
    CaptureHooks,
    CaptureOptions,
    CaptureOutcome,
    SourceKind,
    StopReason,
    autotrader_capture_strategy,
    bca_capture_strategy,
    run_capture,
    save_capture,
)
from .model import (
    AuctionLot,
    AuctionLotId,
    CandidateVehicle,
    CapCleanPrice,
    CoreVehicleIdentity,
    HighMileageReference,
    MarketComparable,
    MarketSnapshot,
    OpportunityList,
)
from .opportunity_search import OpportunitySearch
from .source_access import detect_bot_challenge_markers
from .source_acquisition import (
    AutoTraderAcquisition,
    BcaAcquisition,
    normalize_model_variant,
)

PlaywrightError = RuntimeError
sync_playwright = None
with suppress(ImportError):  # Playwright is optional for comparison-only users.
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright


_BCA_CARD_SELECTOR = (
    '[data-testid="card-link-desktop"], '
    '[data-testid="condition-report-icon"], a[href*="/lot/"]'
)
_LOGIN_TOKENS = ("/login", "/signin", "/sign-in", "/logon")
type JsonValue = (
    str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
)


def _write_json(value: JsonValue, *, pretty: bool = False) -> None:
    print(json.dumps(value, indent=2 if pretty else None, sort_keys=True))


def _error_envelope(message: str, *, code: str = "error") -> dict[str, JsonValue]:
    return {"status": "error", "error": message, "code": code}


def _serialize_identity(identity: CoreVehicleIdentity) -> dict[str, JsonValue]:
    return {
        "make": identity.make,
        "model_variant": identity.model_variant,
        "registration_year": identity.registration_year,
        "fuel_type": identity.fuel_type,
        "transmission": identity.transmission,
        "body_style": identity.body_style,
        "door_count": identity.door_count,
    }


def _serialize_candidate(candidate: CandidateVehicle) -> dict[str, JsonValue]:
    lot = candidate.auction_lot
    return {
        "id": lot.id.value,
        "identity": _serialize_identity(lot.identity),
        "make": lot.identity.make,
        "model_variant": lot.identity.model_variant,
        "registration_year": lot.identity.registration_year,
        "mileage": lot.mileage,
        "cap_clean_price_pounds": lot.cap_clean_price.pounds,
        "fuel_type": lot.identity.fuel_type,
        "transmission": lot.identity.transmission,
        "body_style": lot.identity.body_style,
        "door_count": lot.identity.door_count,
        "trim": lot.trim,
    }


def _serialize_comparable(comparable: MarketComparable) -> dict[str, JsonValue]:
    return {
        "listing_id": comparable.listing_id.value,
        "identity": _serialize_identity(comparable.identity),
        "advertised_price_pounds": comparable.advertised_price.pounds,
        "mileage": comparable.mileage,
        "seller_type": comparable.seller_type.value,
        "trim": comparable.trim,
        "trim_match": comparable.trim_match,
    }


def _serialize_reference(reference: HighMileageReference) -> dict[str, JsonValue]:
    return {
        "listing_id": reference.listing_id.value,
        "identity": _serialize_identity(reference.identity),
        "advertised_price_pounds": reference.advertised_price.pounds,
        "mileage": reference.mileage,
        "seller_type": reference.seller_type.value,
        "trim": reference.trim,
    }


def _serialize_candidate_valuation(candidate: CandidateVehicle) -> dict[str, JsonValue]:
    references = candidate.retail_floor_evidence.high_mileage_references
    retail_floor = candidate.retail_floor
    return {
        "cap_clean_price_pounds": candidate.auction_lot.cap_clean_price.pounds,
        "comparable_supply": candidate.comparable_supply,
        "price_spread_pounds": candidate.price_spread_pounds,
        "retail_floor_pounds": (
            retail_floor.pounds if hasattr(retail_floor, "pounds") else None
        ),
        "retail_floor_spread_pounds": candidate.retail_floor_spread_pounds,
        "high_mileage_reference_count": len(references),
    }


def _serialize_candidate_result(candidate: CandidateVehicle) -> dict[str, JsonValue]:
    comparables = candidate.comparable_evidence.market_comparables
    references = candidate.retail_floor_evidence.high_mileage_references
    return {
        "candidate": _serialize_candidate(candidate),
        "valuation": _serialize_candidate_valuation(candidate),
        "market_comparables": [_serialize_comparable(item) for item in comparables],
        "high_mileage_references": [_serialize_reference(item) for item in references],
    }


def _serialize_opportunity_list(opportunities: OpportunityList) -> list[dict[str, JsonValue]]:
    return [
        {
            **_serialize_candidate_result(candidate),
            "auction_lot_id": candidate.auction_lot.id.value,
        }
        for candidate in opportunities.candidates
    ]


def _read_json_records(path: Path) -> list[dict[str, JsonValue]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{path} must contain a JSON list of records")
    return value


def _market_snapshot_from_args(args: Namespace) -> MarketSnapshot:
    if args.autotrader_capture_id:
        return _load_capture_snapshot(args.data_root, args.autotrader_capture_id)
    if args.market_file is not None:
        return AutoTraderAcquisition().acquire_snapshot(
            _read_json_records(args.market_file)
        )

    source_dir = args.data_root / SourceKind.AUTOTRADER.value
    capture_dirs = sorted(
        (path for path in source_dir.iterdir() if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    ) if source_dir.is_dir() else []
    for capture_dir in capture_dirs:
        records_path = capture_dir / "records.json"
        if records_path.is_file():
            snapshot = AutoTraderAcquisition().acquire_snapshot(
                _read_json_records(records_path)
            )
            if snapshot.listings:
                return snapshot
    raise FileNotFoundError(
        "no usable Auto Trader capture found; provide --market-file or "
        "--autotrader-capture-id"
    )


def _load_capture_snapshot(data_root: Path, capture_id: str) -> MarketSnapshot:
    capture_dir = _capture_path(data_root, SourceKind.AUTOTRADER, capture_id)
    return AutoTraderAcquisition().acquire_snapshot(
        _read_json_records(capture_dir / "records.json")
    )


def _capture_path(data_root: Path, source: SourceKind, capture_id: str) -> Path:
    if not capture_id or Path(capture_id).name != capture_id:
        raise ValueError("capture ID must be a single directory name")
    source_dir = (data_root / source.value).resolve()
    path = (source_dir / capture_id).resolve()
    if path.parent != source_dir:
        raise ValueError("capture ID points outside the capture directory")
    if not path.is_dir():
        raise FileNotFoundError(f"{source.value} capture not found: {capture_id}")
    return path


class VehicleInput(TypedDict, total=False):
    """Sparse CLI or JSON fields used to build one comparison vehicle."""

    make: str | int | None
    model: str | int | None
    year: str | int | None
    mileage: str | int | None
    cap_clean_price: str | int | None
    trim: str | None
    fuel_type: str | None
    transmission: str | None


def _vehicle_values(args: Namespace, *, stdin: TextIO) -> VehicleInput:
    if args.json_input:
        if any(
            value is not None
            for value in (
                args.make,
                args.model,
                args.year,
                args.mileage,
                args.cap_clean_price,
                args.trim,
                args.fuel_type,
                args.transmission,
            )
        ):
            raise ValueError("--json-input cannot be combined with vehicle flags")
        try:
            payload = json.load(stdin)
        except (json.JSONDecodeError, OSError) as error:
            raise ValueError(f"invalid JSON input: {error}") from error
        if not isinstance(payload, dict):
            raise ValueError("JSON input must be an object")
        return VehicleInput(
            make=payload.get("make"),
            model=payload.get("model_variant", payload.get("model")),
            year=payload.get("registration_year", payload.get("year")),
            mileage=payload.get("mileage"),
            cap_clean_price=payload.get(
                "cap_clean_price", payload.get("cap_price")
            ),
            trim=payload.get("trim"),
            fuel_type=payload.get("fuel_type"),
            transmission=payload.get("transmission"),
        )
    return VehicleInput(
        make=args.make,
        model=args.model,
        year=args.year,
        mileage=args.mileage,
        cap_clean_price=args.cap_clean_price,
        trim=args.trim,
        fuel_type=args.fuel_type,
        transmission=args.transmission,
    )


def _build_ad_hoc_lot(vehicle: VehicleInput) -> AuctionLot:
    required = {
        "make": vehicle["make"],
        "model": vehicle["model"],
        "year": vehicle["year"],
        "mileage": vehicle["mileage"],
        "cap_clean_price": vehicle["cap_clean_price"],
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        raise ValueError("missing required parameters: " + ", ".join(missing))
    make_str = str(required["make"]).strip()
    model_str = str(required["model"]).strip()
    model_str = normalize_model_variant(make_str, model_str) or model_str
    return AuctionLot(
        id=AuctionLotId("AD-HOC-INPUT"),
        identity=CoreVehicleIdentity(
            make=make_str,
            model_variant=model_str,
            registration_year=int(required["year"]),
            fuel_type=(
                str(vehicle["fuel_type"])
                if vehicle["fuel_type"] is not None
                else None
            ),
            transmission=(
                str(vehicle["transmission"])
                if vehicle["transmission"] is not None
                else None
            ),
        ),
        mileage=int(required["mileage"]),
        cap_clean_price=CapCleanPrice(int(required["cap_clean_price"])),
        trim=str(vehicle["trim"]) if vehicle["trim"] is not None else None,
    )


def _compare_vehicle(args: Namespace, *, stdin: TextIO) -> int:
    try:
        lot = _build_ad_hoc_lot(_vehicle_values(args, stdin=stdin))
        snapshot = _market_snapshot_from_args(args)
        opportunities = OpportunitySearch().search((lot,), snapshot)
        candidate = opportunities.candidates[0]
    except (OSError, TypeError, ValueError, FileNotFoundError) as error:
        _write_json(_error_envelope(str(error), code="invalid_input"))
        return 1

    result = {
        "status": "success",
        **_serialize_candidate_result(candidate),
        "market_snapshot_summary": {"total_listings_observed": len(snapshot.listings)},
    }
    _write_json(result, pretty=args.pretty)
    return 0


def _load_pair(args: Namespace) -> OpportunityList:
    bca_dir = _capture_path(args.data_root, SourceKind.BCA, args.bca_capture_id)
    auto_dir = _capture_path(
        args.data_root, SourceKind.AUTOTRADER, args.autotrader_capture_id
    )
    lots = BcaAcquisition().acquire(_read_json_records(bca_dir / "records.json"))
    snapshot = AutoTraderAcquisition().acquire_snapshot(
        _read_json_records(auto_dir / "records.json")
    )
    return OpportunitySearch().search(lots, snapshot)


def _match_pair(args: Namespace, *, stdin: TextIO) -> int:
    try:
        opportunities = _load_pair(args)
    except (OSError, TypeError, ValueError, FileNotFoundError) as error:
        _write_json(_error_envelope(str(error), code="capture_error"))
        return 1
    candidates = _serialize_opportunity_list(opportunities)
    _write_json(
        {
            "status": "success",
            "bca_capture_id": args.bca_capture_id,
            "autotrader_capture_id": args.autotrader_capture_id,
            "opportunity_list": {"candidates": candidates},
        },
        pretty=args.pretty,
    )
    return 0


def _autotrader_query_values(
    args: Namespace, *, stdin: TextIO
) -> AutoTraderSearchParams:
    if getattr(args, "json_input", False):
        flags = (
            getattr(args, "url", None),
            getattr(args, "make", None),
            getattr(args, "model", None),
            getattr(args, "year", None),
            getattr(args, "year_from", None),
            getattr(args, "year_to", None),
            getattr(args, "mileage", None),
            getattr(args, "min_mileage", None),
            getattr(args, "max_mileage", None),
            getattr(args, "engine_size", None),
            getattr(args, "min_engine_size", None),
            getattr(args, "max_engine_size", None),
            getattr(args, "fuel_type", None),
            getattr(args, "transmission", None),
            getattr(args, "body_types", None),
            getattr(args, "trim", None),
            getattr(args, "postcode", None),
        )
        if any(value is not None for value in flags):
            raise ValueError("--json-input cannot be combined with search flags")
        try:
            payload = json.load(stdin)
        except (json.JSONDecodeError, OSError) as error:
            raise ValueError(f"invalid JSON input: {error}") from error
        if not isinstance(payload, dict):
            raise ValueError("JSON input must be an object")

        body_types = payload.get("body_types")
        if body_types is None:
            bt = payload.get("body_type") or payload.get("body_style")
            if bt is not None:
                body_types = [bt] if isinstance(bt, str) else list(bt)
        elif isinstance(body_types, str):
            body_types = [body_types]

        result: AutoTraderSearchParams = {
            "make": payload.get("make"),
            "model": payload.get("model_variant", payload.get("model")),
            "year": payload.get("registration_year", payload.get("year")),
            "year_from": payload.get("year_from"),
            "year_to": payload.get("year_to"),
            "mileage": payload.get("mileage"),
            "min_mileage": payload.get("min_mileage", payload.get("minimum_mileage")),
            "max_mileage": payload.get("max_mileage", payload.get("maximum_mileage")),
            "engine_size": payload.get("engine_size"),
            "min_engine_size": payload.get(
                "min_engine_size", payload.get("minimum_badge_engine_size")
            ),
            "max_engine_size": payload.get(
                "max_engine_size", payload.get("maximum_badge_engine_size")
            ),
            "fuel_type": payload.get("fuel_type"),
            "transmission": payload.get("transmission"),
            "body_types": body_types,
            "trim": payload.get("trim", payload.get("aggregated_trim", payload.get("aggregatedTrim"))),
            "postcode": payload.get("postcode"),
        }
        return result

    static_result: AutoTraderSearchParams = {
        "make": getattr(args, "make", None),
        "model": getattr(args, "model", None),
        "year": getattr(args, "year", None),
        "year_from": getattr(args, "year_from", None),
        "year_to": getattr(args, "year_to", None),
        "mileage": getattr(args, "mileage", None),
        "min_mileage": getattr(args, "min_mileage", None),
        "max_mileage": getattr(args, "max_mileage", None),
        "engine_size": getattr(args, "engine_size", None),
        "min_engine_size": getattr(args, "min_engine_size", None),
        "max_engine_size": getattr(args, "max_engine_size", None),
        "fuel_type": getattr(args, "fuel_type", None),
        "transmission": getattr(args, "transmission", None),
        "body_types": getattr(args, "body_types", None),
        "trim": getattr(args, "trim", None),
        "postcode": getattr(args, "postcode", None),
    }
    return static_result


def _resolve_autotrader_url(args: Namespace, *, stdin: TextIO) -> str:
    if getattr(args, "url", None):
        return str(args.url).strip()
    query = _autotrader_query_values(args, stdin=stdin)
    return build_autotrader_search_url(query)


def _has_autotrader_query_args(args: Namespace) -> bool:
    if getattr(args, "url", None) is not None or getattr(args, "json_input", False):
        return True
    return any(
        value is not None
        for value in (
            getattr(args, "make", None),
            getattr(args, "model", None),
            getattr(args, "year", None),
            getattr(args, "year_from", None),
            getattr(args, "year_to", None),
            getattr(args, "mileage", None),
            getattr(args, "min_mileage", None),
            getattr(args, "max_mileage", None),
            getattr(args, "engine_size", None),
            getattr(args, "min_engine_size", None),
            getattr(args, "max_engine_size", None),
            getattr(args, "fuel_type", None),
            getattr(args, "transmission", None),
            getattr(args, "body_types", None),
            getattr(args, "trim", None),
            getattr(args, "postcode", None),
        )
    )


def _build_autotrader_url_cmd(args: Namespace, *, stdin: TextIO) -> int:
    try:
        url = _resolve_autotrader_url(args, stdin=stdin)
    except (OSError, TypeError, ValueError) as error:
        _write_json(_error_envelope(str(error), code="invalid_input"))
        return 1
    _write_json({"status": "success", "url": url}, pretty=args.pretty)
    return 0


def _capture_result[T_Record](
    outcome: CaptureOutcome[T_Record], capture_dir: Path
) -> dict[str, JsonValue]:
    return {
        "capture_id": capture_dir.name,
        "source": outcome.source.value,
        "search_name": outcome.search_name,
        "stop_reason": outcome.stop_reason.value,
        "stop_message": outcome.stop_message,
        "pages_captured": len(outcome.pages),
        "records_captured": len(outcome.records),
        "records_skipped": len(outcome.skipped),
        "capture_dir": str(capture_dir),
        "records": list(outcome.records),
        "skipped": [
            {
                "record_id": item.record_id,
                "page_number": item.page_number,
                "card_index": item.card_index,
                "reasons": list(item.reasons),
            }
            for item in outcome.skipped
        ],
    }


def _stderr(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _countdown_pacing(seconds: float, *, movement: str) -> None:
    remaining = int(seconds)
    _stderr(f"Pacing cadence: {remaining}s before next {movement}...")
    while remaining > 0:
        time.sleep(1)
        remaining -= 1
        if remaining % 10 == 0 or remaining <= 5:
            _stderr(f"{remaining}s remaining...")
    _stderr("Ready.")


def _read_stdin_line(stdin: TextIO) -> str:
    line = stdin.readline()
    if line == "":
        raise EOFError("stdin closed before a response was provided")
    return line.strip()


class SupportsBrowserLocator(Protocol):
    @property
    def first(self) -> SupportsBrowserLocator: ...

    def count(self) -> int: ...

    def is_visible(self) -> bool: ...

    def click(self, *, timeout: int) -> None: ...


class SupportsBrowserPage(Protocol):
    @property
    def url(self) -> str: ...

    def content(self) -> str: ...

    def evaluate(self, expression: str) -> JsonValue: ...

    def goto(self, url: str, *, wait_until: str) -> None: ...

    def locator(self, selector: str) -> SupportsBrowserLocator: ...

    def wait_for_timeout(self, milliseconds: int) -> None: ...


class _PlaywrightPageSource:
    """PageSource adapter for a visible BCA or Auto Trader page."""

    def __init__(
        self, page: SupportsBrowserPage, source: SourceKind, *, stdin: TextIO
    ) -> None:
        self._page = page
        self._source = source
        self._stdin = stdin
        self._next_page_number = 2

    def current_html(self) -> str:
        self._raise_if_login_redirect()
        try:
            self._page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
            self._page.wait_for_timeout(500)
            self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            self._page.wait_for_timeout(1000)
            return self._page.content()
        except (PlaywrightError, TimeoutError, RuntimeError, ValueError) as error:
            raise CaptureChallengeError(f"Could not read the current page: {error}") from error

    def advance(self) -> bool:
        self._raise_if_login_redirect()
        try:
            if self._source is SourceKind.AUTOTRADER:
                for _ in range(3):
                    self._page.evaluate(
                        "window.scrollTo(0, document.body.scrollHeight)"
                    )
                    self._page.wait_for_timeout(1200)
                return True

            next_number = self._next_page_number
            self._next_page_number += 1
            selectors = (
                "button[aria-label='Go to next page']",
                f"button[aria-label='Go to page {next_number}']",
                "button:has-text('next')",
                "a:has-text('next')",
                "a[rel='next']",
            )
            for selector in selectors:
                button = self._page.locator(selector)
                if button.count() > 0 and button.first.is_visible():
                    _stderr(f"Clicking next page using '{selector}'.")
                    button.first.click(timeout=5000)
                    self._page.wait_for_timeout(3000)
                    self._raise_if_login_redirect()
                    return True
            _stderr(
                f"Click page {next_number} in the browser and press ENTER, "
                "or type 'q' to stop."
            )
            return _read_stdin_line(self._stdin).lower() != "q"
        except (PlaywrightError, TimeoutError, RuntimeError, ValueError) as error:
            raise CaptureChallengeError(
                f"Could not advance the search results: {error}"
            ) from error

    def _raise_if_login_redirect(self) -> None:
        url = str(self._page.url).lower()
        if any(token in url for token in _LOGIN_TOKENS):
            raise CaptureChallengeError(
                "The browser was redirected to a login page; halting without bypass."
            )


def _validate_catalogue_url(catalogue_url: str) -> None:
    parsed = urlsplit(catalogue_url)
    if parsed.scheme != "https" or parsed.hostname not in {"bca.co.uk", "www.bca.co.uk"}:
        raise ValueError("catalogue URL must use HTTPS and a bca.co.uk hostname")
    if parsed.username is not None or parsed.password is not None or parsed.port is not None:
        raise ValueError("catalogue URL must not contain userinfo or a custom port")


def _wait_for_bca_cards(
    page: SupportsBrowserPage, catalogue_url: str, timeout: float
) -> None:
    """Wait for the first lot card, recovering once from a login redirect."""
    if timeout <= 0:
        raise ValueError("auth timeout must be greater than zero")
    deadline = time.monotonic() + timeout
    prompted = False
    recovered = False
    catalogue_url_normalized = catalogue_url.rstrip("/").lower()
    while time.monotonic() < deadline:
        url = str(page.url).lower()
        challenge = None
        with suppress(
            AttributeError, PlaywrightError, RuntimeError, TimeoutError, ValueError
        ):
            challenge = detect_bot_challenge_markers(page.content())
        if challenge is not None:
            raise CaptureChallengeError(challenge)

        on_login = any(token in url for token in _LOGIN_TOKENS)
        if on_login and not prompted:
            _stderr(
                "BCA login required. Use the visible browser and LastPass if needed; "
                f"capture starts when lot cards appear (timeout {timeout:g}s)."
            )
            prompted = True
        if not on_login:
            with suppress(PlaywrightError, RuntimeError, ValueError):
                locator = page.locator(_BCA_CARD_SELECTOR)
                if locator.count() > 0:
                    return
            if (
                prompted
                and not recovered
                and url.rstrip("/") != catalogue_url_normalized
            ):
                _stderr("Authentication completed; returning to the catalogue URL.")
                page.goto(catalogue_url, wait_until="domcontentloaded")
                recovered = True
        page.wait_for_timeout(250)
    raise TimeoutError(
        f"No BCA lot cards detected before auth timeout ({timeout:g}s); "
        "partial data, if any, is saved."
    )


def _dismiss_autotrader_cookies(page: SupportsBrowserPage) -> None:
    """Attempt to dismiss Auto Trader cookie consent popups gracefully."""
    selectors = (
        "button:has-text('Accept all')",
        "button:has-text('Accept All')",
        "button:has-text('Accept')",
        "button[id*='accept']",
        "button[aria-label*='Accept']",
        "button[aria-label*='accept']",
    )
    for selector in selectors:
        with suppress(Exception):
            loc = page.locator(selector)
            if loc.count() > 0 and loc.first.is_visible():
                loc.first.click(timeout=2000)
                page.wait_for_timeout(500)
                return


def _run_browser_capture(
    args: Namespace, source: SourceKind, *, stdin: TextIO
) -> int:
    try:
        if args.result_limit < 1:
            raise ValueError("result limit must be at least 1")
        if args.move_delay <= 0:
            raise ValueError("move delay must be greater than zero")
        if source is SourceKind.BCA:
            _validate_catalogue_url(args.catalogue_url)
            if args.auth_timeout <= 0:
                raise ValueError("auth timeout must be greater than zero")
    except ValueError as error:
        _write_json(_error_envelope(str(error), code="invalid_input"))
        return 1

    if sync_playwright is None:
        _write_json(
            _error_envelope(
                "Playwright is required for browser capture; install playwright "
                "and a supported browser.",
                code="playwright_missing",
            )
        )
        return 2

    outcome: CaptureOutcome[Any] | None = None
    capture_dir: Path | None = None
    try:
        with sync_playwright() as playwright:
            context = None
            browser = None
            try:
                headless = bool(getattr(args, "headless", False))
                if source is SourceKind.BCA:
                    if args.profile_dir is not None:
                        context = playwright.chromium.launch_persistent_context(
                            str(args.profile_dir), channel="chrome", headless=headless
                        )
                        page = context.pages[0] if context.pages else context.new_page()
                    else:
                        browser = playwright.chromium.launch(
                            channel="chrome", headless=headless
                        )
                        context = browser.new_context()
                        page = context.new_page()
                    page.goto(args.catalogue_url, wait_until="domcontentloaded")
                    _wait_for_bca_cards(page, args.catalogue_url, args.auth_timeout)
                    _stderr("BCA lot cards detected; starting capture.")
                else:
                    browser = playwright.chromium.launch(
                        channel="chrome", headless=headless
                    )
                    context = browser.new_context()
                    page = context.new_page()

                    if _has_autotrader_query_args(args):
                        target_url = _resolve_autotrader_url(args, stdin=stdin)
                        page.goto(target_url, wait_until="domcontentloaded")
                        _dismiss_autotrader_cookies(page)
                        _stderr(f"Auto Trader search loaded: {target_url}; starting capture.")
                    else:
                        page.goto("https://www.autotrader.co.uk", wait_until="domcontentloaded")
                        _stderr(
                            "Auto Trader browser opened. Run one search, then press ENTER here."
                        )
                        _read_stdin_line(stdin)

                options = CaptureOptions(
                    search_name=args.search_name,
                    source=source,
                    movement_limit=args.result_limit,
                    movement_delay_seconds=args.move_delay,
                    data_dir=args.data_dir,
                )
                movement = "scroll" if source is SourceKind.AUTOTRADER else "page"
                outcome = run_capture(
                    options,
                    _PlaywrightPageSource(page, source, stdin=stdin),
                    (
                        autotrader_capture_strategy
                        if source is SourceKind.AUTOTRADER
                        else bca_capture_strategy
                    ),
                    hooks=CaptureHooks(
                        pace=lambda seconds: _countdown_pacing(
                            seconds, movement=movement
                        )
                    ),
                )
                capture_dir = save_capture(outcome, options)
            finally:
                if source is SourceKind.BCA and context is not None:
                    context.close()
                if browser is not None:
                    browser.close()
    except (EOFError, KeyboardInterrupt):
        _write_json(_error_envelope("capture interrupted by user", code="interrupted"))
        return 1
    except (OSError, PlaywrightError, TimeoutError, ValueError, CaptureChallengeError) as error:
        _write_json(_error_envelope(str(error), code="capture_error"))
        return 1

    if outcome is None or capture_dir is None:
        _write_json(_error_envelope("capture produced no result", code="capture_error"))
        return 1
    result_status = (
        "stopped"
        if outcome.stop_reason in {
            StopReason.CHALLENGE_DETECTED,
            StopReason.USER_STOPPED,
        }
        else "success"
    )
    _write_json(
        {"status": result_status, **_capture_result(outcome, capture_dir)},
        pretty=args.pretty,
    )
    return 0


def _add_autotrader_query_arguments(parser: ArgumentParser) -> None:
    parser.add_argument("--url", help="Direct Auto Trader search URL to load.")
    parser.add_argument(
        "--json-input",
        action="store_true",
        help="Read vehicle/search JSON object from stdin.",
    )
    parser.add_argument("--make", help="Vehicle make (e.g. Audi, BMW).")
    parser.add_argument("--model", help="Vehicle model variant (e.g. A3, 1 Series).")
    parser.add_argument("--year", type=int, help="Vehicle registration year.")
    parser.add_argument("--year-from", type=int, help="Earliest registration year.")
    parser.add_argument("--year-to", type=int, help="Latest registration year.")
    parser.add_argument(
        "--mileage",
        type=int,
        help="Vehicle mileage in miles (applies ±15,000 miles window if min/max omitted).",
    )
    parser.add_argument(
        "--min-mileage", type=int, help="Minimum vehicle mileage in miles."
    )
    parser.add_argument(
        "--max-mileage", type=int, help="Maximum vehicle mileage in miles."
    )
    parser.add_argument(
        "--engine-size",
        help="Engine displacement in litres (e.g. 1.4).",
    )
    parser.add_argument(
        "--min-engine-size",
        help="Minimum badge engine size in litres (e.g. 1.4).",
    )
    parser.add_argument(
        "--max-engine-size",
        help="Maximum badge engine size in litres (e.g. 1.6).",
    )
    parser.add_argument("--fuel-type", help="Observed fuel type (e.g. Petrol, Diesel).")
    parser.add_argument(
        "--transmission", help="Observed transmission (e.g. Automatic, Manual)."
    )
    parser.add_argument(
        "--body-type",
        action="append",
        dest="body_types",
        help="Vehicle body style (e.g. Hatchback, Saloon; can be specified multiple times).",
    )
    parser.add_argument(
        "--trim", help="Vehicle trim or derivative (maps to aggregatedTrim, e.g. TFSI)."
    )
    parser.add_argument(
        "--postcode",
        help="UK postcode for distance calculation (default: NG2 3JW).",
    )


def _build_parser() -> ArgumentParser:
    parser = ArgumentParser(
        prog="car-flip",
        description=(
            "JSON-first car-flip agent tools for user-assisted source capture "
            "and vehicle valuation."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    compare = subparsers.add_parser(
        "compare-vehicle", help="Compare one vehicle against Auto Trader evidence."
    )
    compare.add_argument(
        "--json-input", action="store_true", help="Read vehicle JSON from stdin."
    )
    compare.add_argument("--make", help="Vehicle make.")
    compare.add_argument("--model", help="Vehicle model variant.")
    compare.add_argument("--year", type=int, help="Vehicle registration year.")
    compare.add_argument("--mileage", type=int, help="Vehicle mileage in miles.")
    compare.add_argument(
        "--cap-clean-price", type=int, help="CAP Clean price in whole pounds."
    )
    compare.add_argument("--trim", help="Optional vehicle trim or derivative.")
    compare.add_argument("--fuel-type", help="Optional observed fuel type.")
    compare.add_argument("--transmission", help="Optional observed transmission.")
    compare.add_argument(
        "--market-file", type=Path, help="Path to JSON Auto Trader records."
    )
    compare.add_argument(
        "--autotrader-capture-id", help="Saved Auto Trader capture ID to load."
    )
    compare.add_argument(
        "--data-root",
        type=Path,
        default=Path("data/captures"),
        help="Root directory containing source capture directories.",
    )
    compare.add_argument(
        "--pretty", action="store_true", help="Pretty-print the JSON response."
    )
    compare.set_defaults(handler=_compare_vehicle)

    build_url = subparsers.add_parser(
        "build-autotrader-url",
        help="Construct a scoped Auto Trader search URL from vehicle criteria.",
    )
    _add_autotrader_query_arguments(build_url)
    build_url.add_argument(
        "--pretty", action="store_true", help="Pretty-print the JSON response."
    )
    build_url.set_defaults(handler=_build_autotrader_url_cmd)

    def add_capture_parser(name: str, help_text: str, source: SourceKind) -> None:
        capture = subparsers.add_parser(name, help=help_text)
        capture.add_argument(
            "--search-name", required=True, help="Name used to label this capture."
        )
        capture.add_argument(
            "--result-limit",
            type=int,
            default=5,
            help="Maximum number of pages or scroll batches to capture.",
        )
        capture.add_argument(
            "--move-delay",
            type=float,
            default=60.0,
            help="Positive seconds to wait between browser movements.",
        )
        capture.add_argument(
            "--data-dir",
            type=Path,
            default=Path(f"data/captures/{source.value}"),
            help="Directory where this source's capture is saved.",
        )
        capture.add_argument(
            "--pretty", action="store_true", help="Pretty-print the JSON response."
        )
        capture.add_argument(
            "--headless",
            action="store_true",
            help="Run browser in headless mode (default: headed).",
        )
        if source is SourceKind.BCA:
            capture.add_argument(
                "--catalogue-url",
                default="https://www.bca.co.uk",
                help="HTTPS BCA catalogue URL to open and capture.",
            )
            capture.add_argument(
                "--profile-dir",
                type=Path,
                default=None,
                help=(
                    "Optional Chrome user-data directory; omit it for a fresh "
                    "ephemeral session."
                ),
            )
            capture.add_argument(
                "--auth-timeout",
                type=float,
                default=180.0,
                help="Positive seconds to wait for login and lot cards.",
            )
        elif source is SourceKind.AUTOTRADER:
            _add_autotrader_query_arguments(capture)

        capture.set_defaults(
            handler=lambda args, *, stdin: _run_browser_capture(
                args, source, stdin=stdin
            )
        )

    add_capture_parser("search-bca", "Capture BCA lots in a visible Chrome session.", SourceKind.BCA)
    add_capture_parser("search-autotrader", "Capture Auto Trader listings with headed infinite scroll.", SourceKind.AUTOTRADER)

    pair = subparsers.add_parser(
        "match-pair", help="Match two saved captures into an OpportunityList."
    )
    pair.add_argument(
        "--bca-capture-id", required=True, help="Saved BCA capture ID to load."
    )
    pair.add_argument(
        "--autotrader-capture-id",
        required=True,
        help="Saved Auto Trader capture ID to load.",
    )
    pair.add_argument(
        "--data-root",
        type=Path,
        default=Path("data/captures"),
        help="Root directory containing BCA and Auto Trader captures.",
    )
    pair.add_argument(
        "--pretty", action="store_true", help="Pretty-print the JSON response."
    )
    pair.set_defaults(handler=_match_pair)

    schema = subparsers.add_parser("tool-schema", help="Print OpenAI/Hermes tool-call JSON schemas.")
    schema.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    schema.set_defaults(handler=_tool_schema)
    return parser


def _tool_schema(args: Namespace, *, stdin: TextIO) -> int:
    schemas = [
        {
            "type": "function",
            "function": {
                "name": "build-autotrader-url",
                "description": (
                    "Construct a scoped Auto Trader search URL with standard defaults "
                    "(price-asc sort, clean condition, private/trade sellers) from vehicle "
                    "attributes or JSON stdin."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "json_input": {
                            "type": "boolean",
                            "description": "Read search parameters from JSON stdin.",
                        },
                        "url": {"type": "string", "description": "Direct search URL."},
                        "make": {"type": "string", "description": "Vehicle make."},
                        "model": {"type": "string", "description": "Vehicle model variant."},
                        "year": {"type": "integer", "description": "Registration year."},
                        "year_from": {"type": "integer", "description": "Earliest registration year."},
                        "year_to": {"type": "integer", "description": "Latest registration year."},
                        "mileage": {
                            "type": "integer",
                            "minimum": 0,
                            "description": "Mileage (applies ±15,000 miles window if min/max omitted).",
                        },
                        "min_mileage": {"type": "integer", "minimum": 0, "description": "Minimum mileage."},
                        "max_mileage": {"type": "integer", "minimum": 0, "description": "Maximum mileage."},
                        "engine_size": {"type": "number", "description": "Engine displacement in litres."},
                        "min_engine_size": {"type": "number", "description": "Minimum badge engine size."},
                        "max_engine_size": {"type": "number", "description": "Maximum badge engine size."},
                        "fuel_type": {"type": "string", "description": "Fuel type (e.g. Petrol, Diesel)."},
                        "transmission": {"type": "string", "description": "Transmission (e.g. Automatic, Manual)."},
                        "body_type": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Body types (e.g. Hatchback, Saloon).",
                        },
                        "trim": {"type": "string", "description": "Trim/derivative (e.g. TFSI, AMG Line)."},
                        "postcode": {"type": "string", "description": "UK postcode (default: NG2 3JW)."},
                        "pretty": {"type": "boolean", "description": "Pretty-print JSON."},
                    },
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "compare-vehicle",
                "description": (
                    "Compare an ad-hoc vehicle with Auto Trader market evidence. "
                    "Vehicle fields may be supplied directly or through JSON stdin."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "json_input": {
                            "type": "boolean",
                            "description": "Read the vehicle object from JSON stdin.",
                        },
                        "make": {"type": "string", "description": "Vehicle make."},
                        "model": {
                            "type": "string",
                            "description": "Vehicle model variant.",
                        },
                        "year": {
                            "type": "integer",
                            "description": "Vehicle registration year.",
                        },
                        "mileage": {
                            "type": "integer",
                            "minimum": 0,
                            "description": "Vehicle mileage in miles.",
                        },
                        "cap_clean_price": {
                            "type": "integer",
                            "minimum": 0,
                            "description": "CAP Clean price in whole pounds.",
                        },
                        "trim": {
                            "type": "string",
                            "description": "Optional vehicle trim or derivative.",
                        },
                        "fuel_type": {
                            "type": "string",
                            "description": "Optional observed fuel type.",
                        },
                        "transmission": {
                            "type": "string",
                            "description": "Optional observed transmission.",
                        },
                        "market_file": {
                            "type": "string",
                            "description": "Path to JSON Auto Trader records.",
                        },
                        "autotrader_capture_id": {
                            "type": "string",
                            "description": "Saved Auto Trader capture ID to load.",
                        },
                        "data_root": {
                            "type": "string",
                            "default": "data/captures",
                            "description": "Root directory containing captures.",
                        },
                        "pretty": {
                            "type": "boolean",
                            "description": "Pretty-print the JSON response.",
                        },
                    },
                    "required": [
                        "make",
                        "model",
                        "year",
                        "mileage",
                        "cap_clean_price",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search-bca",
                "description": (
                    "Capture BCA lots through a visible, user-assisted Chrome "
                    "session; challenges halt without bypass."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "search_name": {
                            "type": "string",
                            "description": "Name used to label this capture.",
                        },
                        "result_limit": {
                            "type": "integer",
                            "minimum": 1,
                            "default": 5,
                            "description": "Maximum pages to capture.",
                        },
                        "move_delay": {
                            "type": "number",
                            "exclusiveMinimum": 0,
                            "default": 60,
                            "description": "Seconds between page movements.",
                        },
                        "data_dir": {
                            "type": "string",
                            "default": "data/captures/bca",
                            "description": "Directory where the capture is saved.",
                        },
                        "pretty": {
                            "type": "boolean",
                            "description": "Pretty-print the JSON response.",
                        },
                        "headless": {
                            "type": "boolean",
                            "default": False,
                            "description": "Run browser in headless mode (default: headed).",
                        },
                        "catalogue_url": {
                            "type": "string",
                            "format": "uri",
                            "default": "https://www.bca.co.uk",
                            "description": "HTTPS BCA catalogue URL to capture.",
                        },
                        "profile_dir": {
                            "type": ["string", "null"],
                            "description": (
                                "Optional Chrome user-data directory; null uses "
                                "an ephemeral session."
                            ),
                        },
                        "auth_timeout": {
                            "type": "number",
                            "exclusiveMinimum": 0,
                            "default": 180,
                            "description": "Seconds to wait for login and lot cards.",
                        },
                    },
                    "required": ["search_name"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search-autotrader",
                "description": (
                    "Capture Auto Trader listings through Playwright infinite scroll. "
                    "When vehicle parameters or --url are provided, navigates directly to "
                    "scoped results and captures automatically without user prompts."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "search_name": {
                            "type": "string",
                            "description": "Name used to label this capture.",
                        },
                        "result_limit": {
                            "type": "integer",
                            "minimum": 1,
                            "default": 5,
                            "description": "Maximum scroll batches to capture.",
                        },
                        "move_delay": {
                            "type": "number",
                            "exclusiveMinimum": 0,
                            "default": 60,
                            "description": "Seconds between scroll movements.",
                        },
                        "data_dir": {
                            "type": "string",
                            "default": "data/captures/autotrader",
                            "description": "Directory where the capture is saved.",
                        },
                        "pretty": {
                            "type": "boolean",
                            "description": "Pretty-print the JSON response.",
                        },
                        "headless": {
                            "type": "boolean",
                            "default": False,
                            "description": "Run browser in headless mode (default: headed).",
                        },
                        "url": {"type": "string", "description": "Direct search URL."},
                        "json_input": {"type": "boolean", "description": "Read search parameters from JSON stdin."},
                        "make": {"type": "string", "description": "Vehicle make."},
                        "model": {"type": "string", "description": "Vehicle model variant."},
                        "year": {"type": "integer", "description": "Registration year."},
                        "year_from": {"type": "integer", "description": "Earliest registration year."},
                        "year_to": {"type": "integer", "description": "Latest registration year."},
                        "mileage": {
                            "type": "integer",
                            "minimum": 0,
                            "description": "Mileage (applies ±15,000 miles window if min/max omitted).",
                        },
                        "min_mileage": {"type": "integer", "minimum": 0, "description": "Minimum mileage."},
                        "max_mileage": {"type": "integer", "minimum": 0, "description": "Maximum mileage."},
                        "engine_size": {"type": "number", "description": "Engine displacement in litres."},
                        "min_engine_size": {"type": "number", "description": "Minimum badge engine size."},
                        "max_engine_size": {"type": "number", "description": "Maximum badge engine size."},
                        "fuel_type": {"type": "string", "description": "Fuel type (e.g. Petrol, Diesel)."},
                        "transmission": {"type": "string", "description": "Transmission (e.g. Automatic, Manual)."},
                        "body_type": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Body types (e.g. Hatchback, Saloon).",
                        },
                        "trim": {"type": "string", "description": "Trim/derivative (e.g. TFSI, AMG Line)."},
                        "postcode": {"type": "string", "description": "UK postcode (default: NG2 3JW)."},
                    },
                    "required": ["search_name"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "match-pair",
                "description": "Match saved BCA and Auto Trader captures.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "bca_capture_id": {
                            "type": "string",
                            "description": "Saved BCA capture ID to load.",
                        },
                        "autotrader_capture_id": {
                            "type": "string",
                            "description": "Saved Auto Trader capture ID to load.",
                        },
                        "data_root": {
                            "type": "string",
                            "default": "data/captures",
                            "description": "Root directory containing captures.",
                        },
                        "pretty": {
                            "type": "boolean",
                            "description": "Pretty-print the JSON response.",
                        },
                    },
                    "required": ["bca_capture_id", "autotrader_capture_id"],
                    "additionalProperties": False,
                },
            },
        },
    ]
    _write_json(schemas, pretty=args.pretty)
    return 0


def main(argv: Sequence[str] | None = None, *, stdin: TextIO | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    input_stream = sys.stdin if stdin is None else stdin
    try:
        return int(args.handler(args, stdin=input_stream))
    except ValueError as error:
        _write_json(_error_envelope(str(error), code="invalid_input"))
        return 1


if __name__ == "__main__":  # pragma: no cover - exercised through python -m
    sys.exit(main())
