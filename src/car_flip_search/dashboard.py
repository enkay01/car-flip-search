"""Local Flask dashboard for reviewing saved BCA and Auto Trader Captures."""

from __future__ import annotations

import argparse
import json
import shutil
import threading
import webbrowser
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict, TypeGuard
from urllib.parse import unquote, urljoin, urlparse

from flask import Flask, redirect, render_template, request, url_for

from .capture import SourceKind
from .model import (
    AuctionLot,
    AutoTraderListing,
    CandidateVehicle,
    HighMileageReference,
    MarketComparable,
    MarketSnapshot,
    OpportunityList,
    SortCriterion,
    SortField,
)
from .opportunity_search import OpportunitySearch
from .source_acquisition import (
    AutoTraderAcquisition,
    AutoTraderRawRecord,
    BcaAcquisition,
    BcaRawRecord,
)

DEFAULT_DATA_ROOT = Path("data/captures")
_DEFAULT_SORT_FIELD = SortField.RETAIL_FLOOR_SPREAD
_SORTABLE_FIELDS = (
    SortField.RETAIL_FLOOR_SPREAD,
    SortField.PRICE_SPREAD,
    SortField.CAP_CLEAN_PRICE,
    SortField.MILEAGE,
    SortField.COMPARABLE_SUPPLY,
)
_BCA_HOSTS = {"bca.co.uk", "www.bca.co.uk"}
_AUTOTRADER_HOSTS = {"autotrader.co.uk", "www.autotrader.co.uk"}
type JsonValue = (
    str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
)
type RawCaptureRecord = BcaRawRecord | AutoTraderRawRecord
type EvidenceListing = MarketComparable | HighMileageReference


class ManifestPayload(TypedDict, total=False):
    capture_id: str
    source: str
    search_name: str
    saved_at: str
    pages_captured: int
    records_captured: int
    records_skipped: int
    stop_reason: str
    stop_message: str
    movement_limit: int
    movement_delay_seconds: float


class CaptureLoadError(ValueError):
    """Raised when a saved Capture cannot be trusted by the dashboard."""


@dataclass(frozen=True, kw_only=True)
class CaptureManifest:
    capture_id: str
    source: SourceKind
    search_name: str
    saved_at: datetime
    pages_captured: int
    records_captured: int
    records_skipped: int
    stop_reason: str
    stop_message: str | None
    movement_limit: int | None
    movement_delay_seconds: float | None

    @property
    def saved_at_local(self) -> str:
        return self.saved_at.astimezone().strftime("%d %b %Y, %H:%M %Z")

    @property
    def stop_label(self) -> str:
        return _stop_label(self.stop_reason)

    @property
    def status_label(self) -> str:
        if self.stop_reason == "completed":
            return "Completed"
        return f"Stopped: {self.stop_label}"


@dataclass(frozen=True, kw_only=True)
class SourceLink:
    source: SourceKind
    record_id: str
    url: str


@dataclass(frozen=True, kw_only=True)
class LoadedCapture:
    path: Path
    manifest: CaptureManifest
    raw_records: tuple[RawCaptureRecord, ...]
    auction_lots: tuple[AuctionLot, ...]
    listings: tuple[AutoTraderListing, ...]
    source_links: tuple[SourceLink, ...]

    @property
    def capture_id(self) -> str:
        return self.manifest.capture_id

    @property
    def source(self) -> SourceKind:
        return self.manifest.source

    @property
    def display_label(self) -> str:
        return f"{self.capture_id} · {self.manifest.search_name}"

    @property
    def valid_count(self) -> int:
        return len(self.raw_records)

    @property
    def comparison_ready_count(self) -> int:
        if self.source is SourceKind.BCA:
            return len(self.auction_lots)
        return len(self.listings)

    @property
    def data_quality_notice(self) -> str | None:
        if self.source is not SourceKind.AUTOTRADER:
            return None
        excluded_count = self.valid_count - self.comparison_ready_count
        if excluded_count <= 0:
            return None
        record_label = "record" if excluded_count == 1 else "records"
        return (
            f"Auto Trader Capture {self.capture_id} has {excluded_count} captured "
            f"{record_label} without complete vehicle identity; they are excluded "
            "from market evidence. The Capture remains usable."
        )

    @property
    def summary_label(self) -> str:
        return (
            f"{self.manifest.search_name} · {self.manifest.saved_at_local} · "
            f"{self.valid_count} captured · {self.comparison_ready_count} "
            f"comparison-ready · {self.manifest.records_skipped} skipped"
        )

    def source_url_for(self, record_id: str) -> str | None:
        for source_link in self.source_links:
            if source_link.record_id == record_id:
                return source_link.url
        return None


