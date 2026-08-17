"""User-assisted Auto Trader search capture command.

Opens a visible Playwright browser with a fresh session, lets the user run one
search (Auto Trader does not require login for this workflow), waits for Enter,
then captures up to ``result-limit`` scroll batches at ``move-delay`` intervals.
The capture is saved under ``data/captures/autotrader/<capture_id>`` and never
overwritten.

The tool never requires or stores Auto Trader credentials, and it never
attempts to bypass a CAPTCHA or access challenge: a challenge stops further
movement and everything captured so far is still saved. Because Auto Trader
uses infinite scroll, movement stops early once two consecutive scroll batches
produce no new listing IDs.
"""

from __future__ import annotations

import sys
import time
from argparse import ArgumentParser
from collections.abc import Sequence
from pathlib import Path

from car_flip_search import (
    CaptureChallengeError,
    CaptureHooks,
    CaptureOptions,
    SourceKind,
    autotrader_capture_strategy,
    print_capture_summary,
    run_capture,
    save_capture,
)

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import Page, sync_playwright
except ImportError:  # pragma: no cover - exercised only when playwright is missing
    PlaywrightError = None  # type: ignore[assignment,misc]
    Page = None  # type: ignore[assignment,misc]
    sync_playwright = None  # type: ignore[assignment,misc]


def _countdown_pacing(seconds: float) -> None:
    """Show a real-time countdown during the cadence delay."""
    remaining = int(seconds)
    print(
        f"Pacing cadence: {remaining}s remaining before next scroll...",
        end="",
        flush=True,
    )
    while remaining > 0:
        time.sleep(1)
        remaining -= 1
        if remaining % 10 == 0 or remaining <= 5:
            print(f" {remaining}s...", end="", flush=True)
    print(" Ready!")


class _PlaywrightPageSource:
    """PageSource adapter over a Playwright page using Auto Trader's infinite scroll."""

    def __init__(self, page: Page) -> None:
        self._page = page

    def current_html(self) -> str:
        self._raise_if_access_redirect()
        try:
            self._page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
            self._page.wait_for_timeout(500)
            self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            self._page.wait_for_timeout(1000)
            return self._page.content()
        except (PlaywrightError, TimeoutError, RuntimeError, ValueError) as error:
            raise CaptureChallengeError(
                f"Could not read the current page: {error}"
            ) from error

    def advance(self) -> bool:
        """Scroll one batch; the capture kernel stops when new IDs run out."""
        self._raise_if_access_redirect()
        try:
            for _ in range(3):
                self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                self._page.wait_for_timeout(1200)
            self._raise_if_access_redirect()
            return True
        except (PlaywrightError, TimeoutError, RuntimeError, ValueError) as error:
            raise CaptureChallengeError(
                f"Could not scroll the results: {error}"
            ) from error

    def _raise_if_access_redirect(self) -> None:
        url = self._page.url.lower()
        if any(token in url for token in ("/login", "/signin", "/sign-in", "/logon")):
            raise CaptureChallengeError(
                "Auto Trader redirected to a login or access page — the search "
                "session was challenged. Halting without bypass; pages captured "
                "so far are saved."
            )


def run_capture_command(options: CaptureOptions) -> int:
    """Open the browser, run one capture, save it, and print the summary."""
    if sync_playwright is None:
        print("Playwright is required for the Auto Trader capture command.")
        print("Install with: uv pip install playwright && playwright install chromium")
        return 2

    print("=" * 70)
    print("Auto Trader capture command")
    print(f"Search name : {options.search_name}")
    print(f"Result limit: {options.movement_limit}")
    print(f"Move delay  : {options.movement_delay_seconds}s")
    print(f"Capture dir : {options.data_dir}")
    print("=" * 70)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        try:
            # Fresh context: no stored credentials, cookies, or login sessions.
            context = browser.new_context()
            page = context.new_page()
            page.goto("https://www.autotrader.co.uk", wait_until="domcontentloaded")

            print("\n[Step 1] A visible browser opened at www.autotrader.co.uk.")
            print("No login is needed. Run your search in that browser.")
            print(
                "When your search results are displayed, return here and press ENTER.\n"
            )
            try:
                input(
                    "[Press ENTER when your Auto Trader search results are on "
                    "screen] > "
                )
            except (EOFError, KeyboardInterrupt):
                print("\nCapture aborted — nothing was saved.")
                return 1

            page_source = _PlaywrightPageSource(page)
            outcome = run_capture(
                options,
                page_source,
                autotrader_capture_strategy,
                hooks=CaptureHooks(pace=_countdown_pacing),
            )
        finally:
            browser.close()

    capture_dir = save_capture(outcome, options)
    print_capture_summary(outcome, capture_dir)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = ArgumentParser(description="Auto Trader search capture command")
    parser.add_argument(
        "--search-name",
        required=True,
        help="Name for this capture, saved in the manifest",
    )
    parser.add_argument(
        "--result-limit",
        type=int,
        default=5,
        help="Maximum number of result pages or scroll batches (default: 5)",
    )
    parser.add_argument(
        "--move-delay",
        type=float,
        default=60.0,
        help=(
            "Delay in seconds between movements; must be greater than zero "
            "(default: 60.0)"
        ),
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data/captures/autotrader"),
        help="Directory where captures are saved (default: data/captures/autotrader)",
    )
    args = parser.parse_args(argv)
    try:
        options = CaptureOptions(
            search_name=args.search_name,
            source=SourceKind.AUTOTRADER,
            movement_limit=args.result_limit,
            movement_delay_seconds=args.move_delay,
            data_dir=args.data_dir,
        )
    except ValueError as error:
        parser.error(str(error))
    return run_capture_command(options)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
