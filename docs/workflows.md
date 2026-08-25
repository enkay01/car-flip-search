# Application workflows

This guide covers installing Car Flip Search, its domain terms, and its three main workflows. Human operators and automated systems use the same steps.

## Installation and setup

### Prerequisites

- Python 3.13 or newer
- The `uv` package manager. On Linux/macOS, run `curl -LsSf https://astral.sh/uv/install.sh`. On Windows, run `irm https://astral.sh/uv/install.ps1 | iex`.
- Google Chrome or Chromium. Browser capture commands need one of them.

### Setup

1. Clone the repository.

```bash
git clone https://github.com/enkay01/car-flip-search.git
cd car-flip-search
```

2. Install dependencies and the optional browser group.

```bash
uv sync --extra browser
```

3. Install the Playwright Chromium binary.

```bash
uv run playwright install chromium
```

4. Run the tests and linters.

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

---

## Domain concepts

These definitions come from `CONTEXT.md`. Use them consistently.

- **Auction Lot**: An unsold vehicle listed on BCA, identified by its BCA lot record.
- **CAP Clean Price**: The valuation for a clean-condition vehicle shown on its BCA lot record, in whole pounds.
- **Auto Trader Listing**: A live UK advertisement on Auto Trader with a Cash Price.
- **Candidate Vehicle**: An Auction Lot evaluated against retail market pricing.
- **Core Vehicle Identity**: Lots and listings share one identity, make and Model Variant. Registration year and Mileage Band are separate criteria. Fuel type, transmission, body style, and door count are informational Vehicle Details.
- **Market Comparable**: An Auto Trader Listing that matches the make, Model Variant, and registration year of a Candidate Vehicle, with mileage within plus or minus 15,000 miles.
- **High-Mileage Reference**: An Auto Trader Listing that matches the make, Model Variant, and registration year but has mileage above the plus 15,000 mile window.
- **Retail Floor**: The lowest Advertised Price among High-Mileage References.
- **Price Spread**: The lowest Advertised Price among direct Market Comparables minus the CAP Clean Price.
- **Retail-Floor Spread**: The Retail Floor minus the CAP Clean Price.
- **Capture**: A saved directory that contains raw HTML pages (`pages/`), parsed valid records (`records.json`), skipped records (`skipped.json`), and metadata (`manifest.json`).
- **Capture Pair**: One BCA Capture and one Auto Trader Capture loaded together in the dashboard or CLI to build an Opportunity List.

## Workflow 1: End-to-end human supervised flow

Use this workflow when a human operator inspects BCA auction catalogues, captures a batch of live lots, collects matching Auto Trader market listings, and reviews opportunities in the web UI.

### Step 1: Open BCA and run a search in a headed browser

Run the BCA capture command:

```bash
uv run car-flip search-bca \
  --search-name "Mercedes A-Class Petrol" \
  --result-limit 5 \
  --move-delay 60
```

Legacy script:

```bash
uv run python tools/bca_headed_fetch.py --search-name "Mercedes A-Class Petrol" --result-limit 5 --move-delay 60
```

Execution details:

1. Playwright opens a visible Chrome window at `https://www.bca.co.uk`.
2. Log in manually with your BCA credentials. The application never inspects, captures, or persists credentials.
3. Set your search filters, for example make, model, and fuel type, then open the catalogue results.
4. When lot cards appear, the CLI detects them and starts capturing data.
5. The tool saves the current page to `data/captures/bca/<capture_id>/pages/page_01.html`, writes valid records to `records.json`, and logs skipped lots in `skipped.json`.
6. The tool clicks pagination controls to load the next page. Between pages it waits 60 seconds and prints a countdown to stderr.
7. Capture stops at the page limit, by default 5, when no more pages exist, or when the operator interrupts the process.

Output JSON:

```json
{
  "capture_dir": "data/captures/bca/20260825T010000Z-a1b2c3d4",
  "capture_id": "20260825T010000Z-a1b2c3d4",
  "pages_captured": 5,
  "records_captured": 48,
  "records_skipped": 2,
  "search_name": "Mercedes A-Class Petrol",
  "source": "bca",
  "status": "success",
  "stop_reason": "completed"
}
```

### Step 2: Open Auto Trader and capture market evidence

Run the Auto Trader capture command for the corresponding vehicle family:

```bash
uv run car-flip search-autotrader \
  --search-name "Mercedes A-Class Petrol" \
  --make "Mercedes-Benz" \
  --model "A Class" \
  --fuel-type "Petrol" \
  --result-limit 5 \
  --move-delay 60
```

