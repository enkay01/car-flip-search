"""User-assisted capture kernel: observe, validate, deduplicate, and save one search.

One run of ``run_capture`` reads up to ``page_limit`` result pages from a
``PageSource`` (typically a Playwright adapter owned by the tool script), keeps
every valid car record, logs every skip with its reasons, and stops safely on a
page limit, a lack of further pages, an interrupt, or an access challenge.
``save_capture`` writes a never-overwritten capture directory: the original page
data, the valid parsed car records, and the skipped-car log.

This module is deliberately free of browser imports. The Playwright adapter
lives in ``tools/bca_headed_fetch.py``; here the page source is injected so the
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
    BcaRawRecord,
    observe_bca_cards,
    validate_bca_observation,
)


class CaptureChallengeError(Exception):
    """Raised when a page source hits an access challenge and must stop."""


class StopReason(StrEnum):
    COMPLETED = "completed"
    NO_FURTHER_PAGES = "no_further_pages"
    USER_STOPPED = "user_stopped"
    CHALLENGE_DETECTED = "challenge_detected"


@dataclass(frozen=True, kw_only=True)
class CaptureOptions:
    """Configuration for one BCA capture run."""

    search_name: str
    page_limit: int = 5
    page_delay_seconds: float = 60.0
    data_dir: Path = Path("data/captures/bca")

    def __post_init__(self) -> None:
        if not self.search_name.strip():
            raise ValueError("search name must be a non-blank string")
        if self.page_limit < 1:
            raise ValueError("page limit must be at least 1")
        if self.page_delay_seconds <= 0:
            raise ValueError("page delay must be greater than zero")
        object.__setattr__(self, "data_dir", Path(self.data_dir))


@dataclass(frozen=True)
class SkippedCar:
    """One skipped car with every reason; the lot is identified where possible."""

    lot_id: str | None
    page_number: int
    card_index: int
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class CaptureOutcome:
    """Everything a capture produced, ready to be saved."""

    search_name: str
    stop_reason: StopReason
    stop_message: str | None
    pages: tuple[str, ...]
    cars: tuple[BcaRawRecord, ...]
    skipped: tuple[SkippedCar, ...]


class PageSource(Protocol):
    """A source of successive search-result pages from the user's browser."""

    def current_html(self) -> str:
        """Return the full HTML of the current page."""

    def advance(self) -> bool:
        """Move to the next page, returning False when there is no next page."""


def run_capture(
    options: CaptureOptions,
    page_source: PageSource,
    *,
    pace: Callable[[float], None] | None = None,
    challenge_detector: Callable[[str], str | None] | None = None,
) -> CaptureOutcome:
    """Run one capture: read pages, keep valid cars, log every skip, stop safely."""
    pacer = pace or _default_pace
    detector = challenge_detector or detect_challenge_markers

    cars: dict[str, BcaRawRecord] = {}
    skipped: list[SkippedCar] = []
    pages: list[str] = []
    stop_reason = StopReason.COMPLETED
    stop_message: str | None = None

    for page_number in range(1, options.page_limit + 1):
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

        for card_index, observation in enumerate(observe_bca_cards(html_content)):
            result = validate_bca_observation(observation)
            if result.record is not None:
                cars[result.record["id"]] = result.record
            else:
                skipped.append(
                    SkippedCar(
                        lot_id=observation.lot_id,
                        page_number=page_number,
                        card_index=card_index,
                        reasons=result.reasons,
                    )
                )

        if page_number >= options.page_limit:
            break

        try:
            pacer(options.page_delay_seconds)
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
        stop_reason=stop_reason,
        stop_message=stop_message,
        pages=tuple(pages),
        cars=tuple(cars.values()),
        skipped=tuple(skipped),
    )


def _default_pace(seconds: float) -> None:
    time.sleep(seconds)


def new_capture_id() -> str:
    """Return a unique capture ID that never collides with a saved capture."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def save_capture(outcome: CaptureOutcome, options: CaptureOptions) -> Path:
    """Write a capture directory that is never overwritten; returns its path."""
    data_dir = options.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)

    capture_id = _unique_capture_id(data_dir)

    capture_dir = data_dir / capture_id
    capture_dir.mkdir()
    (capture_dir / "pages").mkdir()

    manifest = {
        "capture_id": capture_id,
        "source": "bca",
        "search_name": options.search_name,
        "page_limit": options.page_limit,
        "page_delay_seconds": options.page_delay_seconds,
        "pages_captured": len(outcome.pages),
        "cars_captured": len(outcome.cars),
        "cars_skipped": len(outcome.skipped),
        "stop_reason": outcome.stop_reason.value,
        "saved_at": datetime.now(UTC).isoformat(),
    }
    if outcome.stop_message is not None:
        manifest["stop_message"] = outcome.stop_message
    (capture_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    for index, page_html in enumerate(outcome.pages, start=1):
        page_path = capture_dir / "pages" / f"page_{index:02d}.html"
        page_path.write_text(page_html, encoding="utf-8")

    (capture_dir / "cars.json").write_text(
        json.dumps(list(outcome.cars), indent=2) + "\n", encoding="utf-8"
    )

    skipped_json = [
        {
            "lot_id": skipped_car.lot_id,
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


def print_capture_summary(outcome: CaptureOutcome, capture_dir: Path) -> None:
    """Print the human summary of a finished capture, including zero-valid runs."""
    print()
    print("=" * 70)
    print("BCA capture saved")
    print("=" * 70)
    print(f"Search name    : {outcome.search_name}")
    print(f"Capture ID     : {capture_dir.name}")
    print(f"Saved to       : {capture_dir}")
    print(f"Pages captured : {len(outcome.pages)}")
    print(f"Valid cars     : {len(outcome.cars)}")
    print(f"Skipped cars   : {len(outcome.skipped)}")
    if outcome.stop_reason is not StopReason.COMPLETED:
        print(f"Stopped        : {outcome.stop_reason.value}")
    if outcome.stop_message is not None:
        print(f"Stop reason    : {outcome.stop_message}")
    print("=" * 70)
