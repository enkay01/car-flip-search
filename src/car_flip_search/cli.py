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
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

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
    MarketSnapshot,
    OpportunityList,
)
from .opportunity_search import OpportunitySearch
from .source_acquisition import AutoTraderAcquisition, BcaAcquisition

try:  # Playwright is optional for users who only run comparison commands.
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - exercised when Playwright is absent
    PlaywrightError = RuntimeError
    sync_playwright = None


_BCA_CARD_SELECTOR = (
    '[data-testid="card-link-desktop"], '
    '[data-testid="condition-report-icon"], a[href*="/lot/"]'
)
_LOGIN_TOKENS = ("/login", "/signin", "/sign-in", "/logon")


def _write_json(value: object, *, pretty: bool = False) -> None:
    print(json.dumps(value, indent=2 if pretty else None, sort_keys=True))


def _error_envelope(message: str, *, code: str = "error") -> dict[str, object]:
    return {"status": "error", "error": message, "code": code}


def _serialize_identity(identity: CoreVehicleIdentity) -> dict[str, object]:
    return {
        "make": identity.make,
        "model_variant": identity.model_variant,
        "registration_year": identity.registration_year,
        "fuel_type": identity.fuel_type,
        "transmission": identity.transmission,
        "body_style": identity.body_style,
        "door_count": identity.door_count,
    }


def _serialize_candidate(candidate: CandidateVehicle) -> dict[str, object]:
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


def _serialize_comparable(comparable: Any) -> dict[str, object]:
    return {
        "listing_id": comparable.listing_id.value,
        "identity": _serialize_identity(comparable.identity),
        "advertised_price_pounds": comparable.advertised_price.pounds,
        "mileage": comparable.mileage,
        "seller_type": comparable.seller_type.value,
        "trim": comparable.trim,
        "trim_match": comparable.trim_match,
    }


def _serialize_reference(reference: Any) -> dict[str, object]:
    return {
        "listing_id": reference.listing_id.value,
        "identity": _serialize_identity(reference.identity),
        "advertised_price_pounds": reference.advertised_price.pounds,
        "mileage": reference.mileage,
        "seller_type": reference.seller_type.value,
        "trim": reference.trim,
    }


def _serialize_candidate_valuation(candidate: CandidateVehicle) -> dict[str, object]:
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


def _serialize_candidate_result(candidate: CandidateVehicle) -> dict[str, object]:
    comparables = candidate.comparable_evidence.market_comparables
    references = candidate.retail_floor_evidence.high_mileage_references
    return {
        "candidate": _serialize_candidate(candidate),
        "valuation": _serialize_candidate_valuation(candidate),
        "market_comparables": [_serialize_comparable(item) for item in comparables],
        "high_mileage_references": [_serialize_reference(item) for item in references],
    }


def _serialize_opportunity_list(opportunities: OpportunityList) -> list[dict[str, object]]:
    return [
        {
            **_serialize_candidate_result(candidate),
            "auction_lot_id": candidate.auction_lot.id.value,
        }
        for candidate in opportunities.candidates
    ]


def _read_json_records(path: Path) -> list[dict[str, object]]:
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


def _vehicle_values(args: Namespace) -> dict[str, object | None]:
    if args.json_input:
        flag_names = (
            "make",
            "model",
            "year",
            "mileage",
            "cap_clean_price",
            "trim",
            "fuel_type",
            "transmission",
        )
        if any(getattr(args, name) is not None for name in flag_names):
            raise ValueError("--json-input cannot be combined with vehicle flags")
        try:
            payload = json.load(sys.stdin)
        except (json.JSONDecodeError, OSError) as error:
            raise ValueError(f"invalid JSON input: {error}") from error
        if not isinstance(payload, dict):
            raise ValueError("JSON input must be an object")
        return {
            "make": payload.get("make"),
            "model": payload.get("model_variant", payload.get("model")),
            "year": payload.get("registration_year", payload.get("year")),
            "mileage": payload.get("mileage"),
            "cap_clean_price": payload.get(
                "cap_clean_price", payload.get("cap_price")
            ),
            "trim": payload.get("trim"),
            "fuel_type": payload.get("fuel_type"),
            "transmission": payload.get("transmission"),
        }
    return {
        "make": args.make,
        "model": args.model,
        "year": args.year,
        "mileage": args.mileage,
        "cap_clean_price": args.cap_clean_price,
        "trim": args.trim,
        "fuel_type": args.fuel_type,
        "transmission": args.transmission,
    }