@dataclass(frozen=True, kw_only=True)
class CaptureProblem:
    capture_id: str
    reason: str


@dataclass(frozen=True, kw_only=True)
class CaptureSelection:
    capture: LoadedCapture | None
    notice: str | None


@dataclass(frozen=True, kw_only=True)
class SourceInventory:
    source: SourceKind
    captures: tuple[LoadedCapture, ...]
    problems: tuple[CaptureProblem, ...]
    directory_exists: bool

    @property
    def latest(self) -> LoadedCapture | None:
        return self.captures[0] if self.captures else None

    @property
    def source_label(self) -> str:
        return _source_label(self.source)

    @property
    def status_label(self) -> str:
        if self.captures:
            return f"{len(self.captures)} usable Capture(s)"
        if self.problems:
            return "No usable Captures"
        return "No saved Captures"

    def capture_by_id(self, capture_id: str) -> LoadedCapture | None:
        return next(
            (capture for capture in self.captures if capture.capture_id == capture_id),
            None,
        )


@dataclass(frozen=True, kw_only=True)
class CaptureEntry:
    """One saved Capture directory shown on the management page."""

    source: SourceKind
    capture_id: str
    search_name: str | None
    saved_at: datetime | None
    records_captured: int | None
    status_label: str
    problem: str | None

    @property
    def source_label(self) -> str:
        return _source_label(self.source)

    @property
    def selection_value(self) -> str:
        return f"{self.source.value}:{self.capture_id}"

    @property
    def search_name_label(self) -> str:
        return self.search_name or "Unavailable"

    @property
    def saved_at_label(self) -> str:
        if self.saved_at is None:
            return "Unavailable"
        return self.saved_at.astimezone().strftime("%d %b %Y, %H:%M %Z")

    @property
    def records_label(self) -> str:
        if self.records_captured is None:
            return "Unavailable"
        return f"{self.records_captured} captured"


@dataclass(frozen=True, kw_only=True)
class CaptureManagementPage:
    entries: tuple[CaptureEntry, ...]
    deleted_count: int = 0
    skipped_count: int = 0


@dataclass(frozen=True, kw_only=True)
class CaptureDeletionResult:
    deleted_count: int
    skipped_count: int


@dataclass(frozen=True, kw_only=True)
class EvidenceView:
    listing_id: str
    identity_label: str
    mileage: int
    advertised_price: int
    seller_type: str
    trim: str | None
    source_url: str | None
    is_cheapest: bool
    sets_retail_floor: bool

    @property
    def price_label(self) -> str:
        return _pounds(self.advertised_price)

    @property
    def mileage_label(self) -> str:
        return f"{self.mileage:,} miles"


@dataclass(frozen=True, kw_only=True)
class DashboardRequest:
    data_root: Path
    bca_capture_id: str | None
    autotrader_capture_id: str | None
    search_query: str
    sort_field: str
    direction: str


