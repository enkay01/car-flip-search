# Car Flip Search

A Python application and library for identifying resale opportunities by comparing BCA Auction Lots against live Auto Trader market evidence.

## Installation and setup

### Prerequisites

- Python 3.13 or newer
- `uv` package manager
- Google Chrome or Chromium

### Setup

```bash
git clone https://github.com/enkay01/car-flip-search.git
cd car-flip-search
uv sync --extra browser
uv run playwright install chromium
```

## Documentation

Full operational workflows, domain definitions, and agent usage guides live in the documentation:

- [Application workflows](file:///d:/stroo/Documents/GitHub/car-flip-search/docs/workflows.md): Detailed guide for the end-to-end human supervised flow, quick compare flow, and headless comparison.
- [Domain model](file:///d:/stroo/Documents/GitHub/car-flip-search/CONTEXT.md): Glossary and invariants for auction lots, market comparables, and valuation signals.
- [Source access specification](file:///d:/stroo/Documents/GitHub/car-flip-search/docs/source-access.md): Permitted access policies and session boundaries.
- [Agent rules](file:///d:/stroo/Documents/GitHub/car-flip-search/AGENTS.md): CLI workflows and instructions for automated coding agents.

## Quick CLI reference

### Capture BCA search results

Opens a visible browser for manual login and search navigation, then captures up to the specified page limit:

```bash
uv run car-flip search-bca --search-name "A-Class Petrol" --result-limit 5 --move-delay 60
```

### Capture Auto Trader search results

Runs scoped infinite scroll capture in a visible browser session (supports `--headless`):

```bash
uv run car-flip search-autotrader \
  --search-name "Audi A3 2018 Petrol" \
  --make Audi \
  --model A3 \
  --year 2018 \
  --mileage 60000 \
  --fuel-type Petrol \
  --transmission Automatic \
  --trim TFSI
```

### Evaluate single vehicle against market evidence

```bash
uv run car-flip compare-vehicle \
  --make Audi \
  --model A3 \
  --year 2018 \
  --mileage 60000 \
  --cap-clean-price 12500 \
  --autotrader-capture-id "<capture_id>" \
  --pretty
```

### Local opportunity dashboard

Start the local Flask dashboard to review valuation signals:

```bash
uv run dev
```

The web server binds to `http://127.0.0.1:5000` and opens the default browser.

## Development

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```
