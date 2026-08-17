"""User-assisted capture kernel: observe, validate, deduplicate, and save one search.

One run of ``run_capture`` reads up to ``movement_limit`` result pages or scroll
batches from a ``PageSource`` (typically a Playwright adapter owned by the tool
script), keeps every valid record, logs every skip with its reasons, and stops
safely on a movement limit, a lack of further pages, repeated movements with
no new listing IDs, an interrupt, or an access challenge. ``save_capture`` writes a
never-overwritten capture directory: the original page data, the valid parsed
records, and the skipped-record log.

The kernel is source-agnostic: each source (BCA lots, Auto Trader listings)
supplies a ``CaptureStrategy`` that observes, validates, and keys its records.
This module is deliberately free of browser imports. The Playwright adapters
live in ``tools/*_headed_fetch.py``; here the page source is injected so the
whole loop is testable in memory.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from .source_access import detect_challenge_markers
from .source_acquisition import (
    AutoTraderCardObservation,
    AutoTraderRawRecord,
    BcaCardObservation,
    BcaRawRecord,
    observe_autotrader_cards,
    observe_bca_cards,
    validate_autotrader_observation,
    validate_bca_observation,
)


class CaptureChallengeError(Exception):
    """Raised when a page source hits an access challenge and must stop."""


class SourceKind(StrEnum):
    BCA = "bca"
    AUTOTRADER = "autotrader"


class StopReason(StrEnum):
    COMPLETED = "completed"
    NO_FURTHER_PAGES = "no_further_pages"
    NO_NEW_RESULTS = "no_new_results"
    USER_STOPPED = "user_stopped"
    CHALLENGE_DETECTED = "challenge_detected"


@dataclass(frozen=True, kw_only=True)
class CaptureOptions:
    """Configuration for one capture run."""

    search_name: str
    source: SourceKind = SourceKind.BCA
    movement_limit: int = 5
    movement_delay_seconds: float = 60.0
    no_new_results_limit: int | None = None
    data_dir: Path | None = None

    def __post_init__(self) -> None:
        if not self.search_name.strip():
            raise ValueError("search name must be a non-blank string")
        if self.movement_limit < 1:
            raise ValueError("movement limit must be at least 1")
        if self.movement_delay_seconds <= 0:
            raise ValueError("movement delay must be greater than zero")
        if self.no_new_results_limit is not None and self.no_new_results_limit < 1:
            raise ValueError("no-new-results limit must be at least 1")
        resolved_data_dir = self.data_dir or Path(f"data/captures/{self.source.value}")
        object.__setattr__(self, "data_dir", Path(resolved_data_dir))


@dataclass(frozen=True)
class SkippedCar:
    """One skipped car with every reason; the record is identified where possible."""

    record_id: str | None
    page_number: int
    card_index: int
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class CaptureOutcome[T_Record]:
    """Everything a capture produced, ready to be saved."""

    search_name: str
    source: SourceKind
    stop_reason: StopReason
    stop_message: str | None
    pages: tuple[str, ...]
    records: tuple[T_Record, ...]
    skipped: tuple[SkippedCar, ...]


class PageSource(Protocol):
    """A source of successive search-result pages from the user's browser."""

    def current_html(self) -> str:
        """Return the full HTML of the current page."""

    def advance(self) -> bool:
        """Move to the next page, returning False when there is no next page."""


def _default_pace(seconds: float) -> None:
    time.sleep(seconds)


@dataclass(frozen=True, kw_only=True)
class CaptureHooks:
    """Injected test seams for pacing and challenge detection."""

    pace: Callable[[float], None] = _default_pace
    challenge_detector: Callable[[str], str | None] = detect_challenge_markers


@dataclass(frozen=True)
class CaptureValidationResult[T_Record]:
    """Outcome of validating one observed card: its record and every skip reason."""

    record: T_Record | None
    reasons: tuple[str, ...]


class CaptureStrategy[T_Observation, T_Record](Protocol):
    """Source-specific observe/validate behaviour injected into the kernel.

    Implementations are thin: they know how to read one source's search cards
    into observations, validate an observation into a raw record plus every
    skip reason, and return the source ID used for deduplication.
    """

    source_name: str
    no_new_results_limit: int | None
    remove_previous_on_invalid: bool

    def observe(self, html_content: str) -> tuple[T_Observation, ...]:
        """Return one observation per card found on the page."""

    def validate(self, observation: T_Observation) -> CaptureValidationResult[T_Record]:
        """Validate one observation into a record plus every skip reason."""

    def observation_id(self, observation: T_Observation) -> str | None:
        """Return the source ID for a skipped entry, when the observation shows one."""

    def record_id(self, record: T_Record) -> str:
        """Return the source ID used to deduplicate records."""