Or fetch it manually in a browser:

```bash
uv run python tools/autotrader_headed_fetch.py --search-name "Mercedes A-Class Petrol" --result-limit 5 --move-delay 60
```

How the capture runs:

1. Auto Trader does not need authentication. The command opens a visible Chrome browser and goes to the query URL.
2. The CLI closes cookie consent dialogs automatically.
3. The tool reads vehicle cards from the page DOM and scrolls down in batches to load more results.
4. The tool waits 60 seconds between scroll batches to avoid request throttling.
5. The capture stops when it reaches the movement limit, when two consecutive scrolls produce no new listing IDs, or when you cancel it.
6. The tool deduplicates records by listing ID and saves them to `data/captures/autotrader/<capture_id>/`.

Output JSON:

```json
{
  "capture_dir": "data/captures/autotrader/20260825T011000Z-e5f6g7h8",
  "capture_id": "20260825T011000Z-e5f6g7h8",
  "pages_captured": 5,
  "records_captured": 75,
  "records_skipped": 0,
  "search_name": "Mercedes A-Class Petrol",
  "source": "autotrader",
  "status": "success",
  "stop_reason": "completed"
}
```

### Step 3. Launch the local dashboard and compare datasets in the UI

Start the local Flask dashboard:

```bash
uv run dev
```

`uv run dashboard` is an equivalent command. You can also set the port and data paths:

```bash
uv run dev --port 5050 --no-browser --data-root data/captures
```

The web server starts at `http://127.0.0.1:5000` and opens your default browser.

#### Using the dashboard interface

1. **Select a Capture Pair**:
   - The top input panel has two dropdown menus, BCA and Auto Trader.
   - Select the BCA Capture ID and Auto Trader Capture ID you want. The newest usable capture from each source is selected by default.
   - Click "Load pair". The URL updates to `/?bca_capture_id=<id>&autotrader_capture_id=<id>`.
   - The dashboard rereads the underlying files on every HTTP request, so new captures appear as soon as they are saved.

2. **Inspect capture metadata and warnings**:
   - Open the collapsible details under the picker to review capture timestamps, page counts, record counts, skipped counts, and stop reasons.
   - If the search names differ between the two captures, the dashboard shows an informational warning, but comparison stays enabled.

3. **Filter and search candidate vehicles**:
   - The Opportunity List shows all Comparison-Eligible Candidate Vehicles.
   - Use the text search box to filter rows by make, model, registration year, or BCA lot ID. Filtering runs in the browser and updates the visible count as you type.

4. **Sort by valuation signals**:
   - Click any column header to sort in ascending or descending order:
     * **Mileage**: Vehicle odometer reading.
     * **CAP Clean Price**: Base auction benchmark.
     * **Retail-Floor Spread**: Spread derived from High-Mileage References.
     * **Price Spread**: Spread derived from direct Market Comparables.
     * **Comparable Supply**: Total number of matching retail comparables.

5. **Expand candidate vehicle details**:
   - Click the `+` icon on any vehicle row to open the inline evidence drawer.
   - **Market Comparables panel**: Shows all Auto Trader listings within plus or minus 15,000 miles. The lowest priced listing has a "Cheapest" tag.
   - **High-Mileage References panel**: Shows listings with mileage above the plus 15,000 mile window. The lowest priced reference has a "Sets Retail Floor" tag.

6. **Open live source links**:
   - Click "Open" or "Open Auction Lot" on candidate rows or evidence cards to open the original BCA lot or Auto Trader listing in a new browser tab.

7. **Manage and delete captures**:
   - Click "Manage Captures" in the header to go to `/captures`.
   - Review all saved captures across BCA and Auto Trader directories.
   - Select unused captures with checkboxes and click "Delete selected" to free disk space.

---

## Workflow 2: Quick compare flow (agent-assisted headed browser)

A local coding agent, such as Claude Code, Codex, or Antigravity, receives a screenshot of one BCA lot. It extracts the vehicle spec, opens a visible browser to collect matching retail listings, and prepares the data for comparison.

### Step 1: provide the BCA lot screenshot to the agent

The user sends the agent a screenshot of the BCA vehicle card or detail sheet. The image includes:

- Make, for example `Audi`
- Model variant, for example `A3`
- Registration year, for example `2018`
- Mileage, for example `62,000`
- CAP Clean Price, for example `£12,500`
- Fuel type, for example `Petrol`
- Transmission, for example `Automatic`
- Trim, for example `TFSI Sport`

