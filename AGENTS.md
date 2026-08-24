## Agent skills

### Issue tracker

Issues and specs are tracked in GitHub Issues using the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Domain docs

This repo uses single-context domain documentation. See `docs/agents/domain.md`.

### Car Search & Valuation CLI Workflow

When finding market evidence or floor prices on Auto Trader:
**NEVER use browser computer use or manual browser clicking to search Auto Trader.**
Auto Trader requires no login for car searches. Always use the CLI directly:

1. **Capture Auto Trader Listings**:
   Run `car-flip search-autotrader` with vehicle criteria or `--url` (supports `--headless`):
   ```bash
   uv run car-flip search-autotrader \
     --search-name "Audi A3 2018 Petrol" \
     --make Audi \
     --model A3 \
     --year 2018 \
     --mileage 60000 \
     --fuel-type Petrol \
     --transmission Automatic \
     --body-type Hatchback \
     --body-type Saloon \
     --trim TFSI \
     --headless
   ```
   This automatically constructs the scoped Auto Trader search URL, opens Playwright directly to it, auto-dismisses cookie overlays, captures results via infinite scroll, and returns a JSON payload with `capture_id`.

2. **Evaluate Vehicle Against Market Evidence**:
   Pass the captured `autotrader_capture_id` (or a market file) into `car-flip compare-vehicle`:
   ```bash
   uv run car-flip compare-vehicle \
     --make Audi \
     --model A3 \
     --year 2018 \
     --mileage 60000 \
     --cap-clean-price 12500 \
     --autotrader-capture-id "<capture_id>"
   ```

3. **Generate Auto Trader Search URL (Without Browser)**:
   To inspect or verify search URLs:
   ```bash
   uv run car-flip build-autotrader-url \
     --make Audi \
     --model A3 \
     --year 2018 \
     --mileage 60000 \
     --fuel-type Petrol \
     --pretty
   ```
   JSON stdin is supported via `--json-input` across `build-autotrader-url`, `search-autotrader`, and `compare-vehicle`.
