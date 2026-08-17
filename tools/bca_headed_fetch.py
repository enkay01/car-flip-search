"""User-assisted BCA search capture command.

Opens a visible Playwright browser with a fresh session, lets the user log in
and run one search, waits for Enter, then captures up to ``result-limit``
pages at ``move-delay`` intervals. The capture is saved under
``data/captures/bca/<capture_id>`` and never overwritten.

The tool never receives, stores, or persists BCA credentials or sessions, and
it never attempts to bypass a CAPTCHA or access challenge: a challenge stops
further navigation and everything captured so far is still saved.
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
    bca_capture_strategy,
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
        f"Pacing cadence: {remaining}s remaining before next page...",
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
    """PageSource adapter over a Playwright page (the browser seam)."""

    def __init__(self, page: Page) -> None:
        self._page = page
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
            raise CaptureChallengeError(
                f"Could not read the current page: {error}"
            ) from error

    def advance(self) -> bool:
        self._raise_if_login_redirect()
        next_number = self._next_page_number
        self._next_page_number += 1
        try:
            self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            self._page.wait_for_timeout(1000)

            next_selectors = (
                "button[aria-label='Go to next page']",
                f"button[aria-label='Go to page {next_number}']",
                "button:has-text('next')",
                "a:has-text('next')",
                "a[rel='next']",
            )
            for selector in next_selectors:
                button = self._page.locator(selector)
                if button.count() > 0 and button.first.is_visible():
                    print(f"Clicking next page using '{selector}'...")
                    button.first.click(timeout=5000)
                    self._page.wait_for_timeout(3000)
                    self._raise_if_login_redirect()
                    return True
        except (PlaywrightError, TimeoutError, RuntimeError, ValueError) as error:
            raise CaptureChallengeError(
                f"Could not navigate to the next page: {error}"
            ) from error

        try:
            user_input = input(
                f"Could not click the next-page button automatically. "
                f"Click page {next_number} in the browser and press ENTER here, "
                f"or type 'q' to stop: "
            )
        except (EOFError, KeyboardInterrupt):
            return False
        return user_input.strip().lower() != "q"

    def _raise_if_login_redirect(self) -> None:
        url = self._page.url.lower()
        if any(token in url for token in ("/login", "/signin", "/sign-in", "/logon")):
            raise CaptureChallengeError(
                "BCA redirected to a login page — the session expired or access "
                "was denied. Halting without bypass; pages captured so far are saved."
            )


def run_capture_command(options: CaptureOptions) -> int:
    """Open the browser, run one capture, save it, and print the summary."""
    if sync_playwright is None:
        print("Playwright is required for the BCA capture command.")
        print("Install with: uv pip install playwright && playwright install chromium")
        return 2

    print("=" * 70)
    print("BCA capture command")
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
            page.goto("https://www.bca.co.uk", wait_until="domcontentloaded")

            print("\n[Step 1] A visible browser opened at www.bca.co.uk.")
            print("Log in to your BCA account and run your search in that browser.")
            print("The tool does not see or store your username or password.")
            print(
                "When your search results are displayed, return here and press ENTER.\n"
            )
            try:
                input("[Press ENTER when your BCA search results are on screen] > ")
            except (EOFError, KeyboardInterrupt):
                print("\nCapture aborted — nothing was saved.")
                return 1

            page_source = _PlaywrightPageSource(page)
            outcome = run_capture(
                options,
                page_source,
                bca_capture_strategy,
                hooks=CaptureHooks(pace=_countdown_pacing),
            )
        finally:
            browser.close()

    capture_dir = save_capture(outcome, options)
    print_capture_summary(outcome, capture_dir)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = ArgumentParser(description="BCA search capture command")
    parser.add_argument(
        "--search-name",
        required=True,
        help="Name for this capture, saved in the manifest",
    )
    parser.add_argument(
        "--result-limit",
        type=int,
        default=5,
        help="Maximum number of result pages to capture (default: 5)",
    )
    parser.add_argument(
        "--move-delay",
        type=float,
        default=60.0,
        help=(
            "Delay in seconds between page movements; must be greater than zero "
            "(default: 60.0)"
        ),
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data/captures/bca"),
        help="Directory where captures are saved (default: data/captures/bca)",
    )
    args = parser.parse_args(argv)
    try:
        options = CaptureOptions(
            search_name=args.search_name,
            source=SourceKind.BCA,
            movement_limit=args.result_limit,
            movement_delay_seconds=args.move_delay,
            data_dir=args.data_dir,
        )
    except ValueError as error:
        parser.error(str(error))
    return run_capture_command(options)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