@dataclass(frozen=True)
class _BcaCaptureStrategy:
    """Capture strategy for BCA search result cards."""

    source_name: str = "bca"
    no_new_results_limit: int | None = None
    remove_previous_on_invalid: bool = True

    def observe(self, html_content: str) -> tuple[BcaCardObservation, ...]:
        return observe_bca_cards(html_content)

    def validate(
        self, observation: BcaCardObservation
    ) -> CaptureValidationResult[BcaRawRecord]:
        result = validate_bca_observation(observation)
        return CaptureValidationResult(record=result.record, reasons=result.reasons)

    def observation_id(self, observation: BcaCardObservation) -> str | None:
        return observation.lot_id

    def record_id(self, record: BcaRawRecord) -> str:
        return record["id"]


bca_capture_strategy: CaptureStrategy[BcaCardObservation, BcaRawRecord] = (
    _BcaCaptureStrategy()
)


@dataclass(frozen=True)
class _AutoTraderCaptureStrategy:
    """Capture strategy for Auto Trader search result cards (infinite scroll)."""

    source_name: str = "autotrader"
    no_new_results_limit: int | None = 2
    remove_previous_on_invalid: bool = False

    def observe(self, html_content: str) -> tuple[AutoTraderCardObservation, ...]:
        return observe_autotrader_cards(html_content)

    def validate(
        self, observation: AutoTraderCardObservation
    ) -> CaptureValidationResult[AutoTraderRawRecord]:
        result = validate_autotrader_observation(observation)
        return CaptureValidationResult(record=result.record, reasons=result.reasons)

    def observation_id(self, observation: AutoTraderCardObservation) -> str | None:
        return observation.listing_id

    def record_id(self, record: AutoTraderRawRecord) -> str:
        return record["id"]


autotrader_capture_strategy: CaptureStrategy[
    AutoTraderCardObservation, AutoTraderRawRecord
] = _AutoTraderCaptureStrategy()


def run_capture[T_Observation, T_Record](
    options: CaptureOptions,
    page_source: PageSource,
    strategy: CaptureStrategy[T_Observation, T_Record],
    *,
    hooks: CaptureHooks | None = None,
) -> CaptureOutcome[T_Record]:
    """Run one capture: read pages, keep valid records, log every skip, stop safely."""
    pacer = hooks.pace if hooks is not None else _default_pace
    detector = (
        hooks.challenge_detector if hooks is not None else detect_challenge_markers
    )
    no_new_results_limit = (
        options.no_new_results_limit
        if options.no_new_results_limit is not None
        else strategy.no_new_results_limit
    )

    records: dict[str, T_Record] = {}
    observed_listing_ids: set[str] = set()
    skipped: list[SkippedCar] = []
    pages: list[str] = []
    stop_reason = StopReason.COMPLETED
    stop_message: str | None = None
    consecutive_no_new = 0

    for page_number in range(1, options.movement_limit + 1):
        try:
            html_content = page_source.current_html()
        except CaptureChallengeError as error:
            stop_reason = StopReason.CHALLENGE_DETECTED
            stop_message = str(error)
            break
        except KeyboardInterrupt:
            stop_reason = StopReason.USER_STOPPED
            stop_message = "Capture interrupted by the user."
            break

        pages.append(html_content)

        challenge = detector(html_content)
        if challenge is not None:
            stop_reason = StopReason.CHALLENGE_DETECTED
            stop_message = challenge
            break

        observed_ids_before = len(observed_listing_ids)
        for card_index, observation in enumerate(strategy.observe(html_content)):
            result = strategy.validate(observation)
            if result.record is not None:
                record_id = strategy.record_id(result.record)
                records[record_id] = result.record
                observed_listing_ids.add(record_id)
            else:
                observation_id = strategy.observation_id(observation)
                if strategy.remove_previous_on_invalid and observation_id is not None:
                    records.pop(observation_id.strip(), None)
                skipped.append(
                    SkippedCar(
                        record_id=observation_id,
                        page_number=page_number,
                        card_index=card_index,
                        reasons=result.reasons,
                    )
                )
                if observation_id is not None:
                    observed_listing_ids.add(observation_id)

        # A movement precedes every page after the first; stop early when a
        # configurable run of consecutive movements yields no new listing IDs.
        # An ID counts as new as soon as it is observed on any page, whether or
        # not the listing passes validation, so skipped cars never mask real
        # movement through the results.
        if no_new_results_limit is not None and page_number >= 2:
            if len(observed_listing_ids) - observed_ids_before == 0:
                consecutive_no_new += 1
                if consecutive_no_new >= no_new_results_limit:
                    stop_reason = StopReason.NO_NEW_RESULTS
                    stop_message = (
                        f"{no_new_results_limit} consecutive movements produced "
                        "no new listing IDs."
                    )
                    break
            else:
                consecutive_no_new = 0

        if page_number >= options.movement_limit:
            break

        try:
            pacer(options.movement_delay_seconds)
        except KeyboardInterrupt:
            stop_reason = StopReason.USER_STOPPED
            stop_message = "Capture interrupted by the user during pacing."
            break

        try:
            advanced = page_source.advance()
        except CaptureChallengeError as error:
            stop_reason = StopReason.CHALLENGE_DETECTED
            stop_message = str(error)
            break
        except KeyboardInterrupt:
            stop_reason = StopReason.USER_STOPPED
            stop_message = "Capture interrupted by the user."
            break

        if not advanced:
            stop_reason = StopReason.NO_FURTHER_PAGES
            stop_message = "No further result pages were available."
            break

    return CaptureOutcome(
        search_name=options.search_name,
        source=options.source,
        stop_reason=stop_reason,
        stop_message=stop_message,
        pages=tuple(pages),
        records=tuple(records.values()),
        skipped=tuple(skipped),
    )