### Step 2. Agent builds the search URL and opens headed Auto Trader capture

Run `car-flip search-autotrader` in headed mode, which is the default:

```bash
uv run car-flip search-autotrader \
  --search-name "Audi A3 2018 Petrol Quick Compare" \
  --make "Audi" \
  --model "A3" \
  --year 2018 \
  --mileage 62000 \
  --fuel-type "Petrol" \
  --transmission "Automatic" \
  --trim "TFSI" \
  --result-limit 3 \
  --move-delay 60 \
  --pretty
```

You can also pass vehicle attributes through JSON stdin:

```bash
echo '{"make": "Audi", "model": "A3", "year": 2018, "mileage": 62000, "fuel_type": "Petrol", "transmission": "Automatic", "trim": "TFSI"}' | uv run car-flip search-autotrader --search-name "Audi A3 2018 Petrol Quick Compare" --json-input --result-limit 3 --move-delay 60 --pretty
```

How this runs:
1. The CLI builds the exact Auto Trader query URL:
   `https://www.autotrader.co.uk/car-search?aggregatedTrim=TFSI&channel=cars&exclude-writeoff-categories=on&fuel-type=Petrol&make=Audi&maximum-mileage=77000&minimum-mileage=47000&model=A3&postcode=NG2+3JW&seller-type=private&seller-type=trade&sort=price-asc&transmission=Automatic&year-from=2018&year-to=2018`
2. Playwright launches a visible Chrome browser at that URL.
3. The tool dismisses cookie consent popups automatically.
4. The tool scrolls through result batches, waits 60 seconds between batches, and extracts all listing cards.
5. The tool saves the capture under `data/captures/autotrader/<capture_id>/` and returns the `capture_id` in stdout JSON.

### Step 3: Compare against the captured evidence

Compare the BCA lot with the captured market evidence using the CLI or UI.

CLI comparison:
```bash
uv run car-flip compare-vehicle \
  --make "Audi" \
  --model "A3" \
  --year 2018 \
  --mileage 62000 \
  --cap-clean-price 12500 \
  --fuel-type "Petrol" \
  --transmission "Automatic" \
  --trim "TFSI" \
  --autotrader-capture-id "<capture_id>" \
  --pretty
```

UI comparison:
Run `uv run dev` and review the candidate vehicle next to its captured Auto Trader dataset in the browser.

---

## Workflow 3: Automated headed comparison

The agent runs this workflow autonomously in a visible browser session. It takes a screenshot or vehicle payload, converts it into structured JSON, launches a headed browser to capture Auto Trader evidence automatically without manual interaction, runs the comparison calculation, and returns valuation signals to the user.

### Step 1: Convert screenshot to vehicle JSON

Read the BCA lot screenshot and produce the normalized vehicle object:

```json
{
  "make": "Audi",
  "model": "A3",
  "year": 2018,
  "mileage": 60000,
  "cap_clean_price": 12500,
  "fuel_type": "Petrol",
  "transmission": "Automatic",
  "trim": "TFSI"
}
```

### Step 2: Agent runs the headed Auto Trader capture

Run the capture command with vehicle criteria:

```bash
uv run car-flip search-autotrader \
  --search-name "Audi A3 2018 Automated" \
  --make "Audi" \
  --model "A3" \
  --year 2018 \
  --mileage 60000 \
  --fuel-type "Petrol" \
  --transmission "Automatic" \
  --trim "TFSI" \
  --result-limit 3 \
  --move-delay 60
```

Playwright opens a visible Chrome window directly to the scoped search URL. The tool dismisses cookie consent dialogs automatically, captures listings across infinite scroll batches with 60 second pacing, and saves the output to disk without requiring user input. The command returns:

```json
{
  "capture_dir": "data/captures/autotrader/20260825T012500Z-9988aabb",
  "capture_id": "20260825T012500Z-9988aabb",
  "pages_captured": 3,
  "records_captured": 45,
  "records_skipped": 0,
  "search_name": "Audi A3 2018 Automated",
  "source": "autotrader",
  "status": "success",
  "stop_reason": "completed"
}
```

### Step 3: agent executes vehicle comparison and sorting

Run `compare-vehicle` with the vehicle details and captured ID:

```bash
uv run car-flip compare-vehicle \
  --make "Audi" \
  --model "A3" \
  --year 2018 \
  --mileage 60000 \
  --cap-clean-price 12500 \
  --fuel-type "Petrol" \
  --transmission "Automatic" \
  --trim "TFSI" \
  --autotrader-capture-id "20260825T012500Z-9988aabb" \
  --pretty
```