@dataclass(frozen=True, kw_only=True)
class CandidateView:
    detail_key: str
    candidate: CandidateVehicle
    source_url: str | None
    market_comparables: tuple[EvidenceView, ...]
    high_mileage_references: tuple[EvidenceView, ...]

    @property
    def vehicle_name(self) -> str:
        identity = self.candidate.auction_lot.identity
        return f"{identity.make} {identity.model_variant}"

    @property
    def identity_label(self) -> str:
        identity = self.candidate.auction_lot.identity
        return (
            f"{self.vehicle_name} · {identity.registration_year} · "
            f"{self.candidate.auction_lot.id.value}"
        )

    @property
    def detail_identity_label(self) -> str:
        identity = self.candidate.auction_lot.identity
        details = (
            identity.make,
            identity.model_variant,
            self.candidate.auction_lot.trim,
            str(identity.registration_year),
            identity.fuel_type,
            identity.transmission,
            identity.body_style,
            f"{identity.door_count} doors",
        )
        return " · ".join(value for value in details if value)

    @property
    def auction_lot_id(self) -> str:
        return self.candidate.auction_lot.id.value

    @property
    def mileage_label(self) -> str:
        return f"{self.candidate.auction_lot.mileage:,}"

    @property
    def cap_clean_price_label(self) -> str:
        return _pounds(self.candidate.auction_lot.cap_clean_price.pounds)

    @property
    def retail_floor_label(self) -> str:
        pounds = self.candidate.retail_floor_spread_pounds
        if pounds is None:
            return "No Retail Floor"
        return _pounds(self.candidate.retail_floor.pounds)

    @property
    def retail_floor_spread_label(self) -> str:
        return _spread_label(self.candidate.retail_floor_spread_pounds)

    @property
    def price_spread_label(self) -> str:
        return _spread_label(self.candidate.price_spread_pounds)

    @property
    def comparable_supply(self) -> int:
        return self.candidate.comparable_supply

    @property
    def source_link_label(self) -> str:
        return "Open Auction Lot" if self.source_url is not None else "No Source Link"

    @property
    def search_text(self) -> str:
        identity = self.candidate.auction_lot.identity
        values = (
            self.auction_lot_id,
            identity.make,
            identity.model_variant,
            self.candidate.auction_lot.trim or "",
            str(identity.registration_year),
            identity.fuel_type,
            identity.transmission,
            identity.body_style,
        )
        return " ".join(values).casefold()


@dataclass(frozen=True, kw_only=True)
class DashboardPage:
    bca_inventory: SourceInventory
    autotrader_inventory: SourceInventory
    bca_capture: LoadedCapture | None
    autotrader_capture: LoadedCapture | None
    notices: tuple[str, ...]
    search_name_warning: str | None
    candidates: tuple[CandidateView, ...]
    total_candidates: int
    search_query: str
    sort_field: SortField
    descending: bool

    @property
    def has_pair(self) -> bool:
        return self.bca_capture is not None and self.autotrader_capture is not None

    @property
    def bca_capture_id(self) -> str | None:
        return self.bca_capture.capture_id if self.bca_capture is not None else None

    @property
    def autotrader_capture_id(self) -> str | None:
        return (
            self.autotrader_capture.capture_id
            if self.autotrader_capture is not None
            else None
        )

    @property
    def result_count_label(self) -> str:
        if self.search_query:
            return f"Showing {len(self.candidates)} of {self.total_candidates} Candidate Vehicles"
        return f"{self.total_candidates} Candidate Vehicle(s)"

    @property
    def selected_pair_label(self) -> str:
        if self.bca_capture is None or self.autotrader_capture is None:
            return "No usable Capture Pair"
        return f"{self.bca_capture.capture_id} + {self.autotrader_capture.capture_id}"

    def direction_for(self, field: str) -> str:
        try:
            parsed_field = SortField(field)
        except ValueError:
            parsed_field = _DEFAULT_SORT_FIELD
        if parsed_field is self.sort_field:
            return "asc" if self.descending else "desc"
        return "desc"


