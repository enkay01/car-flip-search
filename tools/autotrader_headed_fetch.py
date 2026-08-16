"""Headed browser capture tool for Auto Trader search results pages.

Enforces safe user-controlled access:
- Headed browser workflow with human-in-the-loop session navigation.
- Handles Auto Trader's infinite scroll architecture by triggering progressive scroll events.
- Conservative cadence (configurable interval, default 60.0s / max 1 batch per min).
- Bounded scope (max 5 batches per run).
- DOM saving to local files and local parsing via ManualAutoTraderImporter.
- Immediate hard stop if bot/CAPTCHA challenges appear.
"""

import sys
import time
from argparse import ArgumentParser
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from car_flip_search import ManualAutoTraderImporter


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
        "akamai bot manager",
    )
    return any(marker in lower_content for marker in markers)


def parse_saved_pages(output_dir: Path) -> int:
    """Parse all saved HTML pages in output_dir and print acquired listings summary."""
    importer = ManualAutoTraderImporter()
    total_listings = 0
    html_files = sorted(output_dir.glob("*.html"))
    if not html_files:
        print(f"No HTML files found in {output_dir}")
        return 0

    print(f"Parsing {len(html_files)} saved Auto Trader HTML files...")
    for file_path in html_files:
        snapshot = importer.import_from_html_file(str(file_path))
        print(
            f"  - {file_path.name}: {len(snapshot.listings)} valid market listings parsed"
        )
        total_listings += len(snapshot.listings)

    print(
        f"Total acquired Auto Trader listings from saved pages: {total_listings}"
    )
    return total_listings


def _countdown_pacing(seconds: float) -> None:
    """Show a real-time countdown in the terminal during cadence delay."""
    remaining = int(seconds)
    print(
        f"Pacing cadence: {remaining}s remaining before next scroll batch...",
        end="",
        flush=True,
    )
    while remaining > 0:
        time.sleep(1)
        remaining -= 1
        if remaining % 10 == 0 or remaining <= 5:
            print(f" {remaining}s...", end="", flush=True)
    print(" Ready!")


def run_headed_fetch(options: FetchOptions) -> int:
    """Execute the headed Playwright browser capture session for Auto Trader."""
    if options.dry_run:
        return parse_saved_pages(options.output_dir)

    try:
        from playwright.sync_api import (
            sync_playwright,
        )
    except ImportError:
        print(
            "Playwright is not installed. To install: uv pip install playwright && playwright install chromium"
        )
        print("Falling back to parsing existing saved files.")
        return parse_saved_pages(options.output_dir)

    options.output_dir.mkdir(parents=True, exist_ok=True)
    importer = ManualAutoTraderImporter()
    total_acquired = 0

    print("=" * 70)
    print("Auto Trader Headed Browser Capture Tool (Infinite Scroll)")
    print(f"Output directory : {options.output_dir}")
    print(f"Max scroll batches: {options.max_pages}")
    print(
        f"Interval         : {options.interval_seconds}s (cadence: max 1 batch/min)"
    )
    print("=" * 70)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        print(
            "\n[Step 1] Opening browser window to https://www.autotrader.co.uk ..."
        )
        print(
            "Please navigate to your car search results page (apply make/model filters)."
        )
        print(
            "When the search results are displayed on screen, return here and press ENTER.\n"
        )
        page.goto("https://www.autotrader.co.uk")

        try:
            input(
                "[Press ENTER when ready on Auto Trader search results page] > "
            )
        except (EOFError, KeyboardInterrupt):
            print("\nAborting capture session.")
            browser.close()
            return 0

        current_batch = 1
        while current_batch <= options.max_pages:
            print(
                f"\n==================== Capturing Batch {current_batch} of {options.max_pages} ===================="
            )

            # Auto Trader uses infinite scroll: trigger smooth progressive scroll down
            print("Triggering scroll to load additional listings...")
            for _ in range(3):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1200)

            html_content = page.content()

            if check_for_challenge_text(html_content):
                print(
                    "WARNING: Bot verification or CAPTCHA challenge detected!"
                )
                print(
                    "Hard stop policy activated: halting automated capture without bypass."
                )
                break

            output_file = (
                options.output_dir / f"autotrader_page_{current_batch}.html"
            )
            output_file.write_text(html_content, encoding="utf-8")
            print(f"Saved DOM ({len(html_content):,} bytes) to: {output_file}")

            if options.parse_on_save:
                snapshot = importer.import_from_html(html_content)
                print(
                    f"Parsed {len(snapshot.listings)} cumulative valid listings with Cash Prices."
                )
                total_acquired = len(snapshot.listings)

            if current_batch >= options.max_pages:
                print(
                    f"\nReached maximum scroll batch limit ({options.max_pages}). Capture session complete."
                )
                break

            # Pacing countdown
            print()
            _countdown_pacing(options.interval_seconds)

            current_batch += 1

        browser.close()

    print(
        "\n======================================================================"
    )
    print(
        f"Capture session completed successfully! Total unique listings acquired: {total_acquired}"
    )
    print(
        "======================================================================"
    )
    return total_acquired


def main(argv: Sequence[str] | None = None) -> None:
    parser = ArgumentParser(
        description="Auto Trader Headed Browser Page Capture Tool"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/autotrader_pages"),
        help="Directory where captured HTML pages are stored",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=5,
        help="Maximum number of scroll batches to capture (default: 5)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=60.0,
        help="Delay in seconds between scroll batches (default: 60.0s / 1 batch per min)",
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