Use this piped JSON form:
```bash
echo '{"make": "Audi", "model": "A3", "year": 2018, "mileage": 60000, "cap_clean_price": 12500, "fuel_type": "Petrol", "transmission": "Automatic", "trim": "TFSI"}' | uv run car-flip compare-vehicle --autotrader-capture-id "20260825T012500Z-9988aabb" --json-input --pretty
```

The CLI returns:
- **Market Comparables**: Listings that match make, model variant, year, and mileage within 45,000 to 75,000 miles. Sorted by lowest Advertised Price.
- **High-Mileage References**: Listings that match make, model variant, and year with mileage above 75,000 miles.
- **Price Spread**: Cheapest Market Comparable price minus CAP Clean Price (£12,500).
- **Retail Floor**: Cheapest High-Mileage Reference price.
- **Retail-Floor Spread**: Retail Floor minus CAP Clean Price (£12,500).

Sample JSON response:
```json
{
  "candidate": {
    "body_style": null,
    "cap_clean_price_pounds": 12500,
    "door_count": null,
    "fuel_type": "Petrol",
    "id": "AD-HOC-INPUT",
    "identity": {
      "body_style": null,
      "door_count": null,
      "fuel_type": "Petrol",
      "make": "Audi",
      "model_variant": "A3",
      "registration_year": 2018,
      "transmission": "Automatic"
    },
    "make": "Audi",
    "mileage": 60000,
    "model_variant": "A3",
    "registration_year": 2018,
    "transmission": "Automatic",
    "trim": "TFSI"
  },
  "high_mileage_references": [
    {
      "advertised_price_pounds": 13995,
      "identity": {
        "body_style": "Hatchback",
        "door_count": 5,
        "fuel_type": "Petrol",
        "make": "Audi",
        "model_variant": "A3",
        "registration_year": 2018,
        "transmission": "Automatic"
      },
      "listing_id": "at-ref-1",
      "mileage": 82000,
      "seller_type": "trade",
      "trim": "TFSI Sport"
    }
  ],
  "market_comparables": [
    {
      "advertised_price_pounds": 14995,
      "identity": {
        "body_style": "Hatchback",
        "door_count": 5,
        "fuel_type": "Petrol",
        "make": "Audi",
        "model_variant": "A3",
        "registration_year": 2018,
        "transmission": "Automatic"
      },
      "listing_id": "at-comp-1",
      "mileage": 58000,
      "seller_type": "trade",
      "trim": "TFSI Sport",
      "trim_match": true
    },
    {
      "advertised_price_pounds": 15450,
      "identity": {
        "body_style": "Saloon",
        "door_count": 4,
        "fuel_type": "Petrol",
        "make": "Audi",
        "model_variant": "A3",
        "registration_year": 2018,
        "transmission": "Automatic"
      },
      "listing_id": "at-comp-2",
      "mileage": 64000,
      "seller_type": "private",
      "trim": "TFSI S Line",
      "trim_match": false
    }
  ],
  "market_snapshot_summary": {
    "total_listings_observed": 45
  },
  "status": "success",
  "valuation": {
    "cap_clean_price_pounds": 12500,
    "comparable_supply": 2,
    "high_mileage_reference_count": 1,
    "price_spread_pounds": 2495,
    "retail_floor_pounds": 13995,
    "retail_floor_spread_pounds": 1495
  }
}
```

### Step 4: Present results to the user

Format the valuation signals and comparables into a structured report:

- **Target Vehicle**: 2018 Audi A3 Petrol Automatic (60,000 miles)
- **CAP Clean Benchmark**: £12,500
- **Market Comparables (45k to 75k miles)**: 2 active listings found
  * Cheapest comparable: £14,995 (58,000 miles, Trade)
  * Price spread: +£2,495 above CAP Clean Price
- **High-Mileage References (>75k miles)**: 1 reference found
  * Retail Floor: £13,995 (82,000 miles, Trade)
  * Retail-floor spread: +£1,495 above CAP Clean Price

---

## Agent tool integration

Agents can request JSON schemas for tools:

```bash
uv run car-flip tool-schema --pretty
```

Tool definitions:
- `build-autotrader-url`: Build a scoped Auto Trader search URL.
- `search-autotrader`: Capture market listings with headed or headless infinite scroll.
- `search-bca`: Capture BCA auctions in a headed browser with user assistance.
- `compare-vehicle`: Evaluate one vehicle against market evidence on demand.
- `match-pair`: Match two saved captures into a full Opportunity List.