def create_app(data_root: str | Path = DEFAULT_DATA_ROOT) -> Flask:
    """Create the local dashboard application."""
    app = Flask(__name__)
    app.config["DATA_ROOT"] = Path(data_root)

    @app.get("/")
    def dashboard() -> str:
        page = build_dashboard_page(
            DashboardRequest(
                data_root=Path(app.config["DATA_ROOT"]),
                bca_capture_id=request.args.get("bca_capture_id"),
                autotrader_capture_id=request.args.get("autotrader_capture_id"),
                search_query=request.args.get("q", ""),
                sort_field=request.args.get("sort", _DEFAULT_SORT_FIELD.value),
                direction=request.args.get("direction", "desc"),
            )
        )
        return render_template("dashboard.html", page=page)

    @app.get("/captures")
    def capture_manager() -> str:
        return render_template(
            "captures.html",
            page=build_capture_management_page(
                Path(app.config["DATA_ROOT"]),
                deleted_count=request.args.get("deleted", default=0, type=int),
                skipped_count=request.args.get("skipped", default=0, type=int),
            ),
        )

    @app.post("/captures/delete")
    def delete_capture_selections() -> str:
        result = delete_captures(
            Path(app.config["DATA_ROOT"]), request.form.getlist("capture")
        )
        return redirect(
            url_for(
                "capture_manager",
                deleted=result.deleted_count,
                skipped=result.skipped_count,
            )
        )

    return app


def build_dashboard_page(request_data: DashboardRequest) -> DashboardPage:
    """Read the Capture directories and produce one renderable dashboard state."""
    bca_inventory = discover_captures(request_data.data_root, SourceKind.BCA)
    autotrader_inventory = discover_captures(
        request_data.data_root, SourceKind.AUTOTRADER
    )

    bca_selection = _select_capture(bca_inventory, request_data.bca_capture_id, "BCA")
    autotrader_selection = _select_capture(
        autotrader_inventory,
        request_data.autotrader_capture_id,
        "Auto Trader",
    )
    selection_notices = tuple(
        notice
        for notice in (bca_selection.notice, autotrader_selection.notice)
        if notice is not None
    )

    bca_capture = bca_selection.capture
    autotrader_capture = autotrader_selection.capture
    capture_notices = tuple(
        notice
        for capture in (bca_capture, autotrader_capture)
        if capture is not None
        for notice in (capture.data_quality_notice,)
        if notice is not None
    )
    notices = selection_notices + capture_notices

    search_name_warning: str | None = None
    candidates: tuple[CandidateView, ...] = ()
    total_candidates = 0
    parsed_sort_field = _parse_sort_field(request_data.sort_field)
    descending = request_data.direction != "asc"
    clean_search_query = request_data.search_query.strip()

    if bca_capture is not None and autotrader_capture is not None:
        if bca_capture.manifest.search_name != autotrader_capture.manifest.search_name:
            search_name_warning = (
                "Search Name mismatch: "
                f"BCA is {bca_capture.manifest.search_name}; "
                f"Auto Trader is {autotrader_capture.manifest.search_name}."
            )

        opportunities = OpportunitySearch().search(
            bca_capture.auction_lots,
            MarketSnapshot(autotrader_capture.listings),
        )
        total_candidates = len(opportunities.candidates)
        if clean_search_query:
            query = clean_search_query.casefold()
            opportunities = OpportunityList(
                tuple(
                    candidate
                    for candidate in opportunities.candidates
                    if _candidate_search_text(candidate).find(query) >= 0
                )
            )
        opportunities = opportunities.sort(
            SortCriterion(field=parsed_sort_field, descending=descending)
        )
        candidates = _candidate_views(
            opportunities,
            bca_capture,
            autotrader_capture,
        )

    return DashboardPage(
        bca_inventory=bca_inventory,
        autotrader_inventory=autotrader_inventory,
        bca_capture=bca_capture,
        autotrader_capture=autotrader_capture,
        notices=notices,
        search_name_warning=search_name_warning,
        candidates=candidates,
        total_candidates=total_candidates,
        search_query=clean_search_query,
        sort_field=parsed_sort_field,
        descending=descending,
    )