def new_capture_id() -> str:
    """Return a unique capture ID that never collides with a saved capture."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def save_capture[T_Record](
    outcome: CaptureOutcome[T_Record], options: CaptureOptions
) -> Path:
    """Write a capture directory that is never overwritten; returns its path."""
    data_dir = options.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)

    capture_id = _unique_capture_id(data_dir)

    capture_dir = data_dir / capture_id
    capture_dir.mkdir()
    (capture_dir / "pages").mkdir()

    manifest = {
        "capture_id": capture_id,
        "source": outcome.source.value,
        "search_name": outcome.search_name,
        "movement_limit": options.movement_limit,
        "movement_delay_seconds": options.movement_delay_seconds,
        "pages_captured": len(outcome.pages),
        "records_captured": len(outcome.records),
        "records_skipped": len(outcome.skipped),
        "stop_reason": outcome.stop_reason.value,
        "saved_at": datetime.now(UTC).isoformat(),
    }
    if options.no_new_results_limit is not None:
        manifest["no_new_results_limit"] = options.no_new_results_limit
    if outcome.stop_message is not None:
        manifest["stop_message"] = outcome.stop_message
    (capture_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    for index, page_html in enumerate(outcome.pages, start=1):
        page_path = capture_dir / "pages" / f"page_{index:02d}.html"
        page_path.write_text(page_html, encoding="utf-8")

    (capture_dir / "records.json").write_text(
        json.dumps(list(outcome.records), indent=2) + "\n", encoding="utf-8"
    )

    skipped_json = [
        {
            "record_id": skipped_car.record_id,
            "page_number": skipped_car.page_number,
            "card_index": skipped_car.card_index,
            "reasons": list(skipped_car.reasons),
        }
        for skipped_car in outcome.skipped
    ]
    (capture_dir / "skipped.json").write_text(
        json.dumps(skipped_json, indent=2) + "\n", encoding="utf-8"
    )

    return capture_dir


def _unique_capture_id(data_dir: Path) -> str:
    while True:
        candidate = new_capture_id()
        if not (data_dir / candidate).exists():
            return candidate


def print_capture_summary[T_Record](
    outcome: CaptureOutcome[T_Record], capture_dir: Path
) -> None:
    """Print the human summary of a finished capture, including zero-valid runs."""
    source_label = (
        "Auto Trader capture"
        if outcome.source is SourceKind.AUTOTRADER
        else "BCA capture"
    )
    print()
    print("=" * 70)
    print(f"{source_label} saved")
    print("=" * 70)
    print(f"Search name    : {outcome.search_name}")
    print(f"Capture ID     : {capture_dir.name}")
    print(f"Saved to       : {capture_dir}")
    print(f"Pages captured : {len(outcome.pages)}")
    print(f"Valid records  : {len(outcome.records)}")
    print(f"Skipped records: {len(outcome.skipped)}")
    if outcome.stop_reason is not StopReason.COMPLETED:
        print(f"Stopped        : {outcome.stop_reason.value}")
    if outcome.stop_message is not None:
        print(f"Stop reason    : {outcome.stop_message}")
    print("=" * 70)
