# Permitted Source Access Specification

This document details the permitted access mechanisms, account permissions, usage constraints, rate limits, credential handling, backoff policies, hard stop mechanisms, and manual/headed browser import routes for BCA and Auto Trader.

## 1. Source Access Overview

| Source | Approved Access Mechanism | Required Permissions | Usage Constraints | Rate Limit / Cadence |
|---|---|---|---|---|
| **BCA** | User-assisted headed capture (`tools/bca_headed_fetch.py`) | Registered BCA Trade Buyer Account (login performed by the user in the visible browser) | Read-only lot inspection with CAP Clean Price; fresh session per run; strictly no CAPTCHA bypass | Configurable page delay (default 60s), page limit default 5 |
| **Auto Trader** | Auto Trader Connect Developer API (REST / OAuth2) / Market Snapshot Feed / Headed DOM Capture (`tools/autotrader_headed_fetch.py`) | Registered Auto Trader Developer / Commercial Partner Account for the API; **capture requires no login or credentials** | Live UK Cash Price listings only; strictly no scraping of consumer website, Akamai bypass, or CAPTCHA bypass | API: max 5 req/s; Headed capture: max 1 movement/min, result limit default 5 |

---

## 2. BCA (British Car Auctions)

### Permitted Access Mechanism
- **User-Assisted Headed Browser Capture** (only): `tools/bca_headed_fetch.py` opens a visible browser with a fresh session. The user logs in and runs one search; the command waits for Enter and then captures up to `result-limit` pages (default 5) at `move-delay` intervals (default 60s, must be greater than zero).
- The tool **never receives, stores, or persists BCA credentials or login sessions**. Every run starts from a fresh browser context; the user's username and password stay with the user.
- The BCA Partner API / API-key credential path (`BcaCredentials`, `BcaSourceClient`) was **removed** (#8) because it was unused.

### Account Permissions
- Registered BCA Trade / Buyer account; the user performs their own login and search in the visible browser.

### Usage Constraints
- One command run captures one BCA search.
- Each run saves a capture under `data/captures/bca/<capture_id>/` that is never overwritten:
  - `pages/page_NN.html` — original page data.
  - `records.json` — valid parsed car records (deduplicated by BCA lot ID; the latest version of a lot is kept).
  - `skipped.json` — one entry per skipped car with the lot where possible and every skip reason.
  - `manifest.json` — search name, capture ID, limits, counts, and stop reason.
- A car is skipped when a required field (lot ID, Core Vehicle Identity, mileage, CAP Clean Price, condition) is missing or invalid. The tool never invents condition, identity, mileage, or CAP Clean Price values.
- Automated CAPTCHA bypass, anti-bot circumvention, and proxy rotation are strictly prohibited.

### Capture Usage (CLI)
```bash
uv run python tools/bca_headed_fetch.py --search-name "A-Class Petrol" --result-limit 5 --move-delay 60
```

---

## 3. Auto Trader

### Permitted Access Mechanisms
- **Auto Trader Connect API**: Official Developer Platform REST API using OAuth2 client credentials (`client_id`, `client_secret`) or assigned API keys (`AutoTraderSourceClient`). Credentials are required only for this API path; the headed capture workflow below needs none.
- **Market Snapshot Feed**: Structured JSON/CSV export files loaded directly into the market input boundary.
- **User-Assisted Capture (`tools/autotrader_headed_fetch.py`)**: Auto Trader does not require login for this workflow. The command opens a visible browser with a fresh session, the user performs one search, presses Enter, and the command moves through the results in scroll batches up to a configurable `--result-limit` (default 5) at a configurable non-zero `--move-delay` (default 60s). Scrolling stops early once two consecutive scroll batches produce no new listing IDs. Each run saves a never-overwritten capture under `data/captures/autotrader/<capture_id>/` with the same layout as BCA: `pages/`, `records.json`, `skipped.json`, and `manifest.json`. Cars are deduplicated by Auto Trader listing ID, keeping the latest version.

- **Account Permissions**: Auto Trader capture requires no login, credentials, or account permissions. Auto Trader Connect API paths require commercial partner or approved developer credentials with vehicle search and stock read scopes.

### Usage Constraints
- Auto Trader terms of use strictly prohibit scraping public consumer search pages, bypassing Akamai Bot Manager, solving CAPTCHAs, or rotating proxies.
- Only live UK advertised listings with Cash Price are ingested. Finance illustrations, leasing estimates, and historical sales are excluded.
- For the user-assisted capture command (`tools/autotrader_headed_fetch.py`):
  - **Cadence**: Maximum 1 movement per minute (60 seconds delay between scroll batches with real-time countdown).
  - **Scope**: Maximum 5 result pages / scroll batches per run by default; a zero movement delay is rejected.
  - **Early stop**: Scrolling stops once two consecutive scroll batches produce no new listing IDs.
  - **Storage**: The capture command saves a never-overwritten capture directory (`data/captures/autotrader/<capture_id>/`) containing the original page data (`pages/`), the valid parsed records (`records.json`), a skipped-car log (`skipped.json`), and a manifest (`manifest.json`).

### Headed Capture Usage (CLI)
```bash
uv run python tools/autotrader_headed_fetch.py --search-name "A-Class Petrol" --result-limit 5 --move-delay 60
```

---

## 4. Credential Isolation and Revocation

### Isolation
- **BCA**: There are no BCA credential objects in the application. Credentials exist only inside the user's visible browser session; the capture command creates a fresh context per run and never persists cookies or sessions.
- **Credential Isolation**: Auto Trader **credentials are optional** and exist only for the Connect API path inside the source access layer (`src/car_flip_search/source_access.py`). The user-assisted capture workflow never requires, requests, or stores them. BCA has no credential objects in the application; credentials exist only inside the user's visible browser session, and the capture command creates a fresh context per run and never persists cookies or sessions.
- `__repr__` and `__str__` implementations mask secret values (e.g. `client_secret="***"`) so that tokens cannot appear in application logs, error traces, or diagnostic dumps.
- Domain models (`AuctionLot`, `AutoTraderListing`, `MarketSnapshot`, `CandidateVehicle`, `OpportunityList`) contain zero authentication or transport state.

### Revocation Procedure
- **BCA**: Change the BCA trade portal password in the user's own account; no application-side revocation exists because no credentials are stored. Closing the browser ends the ephemeral session.
- **Auto Trader**: Rotate `client_secret` or revoke API tokens via the Auto Trader Developer Portal. In application memory, call `credentials.revoke()` to clear stored secrets and cached bearer tokens.

---

## 5. Resilience, Backoff, and Hard Stops

### Cadence, Caching, and Deduplication
- **Cadence**: Pacing enforced before each HTTP request (0.2s–1.0s for Auto Trader API) or each browser movement (configurable, default 60s for both BCA and Auto Trader capture).
- **Caching**: In-memory response cache with key/TTL support to avoid repeated queries for unchanged lots or listings during a run (Auto Trader).
- **Deduplication**: Source IDs are deduplicated prior to emission; BCA captures deduplicate by lot ID keeping the latest captured version.

### Retry-After-Aware Exponential Backoff (Auto Trader API)
- When encountering a transient HTTP 429 (Too Many Requests), the client checks for a `Retry-After` header (seconds or HTTP date).
- If present, the client pauses for the duration specified.
- If absent, exponential backoff with jitter is applied: `delay = min(max_delay, base_delay * 2^attempt) + jitter`.
- Retries are bounded to a maximum of 3 attempts.

### Hard Stops (No Evasion)
The system executes an immediate hard stop without retrying, rotating proxies, or attempting evasion in any of the following scenarios:
1. **Authentication Challenge / Login Expiry**: The capture detects a login redirect or missing session and stops, telling the user to log in again — it never bypasses (`AuthenticationChallengeError` for APIs; capture stops with an explicit message for the browser workflow).
2. **Anti-Bot / CAPTCHA Detection**: Response body, browser page, or headers indicate a Cloudflare, Akamai, or CAPTCHA challenge (`BotChallengeDetectedError` / `detect_challenge_markers`; browser captures stop with an explicit message and still save everything captured so far).
3. **Repeated Throttling**: Exceeding the maximum retry count on HTTP 429 responses (`RepeatedThrottlingError`).

A capture that stops early still saves everything captured so far and is not treated as an error.

---

## 6. No-Go Decision and Supported Import Routes

When automated API access is not permitted (e.g., missing API credentials, unapproved account type, or presence of bot challenges):
1. The access layer records a clear decision via `assess_bca_access()` (user-assisted capture) or `assess_auto_trader_access()` (Connect API or manual route) with detailed rationale.
2. The system falls back to supported first-class import routes:
   - `ManualBcaImporter`: Ingests JSON/CSV catalogue exports, raw records, or saved HTML DOM files into `AuctionLot` records via `BcaAcquisition`.
   - `ManualAutoTraderImporter`: Ingests JSON/CSV market snapshot feeds, raw records, or saved HTML DOM files into `MarketSnapshot` via `AutoTraderAcquisition`.
   - `tools/bca_headed_fetch.py`: User-assisted capture command (configurable result limit and movement delay) that saves never-overwritten captures for BCA search results.
   - `tools/autotrader_headed_fetch.py`: User-assisted unauthenticated capture command (configurable result limit and movement delay) that saves never-overwritten captures for Auto Trader search results.
3. This guarantees compliant, verified operation without compromising account security or violating third-party terms.