def build_capture_management_page(
    data_root: Path, *, deleted_count: int = 0, skipped_count: int = 0
) -> CaptureManagementPage:
    """List every saved Capture directory, including unreadable Captures."""
    entries: list[CaptureEntry] = []
    for source in (SourceKind.BCA, SourceKind.AUTOTRADER):
        source_directory = data_root / source.value
        if not source_directory.is_dir():
            continue
        try:
            capture_paths = sorted(
                path
                for path in source_directory.iterdir()
                if path.is_dir() and not path.is_symlink()
            )
        except OSError:
            continue
        entries.extend(_capture_entry(path, source) for path in capture_paths)

    entries.sort(
        key=lambda entry: (
            entry.saved_at is not None,
            entry.saved_at or datetime.min.replace(tzinfo=UTC),
            entry.source.value,
            entry.capture_id,
        ),
        reverse=True,
    )
    return CaptureManagementPage(
        entries=tuple(entries),
        deleted_count=max(deleted_count, 0),
        skipped_count=max(skipped_count, 0),
    )


def delete_captures(
    data_root: Path, selections: Sequence[str]
) -> CaptureDeletionResult:
    """Delete only selected Capture directories inside the configured data root."""
    deleted_count = 0
    skipped_count = 0
    seen: set[str] = set()
    for selection in selections:
        if selection in seen:
            continue
        seen.add(selection)
        parsed_selection = _parse_capture_selection(selection)
        if parsed_selection is None:
            skipped_count += 1
            continue
        source, capture_id = parsed_selection
        capture_path = _safe_capture_path(data_root, source, capture_id)
        if (
            capture_path is None
            or not capture_path.is_dir()
            or capture_path.is_symlink()
        ):
            skipped_count += 1
            continue
        try:
            shutil.rmtree(capture_path)
        except OSError:
            skipped_count += 1
        else:
            deleted_count += 1
    return CaptureDeletionResult(
        deleted_count=deleted_count,
        skipped_count=skipped_count,
    )


def _capture_entry(capture_path: Path, source: SourceKind) -> CaptureEntry:
    try:
        manifest_data = _read_json_object(capture_path / "manifest.json", "manifest")
        manifest = _parse_manifest(manifest_data, capture_path.name, source)
    except CaptureLoadError as error:
        return CaptureEntry(
            source=source,
            capture_id=capture_path.name,
            search_name=None,
            saved_at=None,
            records_captured=None,
            status_label="Unavailable",
            problem=str(error),
        )
    return CaptureEntry(
        source=source,
        capture_id=capture_path.name,
        search_name=manifest.search_name,
        saved_at=manifest.saved_at,
        records_captured=manifest.records_captured,
        status_label=manifest.status_label,
        problem=None,
    )


def _parse_capture_selection(value: str) -> tuple[SourceKind, str] | None:
    source_value, separator, capture_id = value.partition(":")
    if not separator or not capture_id or "/" in capture_id or "\\" in capture_id:
        return None
    try:
        source = SourceKind(source_value)
    except ValueError:
        return None
    if capture_id in {".", ".."} or capture_id.strip() != capture_id:
        return None
    return source, capture_id


def _safe_capture_path(
    data_root: Path, source: SourceKind, capture_id: str
) -> Path | None:
    source_directory = data_root / source.value
    capture_path = source_directory / capture_id
    try:
        if source_directory.is_symlink():
            return None
        if capture_path.resolve(strict=False).parent != source_directory.resolve(
            strict=False
        ):
            return None
    except OSError:
        return None
    return capture_path


def discover_captures(data_root: Path, source: SourceKind) -> SourceInventory:
    """Load structurally valid Captures for one source, newest first."""
    source_directory = data_root / source.value
    if not source_directory.is_dir():
        return SourceInventory(
            source=source,
            captures=(),
            problems=(),
            directory_exists=False,
        )

    captures: list[LoadedCapture] = []
    problems: list[CaptureProblem] = []
    try:
        capture_paths = sorted(
            path for path in source_directory.iterdir() if path.is_dir()
        )
    except OSError as error:
        problems.append(
            CaptureProblem(
                capture_id=source_directory.name,
                reason=f"Capture directory is unreadable: {error}",
            )
        )
        return SourceInventory(
            source=source,
            captures=(),
            problems=tuple(problems),
            directory_exists=True,
        )

    for capture_path in capture_paths:
        try:
            captures.append(_load_capture(capture_path, source))
        except CaptureLoadError as error:
            problems.append(
                CaptureProblem(capture_id=capture_path.name, reason=str(error))
            )

    captures.sort(
        key=lambda capture: (capture.manifest.saved_at, capture.capture_id),
        reverse=True,
    )
    return SourceInventory(
        source=source,
        captures=tuple(captures),
        problems=tuple(problems),
        directory_exists=True,
    )


