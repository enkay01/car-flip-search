## Agent skills

### Issue tracker

Issues and specs are tracked in GitHub Issues using the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Domain docs

This repo uses single-context domain documentation. See `docs/agents/domain.md` and `CONTEXT.md`.

### Application workflows

For complete instructions covering all operational workflows, see `docs/workflows.md`.

### Car search and valuation CLI workflows

When finding market evidence or floor prices on Auto Trader:
**NEVER use browser computer use or manual browser clicking to search Auto Trader.**
Auto Trader requires no login for car searches. Always use the CLI directly:

1. **Workflow 1: End-to-end human supervised flow**:
   - Capture BCA lots: `uv run car-flip search-bca --search-name "..." --result-limit 5 --move-delay 60`
   - Capture Auto Trader market evidence: `uv run car-flip search-autotrader --search-name "..." --make ... --model ... --result-limit 5 --move-delay 60`
   - Review in dashboard: `uv run dev`

2. **Workflow 2: Quick compare flow (headed browser)**:
   - Extract vehicle attributes from BCA lot screenshot or text.
   - Run headed Auto Trader capture:
     ```bash
     uv run car-flip search-autotrader \
       --search-name "Audi A3 2018 Petrol Quick Compare" \
       --make Audi \
       --model A3 \
       --year 2018 \
       --mileage 62000 \
       --fuel-type Petrol \
       --transmission Automatic \
       --trim TFSI \
       --pretty
     ```
   - Compare via CLI (`car-flip compare-vehicle`) or inspect in UI (`uv run dev`).

3. **Workflow 3: Automated headed comparison (agent loop)**:
   - Convert BCA vehicle details to JSON.
   - Run headed Auto Trader capture:
     ```bash
     uv run car-flip search-autotrader \
       --search-name "Audi A3 2018 Automated" \
       --make Audi \
       --model A3 \
       --year 2018 \
       --mileage 60000 \
       --fuel-type Petrol \
       --transmission Automatic \
       --trim TFSI \
       --pretty
     ```
   - Evaluate against captured evidence:
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
   - Return structured valuation signals (Price Spread, Retail Floor, Comparable Supply) to user.

4. **Verify search URLs without browser**:
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
