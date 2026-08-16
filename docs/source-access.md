# Permitted Source Access Specification

This document details the permitted access mechanisms, account permissions, usage constraints, rate limits, credential handling, backoff policies, hard stop mechanisms, and manual/headed browser import routes for BCA and Auto Trader.

## 1. Source Access Overview

| Source | Approved Access Mechanism | Required Permissions | Usage Constraints | Rate Limit / Cadence |
|---|---|---|---|---|
| **BCA** | Partner REST API / Trade Portal Catalogue Feed (JSON/CSV) / Headed DOM Capture (`tools/bca_headed_fetch.py`) | Registered BCA Trade Buyer Account (`Catalog:Read`, `Valuation:Read`) | Read-only lot inspection with CAP Clean Price; headed browser if API unavailable; strictly no CAPTCHA bypass | API: 1 req/s, max concurrency = 1; Headed DOM: max 1 page/min, max 5 pages/run |
| **Auto Trader** | Auto Trader Connect Developer API (REST / OAuth2) / Market Snapshot Feed / Headed DOM Capture (`tools/autotrader_headed_fetch.py`) | Registered Auto Trader Developer / Commercial Partner Account (`Stock:Read`, `Search:Read`) | Live UK Cash Price listings only; strictly no scraping of consumer website, Akamai bypass, or CAPTCHA bypass | API: max 5 req/s; Headed DOM: max 1 page/min, max 5 pages/run |

---

## 2. BCA (British Car Auctions)

### Permitted Access Mechanisms
- **BCA Partner API**: Authenticated HTTPS REST endpoints providing vehicle catalogue and auction lot data using an API key or Bearer token (`BcaSourceClient`).
- **BCA Trade Portal Export**: Authenticated catalogue data exports (JSON/CSV) generated through a verified BCA Trade Buyer account.
- **Headed Browser DOM Capture**: When direct APIs are unavailable, a headed browser session (`tools/bca_headed_fetch.py`) operated under user authentication saves DOM pages locally to `data/bca_pages/` for parsing by `ManualBcaImporter.import_from_html`.

### Account Permissions
- Registered BCA Trade / Buyer account with active permissions to browse auction catalogues and view CAP valuation benchmarks.

### Usage Constraints
- Automated access is permitted only via approved API endpoints, verified export feeds, or user-assisted headed browser DOM capture.
- Automated CAPTCHA bypass, anti-bot circumvention, and proxy rotation are strictly prohibited.
- For headed browser capture (`tools/bca_headed_fetch.py`):
  - **Cadence**: Maximum 1 page per minute (60 seconds delay between page navigations with real-time countdown).
  - **Scope**: Maximum 5 pages per run.
  - **Storage**: Complete page DOM is saved to local disk (`data/bca_pages/`) and parsed locally.
- Acquired records must be filtered to condition-eligible lots (clean condition, no reported write-off or accident damage) with whole-pound CAP Clean Prices.

### Headed Browser Usage (CLI)
```bash
uv run python tools/bca_headed_fetch.py --output-dir data/bca_pages --max-pages 5 --interval 60
```

---

## 3. Auto Trader

### Permitted Access Mechanisms
- **Auto Trader Connect API**: Official Developer Platform REST API using OAuth2 client credentials (`client_id`, `client_secret`) or assigned API keys (`AutoTraderSourceClient`).
- **Market Snapshot Feed**: Structured JSON/CSV export files loaded directly into the market input boundary.
- **Headed Browser DOM Capture**: When developer APIs are not provisioned, a headed browser session (`tools/autotrader_headed_fetch.py`) operated under user authentication saves DOM pages locally to `data/autotrader_pages/` for parsing by `ManualAutoTraderImporter.import_from_html`.

### Account Permissions
- Commercial partner or approved developer credentials with vehicle search and stock read scopes.