def _load_capture(capture_path: Path, expected_source: SourceKind) -> LoadedCapture:
    manifest_data = _read_json_object(capture_path / "manifest.json", "manifest")
    manifest = _parse_manifest(manifest_data, capture_path.name, expected_source)
    raw_records = _read_records(capture_path / "records.json")
    if len(raw_records) != manifest.records_captured:
        raise CaptureLoadError(
            "records.json count does not match manifest records_captured"
        )

    if expected_source is SourceKind.BCA:
        auction_lots = BcaAcquisition().acquire(raw_records)
        if len(auction_lots) != len(raw_records):
            raise CaptureLoadError("records.json contains an invalid BCA record")
        listings: tuple[AutoTraderListing, ...] = ()
    else:
        listings = AutoTraderAcquisition().acquire(raw_records)
        auction_lots = ()

    return LoadedCapture(
        path=capture_path,
        manifest=manifest,
        raw_records=raw_records,
        auction_lots=auction_lots,
        listings=listings,
        source_links=_build_source_links(expected_source, raw_records),
    )


def _read_json_value(path: Path, label: str) -> JsonValue:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CaptureLoadError(f"{label}.json is unreadable: {error}") from error


def _read_json_object(path: Path, label: str) -> ManifestPayload:
    value = _read_json_value(path, label)
    if not _is_manifest_payload(value):
        raise CaptureLoadError(f"{label}.json must contain a JSON object")
    return value


def _read_records(path: Path) -> tuple[RawCaptureRecord, ...]:
    value = _read_json_value(path, "records")
    if not _is_capture_record_list(value):
        raise CaptureLoadError("records.json must contain a list of record objects")
    return tuple(value)


def _is_manifest_payload(value: JsonValue) -> TypeGuard[ManifestPayload]:
    return isinstance(value, dict)


def _is_capture_record(value: JsonValue) -> TypeGuard[RawCaptureRecord]:
    return isinstance(value, dict)


def _is_capture_record_list(
    value: JsonValue,
) -> TypeGuard[list[RawCaptureRecord]]:
    return isinstance(value, list) and all(_is_capture_record(item) for item in value)


def _is_text(value: JsonValue | None) -> TypeGuard[str]:
    return isinstance(value, str)


def _is_nonnegative_int(value: JsonValue | None) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_positive_number(value: JsonValue | None) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _parse_manifest(
    manifest: ManifestPayload, capture_id: str, expected_source: SourceKind
) -> CaptureManifest:
    manifest_capture_id = _manifest_text(manifest, "capture_id")
    if manifest_capture_id != capture_id:
        raise CaptureLoadError("manifest capture_id does not match directory name")
    manifest_source = _manifest_text(manifest, "source")
    if manifest_source != expected_source.value:
        raise CaptureLoadError(f"manifest source is not {expected_source.value}")
    search_name = _manifest_text(manifest, "search_name")
    saved_at = _parse_saved_at(_manifest_text(manifest, "saved_at"))
    pages_captured = _manifest_nonnegative_int(manifest, "pages_captured")
    records_captured = _manifest_nonnegative_int(manifest, "records_captured")
    records_skipped = _manifest_nonnegative_int(manifest, "records_skipped")
    stop_reason = _manifest_text(manifest, "stop_reason")
    stop_message = _optional_manifest_text(manifest, "stop_message")
    movement_limit = _optional_manifest_nonnegative_int(manifest, "movement_limit")
    movement_delay_seconds = _optional_manifest_float(
        manifest, "movement_delay_seconds"
    )
    return CaptureManifest(
        capture_id=capture_id,
        source=expected_source,
        search_name=search_name,
        saved_at=saved_at,
        pages_captured=pages_captured,
        records_captured=records_captured,
        records_skipped=records_skipped,
        stop_reason=stop_reason,
        stop_message=stop_message,
        movement_limit=movement_limit,
        movement_delay_seconds=movement_delay_seconds,
    )


