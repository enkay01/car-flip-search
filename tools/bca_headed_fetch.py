"""Headed browser capture tool for BCA search results pages.

Enforces safe user-controlled access:
- Headed browser workflow with human-in-the-loop authentication.
- Conservative cadence (max 1 page per minute / 60-second interval).
- Bounded scope (max 5 pages per run).
- DOM saving to local files and local parsing via ManualBcaImporter.
- Immediate hard stop if bot/CAPTCHA challenges appear.
"""

import contextlib
import sys
import time
from argparse import ArgumentParser
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from car_flip_search import ManualBcaImporter


@dataclass(frozen=True, kw_only=True)
class FetchOptions:
    output_dir: Path
    max_pages: int = 5
    interval_seconds: float = 60.0
    parse_on_save: bool = True
    dry_run: bool = False


def check_for_challenge_text(html_content: str) -> bool:
    """Inspect page HTML for anti-bot or CAPTCHA challenge markers."""
    lower_content = html_content.lower()
    markers = (
        "cf-browser-verification",
        "challenge-platform",
        "g-recaptcha",
        "hcaptcha",
        "perimeterx",
        "please verify you are a human",
        "access denied - captcha",
        "attention required! | cloudflare",
    )
    return any(marker in lower_content for marker in markers)


def parse_saved_pages(output_dir: Path) -> int:
    """Parse all saved HTML pages in output_dir and print acquired lots summary."""
    importer = ManualBcaImporter()
    total_lots = 0
    html_files = sorted(output_dir.glob("*.html"))
    if not html_files:
        print(f"No HTML files found in {output_dir}")
        return 0

    print(f"Parsing {len(html_files)} saved BCA HTML files...")
    for file_path in html_files:
        lots = importer.import_from_html_file(str(file_path))
        print(f"  - {file_path.name}: {len(lots)} condition-eligible lots parsed")
        total_lots += len(lots)

    print(f"Total acquired Auction Lots from saved pages: {total_lots}")
    return total_lots


def run_headed_fetch(options: FetchOptions) -> int:
    """Execute the headed Playwright browser capture session."""
    if options.dry_run:
        return parse_saved_pages(options.output_dir)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "Playwright is not installed. To install: uv pip install playwright && playwright install chromium"
        )
        print("Falling back to parsing existing saved files.")
        return parse_saved_pages(options.output_dir)

    options.output_dir.mkdir(parents=True, exist_ok=True)
    importer = ManualBcaImporter()
    total_acquired = 0

    print("=" * 70)
    print("BCA Headed Browser Capture")
    print(f"Output directory: {options.output_dir}")
    print(f"Max pages: {options.max_pages}")
    print(f"Interval between pages: {options.interval_seconds}s (max 1 page/min)")
    print("=" * 70)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        print("\nOpening browser. Please navigate to BCA and log in if needed.")
        print(
            "Once on your search results page, press ENTER in this terminal to start capture..."
        )
        page.goto("https://www.bca.co.uk")

        try:
            input("\n[Press ENTER when ready on BCA search results page] > ")
        except (EOFError, KeyboardInterrupt):
            print("\nAborting capture session.")
            browser.close()
            return 0

        current_page = 1
        while current_page <= options.max_pages:
            print(f"\n--- Capturing Page {current_page} of {options.max_pages} ---")
            html_content = page.content()

            if check_for_challenge_text(html_content):
                print("WARNING: Bot verification or CAPTCHA challenge detected!")
                print(
                    "Hard stop policy activated: halting automated capture without bypass."
                )
                break

            output_file = (
                options.output_dir / f"bca_search_page_{current_page}.html"
            )
            output_file.write_text(html_content, encoding="utf-8")
            print(f"Saved DOM to: {output_file}")

            if options.parse_on_save:
                lots = importer.import_from_html(html_content)
                print(
                    f"Parsed {len(lots)} condition-eligible lots from page {current_page}."
                )
                total_acquired += len(lots)

            if current_page >= options.max_pages:
                print(
                    f"Reached maximum page limit ({options.max_pages}). Capture complete."
                )
                break

            print(
                f"Pacing: waiting {options.interval_seconds:.0f}s before moving to next page (1 page/min limit)..."
            )
            time.sleep(options.interval_seconds)

            # Scroll to bottom to ensure pagination bar is visible in DOM
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1000)

            # Try locating BCA next page button with multiple selector strategies
            next_selectors = [
                "button[aria-label='Go to next page']",
                f"button[aria-label='Go to page {current_page + 1}']",
                "button:has-text('next')",
                "a:has-text('next')",
                "a[rel='next']",
                ".pagination-next",
            ]

            clicked = False
            for selector in next_selectors:
                with contextlib.suppress(TimeoutError, RuntimeError, ValueError):
                    btn = page.locator(selector)
                    if btn.count() > 0 and btn.first.is_visible():
                        print(f"Clicking next page using '{selector}'...")
                        btn.first.click()
                        page.wait_for_load_state("networkidle")
                        clicked = True
                        break

            if not clicked:
                print(
                    f"\nCould not automatically locate the next page button for page {current_page + 1}."
                )
                try:
                    user_input = input(
                        f"Please navigate to page {current_page + 1} in the browser and press ENTER to continue (or 'q' to finish): "
                    )
                    if user_input.strip().lower() == "q":
                        print("User chose to end capture.")
                        break
                except (EOFError, KeyboardInterrupt):
                    break

            current_page += 1

        browser.close()

    print(f"\nCapture session completed. Total lots acquired: {total_acquired}")
    return total_acquired


def main(argv: Sequence[str] | None = None) -> None:
    parser = ArgumentParser(description="BCA Headed Browser Page Capture Tool")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/bca_pages"),
        help="Directory where captured HTML pages are stored",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=5,
        help="Maximum number of search pages to capture (default: 5)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=60.0,
        help="Delay in seconds between page navigations (default: 60.0s / 1 page per min)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only parse previously saved HTML pages without launching browser",
    )

    args = parser.parse_args(argv)
    options = FetchOptions(
        output_dir=args.output_dir,
        max_pages=args.max_pages,
        interval_seconds=args.interval,
        dry_run=args.dry_run,
    )
    run_headed_fetch(options)


if __name__ == "__main__":
    main(sys.argv[1:])