def _build_ad_hoc_lot(values: dict[str, object | None]) -> AuctionLot:
    required = {
        "make": values.get("make"),
        "model": values.get("model"),
        "year": values.get("year"),
        "mileage": values.get("mileage"),
        "cap_clean_price": values.get("cap_clean_price"),
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        raise ValueError(
            "missing required parameters: " + ", ".join(missing)
        )
    make_str = str(required["make"]).strip()
    model_str = str(required["model"]).strip()
    if make_str.casefold() == "mercedes-benz":
        lowered = model_str.casefold()
        if lowered.endswith("dh"):
            model_str = model_str[:-2]
        elif lowered.endswith("d"):
            model_str = model_str[:-1]
    return AuctionLot(
        id=AuctionLotId("AD-HOC-INPUT"),
        identity=CoreVehicleIdentity(
            make=make_str,
            model_variant=model_str,
            registration_year=int(required["year"]),
            fuel_type=(
                str(values["fuel_type"]) if values.get("fuel_type") is not None else None
            ),
            transmission=(
                str(values["transmission"])
                if values.get("transmission") is not None
                else None
            ),
        ),
        mileage=int(required["mileage"]),
        cap_clean_price=CapCleanPrice(int(required["cap_clean_price"])),
        trim=str(values["trim"]) if values.get("trim") is not None else None,
    )


def _compare_vehicle(args: Namespace) -> int:
    try:
        lot = _build_ad_hoc_lot(_vehicle_values(args))
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


def _match_pair(args: Namespace) -> int:
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


def _capture_result[T_Record](
    outcome: CaptureOutcome[T_Record], capture_dir: Path
) -> dict[str, object]:
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


class _PlaywrightPageSource:
    """PageSource adapter for a visible BCA or Auto Trader page."""

    def __init__(self, page: Any, source: SourceKind) -> None:
        self._page = page
        self._source = source
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
            return input().strip().lower() != "q"
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


def _wait_for_bca_cards(page: Any, catalogue_url: str, timeout: float) -> None:
    """Wait for the first lot card, recovering once from a login redirect."""
    if timeout <= 0:
        raise ValueError("auth timeout must be greater than zero")
    deadline = time.monotonic() + timeout
    prompted = False
    recovered = False
    while time.monotonic() < deadline:
        url = str(page.url).lower()
        on_login = any(token in url for token in _LOGIN_TOKENS)
        if on_login and not prompted:
            _stderr(
                "BCA login required. Use the visible browser and LastPass if needed; "
                f"capture starts when lot cards appear (timeout {timeout:g}s)."
            )
            prompted = True
        if not on_login:
            try:
                locator = page.locator(_BCA_CARD_SELECTOR)
                if locator.count() > 0:
                    return
            except (PlaywrightError, RuntimeError, ValueError):
                pass
            if prompted and not recovered and url != catalogue_url.lower():
                _stderr("Authentication completed; returning to the catalogue URL.")
                page.goto(catalogue_url, wait_until="domcontentloaded")
                recovered = True
        page.wait_for_timeout(250)
    raise TimeoutError(
        f"No BCA lot cards detected before auth timeout ({timeout:g}s); "
        "partial data, if any, is saved."
    )


def _run_browser_capture(args: Namespace, source: SourceKind) -> int:
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
                if source is SourceKind.BCA:
                    context = playwright.chromium.launch_persistent_context(
                        str(args.profile_dir), channel="chrome", headless=False
                    )
                    page = context.pages[0] if context.pages else context.new_page()
                    page.goto(args.catalogue_url, wait_until="domcontentloaded")
                    _wait_for_bca_cards(page, args.catalogue_url, args.auth_timeout)
                    _stderr("BCA lot cards detected; starting capture.")
                else:
                    browser = playwright.chromium.launch(channel="chrome", headless=False)
                    context = browser.new_context()
                    page = context.new_page()
                    page.goto("https://www.autotrader.co.uk", wait_until="domcontentloaded")
                    _stderr(
                        "Auto Trader browser opened. Run one search, then press ENTER here."
                    )
                    input()

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
                    _PlaywrightPageSource(page, source),
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
    compare.add_argument("--json-input", action="store_true", help="Read vehicle JSON from stdin.")
    compare.add_argument("--make", help="Vehicle make.")
    compare.add_argument("--model", help="Model variant.")
    compare.add_argument("--year", type=int, help="Registration year.")
    compare.add_argument("--mileage", type=int, help="Mileage in miles.")
    compare.add_argument("--cap-clean-price", type=int, help="CAP Clean price in pounds.")
    compare.add_argument("--trim", help="Optional trim.")
    compare.add_argument("--fuel-type", help="Optional fuel type.")
    compare.add_argument("--transmission", help="Optional transmission.")
    compare.add_argument("--market-file", type=Path, help="JSON Auto Trader records file.")
    compare.add_argument("--autotrader-capture-id", help="Saved Auto Trader capture ID.")
    compare.add_argument("--data-root", type=Path, default=Path("data/captures"))
    compare.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    compare.set_defaults(handler=_compare_vehicle)

    def add_capture_parser(name: str, help_text: str, source: SourceKind) -> None:
        capture = subparsers.add_parser(name, help=help_text)
        capture.add_argument("--search-name", required=True, help="Capture name.")
        capture.add_argument("--result-limit", type=int, default=5, help="Maximum pages or scroll batches.")
        capture.add_argument("--move-delay", type=float, default=60.0, help="Non-zero delay between movements.")
        capture.add_argument("--data-dir", type=Path, default=Path(f"data/captures/{source.value}"))
        capture.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
        if source is SourceKind.BCA:
            capture.add_argument("--catalogue-url", default="https://www.bca.co.uk", help="BCA catalogue URL.")
            capture.add_argument("--profile-dir", type=Path, default=Path("data/browser/bca"), help="User-controlled Chrome profile for LastPass.")
            capture.add_argument("--auth-timeout", type=float, default=180.0, help="Seconds to wait for login and lot cards.")
        capture.set_defaults(handler=lambda args: _run_browser_capture(args, source))

    add_capture_parser("search-bca", "Capture BCA lots in a visible Chrome session.", SourceKind.BCA)
    add_capture_parser("search-autotrader", "Capture Auto Trader listings with headed infinite scroll.", SourceKind.AUTOTRADER)

    pair = subparsers.add_parser("match-pair", help="Match two saved captures into an OpportunityList.")
    pair.add_argument("--bca-capture-id", required=True, help="Saved BCA capture ID.")
    pair.add_argument("--autotrader-capture-id", required=True, help="Saved Auto Trader capture ID.")
    pair.add_argument("--data-root", type=Path, default=Path("data/captures"))
    pair.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    pair.set_defaults(handler=_match_pair)

    schema = subparsers.add_parser("tool-schema", help="Print OpenAI/Hermes tool-call JSON schemas.")
    schema.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    schema.set_defaults(handler=_tool_schema)
    return parser


def _tool_schema(_args: Namespace) -> int:
    schemas = [
        {
            "type": "function",
            "function": {
                "name": "compare-vehicle",
                "description": "Compare an ad-hoc vehicle with Auto Trader market evidence.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "make": {"type": "string"},
                        "model": {"type": "string"},
                        "year": {"type": "integer"},
                        "mileage": {"type": "integer", "minimum": 0},
                        "cap_clean_price": {"type": "integer", "minimum": 0},
                        "trim": {"type": "string"},
                        "fuel_type": {"type": "string"},
                        "transmission": {"type": "string"},
                    },
                    "required": ["make", "model", "year", "mileage", "cap_clean_price"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search-bca",
                "description": "Capture BCA lots through a visible user-assisted Chrome session.",
                "parameters": {"type": "object", "properties": {"search_name": {"type": "string"}, "catalogue_url": {"type": "string"}, "auth_timeout": {"type": "number", "exclusiveMinimum": 0}}, "required": ["search_name"], "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search-autotrader",
                "description": "Capture Auto Trader results through headed infinite scroll.",
                "parameters": {"type": "object", "properties": {"search_name": {"type": "string"}}, "required": ["search_name"], "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "match-pair",
                "description": "Match a saved BCA capture with a saved Auto Trader capture.",
                "parameters": {"type": "object", "properties": {"bca_capture_id": {"type": "string"}, "autotrader_capture_id": {"type": "string"}}, "required": ["bca_capture_id", "autotrader_capture_id"], "additionalProperties": False},
            },
        },
    ]
    _write_json(schemas, pretty=_args.pretty)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except ValueError as error:
        _write_json(_error_envelope(str(error), code="invalid_input"))
        return 1


if __name__ == "__main__":  # pragma: no cover - exercised through python -m
    sys.exit(main())