def _manifest_text(manifest: ManifestPayload, field: str) -> str:
    value = manifest.get(field)
    if not _is_text(value) or not value.strip():
        raise CaptureLoadError(f"manifest {field} is missing or invalid")
    return value.strip()


def _optional_manifest_text(manifest: ManifestPayload, field: str) -> str | None:
    value = manifest.get(field)
    if value is None:
        return None
    if not _is_text(value):
        raise CaptureLoadError(f"manifest {field} is invalid")
    return value.strip() or None


def _manifest_nonnegative_int(manifest: ManifestPayload, field: str) -> int:
    value = manifest.get(field)
    if not _is_nonnegative_int(value):
        raise CaptureLoadError(f"manifest {field} is missing or invalid")
    return value


def _optional_manifest_nonnegative_int(
    manifest: ManifestPayload, field: str
) -> int | None:
    value = manifest.get(field)
    if value is None:
        return None
    if not _is_nonnegative_int(value):
        raise CaptureLoadError(f"manifest {field} is invalid")
    return value


def _optional_manifest_float(manifest: ManifestPayload, field: str) -> float | None:
    value = manifest.get(field)
    if value is None:
        return None
    if not _is_positive_number(value):
        raise CaptureLoadError(f"manifest {field} is invalid")
    return float(value)