### Usage Constraints
- Auto Trader terms of use strictly prohibit scraping public consumer search pages, bypassing Akamai Bot Manager, solving CAPTCHAs, or rotating proxies.
- Only live UK advertised listings with Cash Price are ingested. Finance illustrations, leasing estimates, and historical sales are excluded.
- For headed browser capture (`tools/autotrader_headed_fetch.py`):
  - **Cadence**: Maximum 1 page per minute (60 seconds delay between page navigations with real-time countdown).
  - **Scope**: Maximum 5 pages per run.
  - **Storage**: Complete page DOM is saved to local disk (`data/autotrader_pages/`) and parsed locally.

### Headed Browser Usage (CLI)
```bash
uv run python tools/autotrader_headed_fetch.py --output-dir data/autotrader_pages --max-pages 5 --interval 60
```

---

## 4. Credential Isolation and Revocation

### Isolation
- Credential objects (`BcaCredentials`, `AutoTraderCredentials`) are encapsulated inside the source access layer (`src/car_flip_search/source_access.py`).
- `__repr__` and `__str__` implementations mask secret values (e.g. `api_key="***"`) so that tokens cannot appear in application logs, error traces, or diagnostic dumps.
- Domain models (`AuctionLot`, `AutoTraderListing`, `MarketSnapshot`, `CandidateVehicle`, `OpportunityList`) contain zero authentication or transport state.

### Revocation Procedure
- **BCA**: Invalidate API keys via the BCA partner developer portal or change trade portal passwords. In application memory, call `credentials.revoke()` to clear active tokens immediately.
- **Auto Trader**: Rotate `client_secret` or revoke API tokens via the Auto Trader Developer Portal. In application memory, call `credentials.revoke()` to clear stored secrets and cached bearer tokens.

---

## 5. Resilience, Backoff, and Hard Stops

### Cadence, Caching, and Deduplication
- **Cadence**: Pacing enforced before sending each HTTP request (0.2s–1.0s) or navigating each browser page (60s).
- **Caching**: In-memory response cache with key/TTL support to avoid repeated queries for unchanged lots or listings during a run.
- **Deduplication**: Source IDs (`AuctionLotId`, `AutoTraderListingId`) are deduplicated prior to emission.

### Retry-After-Aware Exponential Backoff
- When encountering a transient HTTP 429 (Too Many Requests), the client checks for a `Retry-After` header (seconds or HTTP date).
- If present, the client pauses for the duration specified.
- If absent, exponential backoff with jitter is applied: `delay = min(max_delay, base_delay * 2^attempt) + jitter`.
- Retries are bounded to a maximum of 3 attempts.

### Hard Stops (No Evasion)
The system executes an immediate hard stop without retrying, rotating proxies, or attempting evasion in any of the following scenarios:
1. **Authentication Challenge (HTTP 401 / 403)**: Invalid, expired, or missing credentials (`AuthenticationChallengeError`).
2. **Anti-Bot / CAPTCHA Detection**: Response body, browser page, or headers indicate a Cloudflare, Akamai, or CAPTCHA challenge (`BotChallengeDetectedError`).
3. **Repeated Throttling**: Exceeding the maximum retry count on HTTP 429 responses (`RepeatedThrottlingError`).

---

## 6. No-Go Decision and Supported Import Routes

When automated API access is not permitted (e.g., missing API credentials, unapproved account type, or presence of bot challenges):
1. The access layer records a clear `NO_GO_MANUAL_REQUIRED` access decision via `assess_bca_access()` or `assess_auto_trader_access()` with detailed rationale.
2. The system falls back to supported first-class import routes:
   - `ManualBcaImporter`: Ingests JSON/CSV catalogue exports, raw records, or saved HTML DOM files into `AuctionLot` records via `BcaAcquisition`.
   - `ManualAutoTraderImporter`: Ingests JSON/CSV market snapshot feeds, raw records, or saved HTML DOM files into `MarketSnapshot` via `AutoTraderAcquisition`.
   - `tools/bca_headed_fetch.py`: Headed browser capture workflow (max 5 pages, 1 page/min) for BCA search results.
   - `tools/autotrader_headed_fetch.py`: Headed browser capture workflow (max 5 pages, 1 page/min) for Auto Trader search results.
3. This guarantees compliant, verified operation without compromising account security or violating third-party terms.