def _parse_saved_at(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise CaptureLoadError("manifest saved_at is not a valid timestamp") from error
    if parsed.tzinfo is None:
        raise CaptureLoadError("manifest saved_at must include a timezone")
    return parsed.astimezone(UTC)


def _build_source_links(
    source: SourceKind, raw_records: tuple[RawCaptureRecord, ...]
) -> tuple[SourceLink, ...]:
    links: dict[str, str] = {}
    for record in raw_records:
        record_id = record.get("id")
        raw_url = record.get("source_url")
        valid_url = validate_source_link(source, record_id, raw_url)
        if valid_url is not None:
            links[record_id] = valid_url
    return tuple(
        SourceLink(source=source, record_id=record_id, url=url)
        for record_id, url in links.items()
    )


def validate_source_link(
    source: SourceKind, record_id: str | None, raw_url: str | None
) -> str | None:
    """Return a safe captured source URL, or None without reconstructing it."""
    if record_id is None or raw_url is None or not raw_url.strip():
        return None
    base_url = (
        "https://www.bca.co.uk/"
        if source is SourceKind.BCA
        else "https://www.autotrader.co.uk/"
    )
    candidate = urljoin(base_url, raw_url.strip())
    try:
        parsed = urlparse(candidate)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme != "https" or hostname is None or port is not None:
        return None
    allowed_hosts = _BCA_HOSTS if source is SourceKind.BCA else _AUTOTRADER_HOSTS
    if hostname.casefold() not in allowed_hosts:
        return None

    path_parts = [part for part in unquote(parsed.path).split("/") if part]
    if len(path_parts) != 2:
        return None
    expected_prefix = "lot" if source is SourceKind.BCA else "car-details"
    if path_parts[0].casefold() != expected_prefix:
        return None
    if path_parts[1] != record_id:
        return None
    return candidate


def _select_capture(
    inventory: SourceInventory, requested_id: str | None, source_label: str
) -> CaptureSelection:
    clean_requested_id = requested_id.strip() if requested_id else None
    if clean_requested_id is None:
        return CaptureSelection(capture=inventory.latest, notice=None)
    selected = inventory.capture_by_id(clean_requested_id)
    if selected is not None:
        return CaptureSelection(capture=selected, notice=None)
    if inventory.latest is None:
        return CaptureSelection(
            capture=None,
            notice=(
                f"{source_label} Capture {clean_requested_id} is unavailable, "
                "and no usable replacement exists."
            ),
        )
    return CaptureSelection(
        capture=inventory.latest,
        notice=(
            f"{source_label} Capture {clean_requested_id} is unavailable; using "
            f"newest valid Capture {inventory.latest.capture_id}."
        ),
    )


def _parse_sort_field(value: str) -> SortField:
    try:
        parsed = SortField(value)
    except ValueError:
        return _DEFAULT_SORT_FIELD
    return parsed if parsed in _SORTABLE_FIELDS else _DEFAULT_SORT_FIELD


def _candidate_views(
    opportunities: OpportunityList,
    bca_capture: LoadedCapture,
    autotrader_capture: LoadedCapture,
) -> tuple[CandidateView, ...]:
    views: list[CandidateView] = []
    for index, candidate in enumerate(opportunities.candidates):
        comparables = candidate.comparable_evidence.market_comparables
        references = candidate.retail_floor_evidence.high_mileage_references
        cheapest_comparable_id = _cheapest_listing_id(comparables)
        floor_setting_id = _cheapest_listing_id(references)
        views.append(
            CandidateView(
                detail_key=f"candidate-{index}",
                candidate=candidate,
                source_url=bca_capture.source_url_for(candidate.auction_lot.id.value),
                market_comparables=tuple(
                    _evidence_view(
                        item,
                        autotrader_capture,
                        cheapest_comparable_id,
                        floor_setting_id,
                    )
                    for item in comparables
                ),
                high_mileage_references=tuple(
                    _evidence_view(
                        item,
                        autotrader_capture,
                        floor_setting_id,
                        floor_setting_id,
                    )
                    for item in references
                ),
            )
        )
    return tuple(views)


def _evidence_view(
    listing: EvidenceListing,
    autotrader_capture: LoadedCapture,
    cheapest_id: str | None,
    floor_setting_id: str | None,
) -> EvidenceView:
    listing_id = listing.listing_id.value
    return EvidenceView(
        listing_id=listing_id,
        identity_label=(
            f"{listing.identity.make} {listing.identity.model_variant}"
            + (f" · {listing.trim}" if listing.trim else "")
        ),
        mileage=listing.mileage,
        advertised_price=listing.advertised_price.pounds,
        seller_type=listing.seller_type.value,
        trim=listing.trim,
        source_url=autotrader_capture.source_url_for(listing_id),
        is_cheapest=listing_id == cheapest_id,
        sets_retail_floor=listing_id == floor_setting_id,
    )


def _cheapest_listing_id(listings: tuple[EvidenceListing, ...]) -> str | None:
    if not listings:
        return None
    cheapest = min(listings, key=lambda listing: listing.advertised_price.pounds)
    return cheapest.listing_id.value


def _candidate_search_text(candidate: CandidateVehicle) -> str:
    identity = candidate.auction_lot.identity
    values = (
        candidate.auction_lot.id.value,
        identity.make,
        identity.model_variant,
        candidate.auction_lot.trim or "",
        str(identity.registration_year),
        identity.fuel_type,
        identity.transmission,
        identity.body_style,
    )
    return " ".join(values).casefold()


def _source_label(source: SourceKind) -> str:
    return "Auto Trader" if source is SourceKind.AUTOTRADER else "BCA"


def _stop_label(stop_reason: str) -> str:
    return stop_reason.replace("_", " ").capitalize()


def _pounds(value: int) -> str:
    return f"£{value:,}"


def _spread_label(value: int | None) -> str:
    return "No Price Spread" if value is None else _signed_pounds(value)


def _signed_pounds(value: int) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}£{value:,}"


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local opportunity dashboard")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--debug", action="store_true")
    return parser


def main() -> None:
    """Run the dashboard in the foreground on localhost."""
    args = _argument_parser().parse_args()
    app = create_app(args.data_root)
    if not args.no_browser:
        browser_url = f"http://127.0.0.1:{args.port}/"
        browser_timer = threading.Timer(0.35, webbrowser.open_new_tab, [browser_url])
        browser_timer.daemon = True
        browser_timer.start()
    app.run(
        host="127.0.0.1",
        port=args.port,
        debug=args.debug,
        use_reloader=False,
    )


if __name__ == "__main__":
    main()
