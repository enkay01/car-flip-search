# Permitted Source Access Specification

This document details the permitted access mechanisms, account permissions, usage constraints, rate limits, credential handling, backoff policies, hard stop mechanisms, and manual import routes for BCA and Auto Trader.

## 1. Source Access Overview

| Source | Approved Access Mechanism | Required Permissions | Usage Constraints | Rate Limit / Cadence |
|---|---|---|---|---|
| **BCA** | Partner REST API / Trade Portal Catalogue Feed (JSON/CSV) | Registered BCA Trade Buyer Account (`Catalog:Read`, `Valuation:Read`) | Read-only lot inspection with CAP Clean Price; no consumer scraping or anti-bot bypass | Conservative cadence (1 req/s, max concurrency = 1); adhere to `Retry-After` |
| **Auto Trader** | Auto Trader Connect Developer API (REST / OAuth2) | Registered Auto Trader Developer / Commercial Partner Account (`Stock:Read`, `Search:Read`) | Live UK Cash Price listings only; strictly no scraping of consumer website or CAPTCHA bypass | Max 5 req/s; adhere to `Retry-After` on HTTP 429 |

---

## 2. BCA (British Car Auctions)

### Permitted Access Mechanisms
- **BCA Partner API**: Authenticated HTTPS REST endpoints providing vehicle catalogue and auction lot data using an API key or Bearer token.
- **BCA Trade Portal Export**: Authenticated catalogue data exports (JSON/CSV) generated through a verified BCA Trade Buyer account.

### Account Permissions
- Registered BCA Trade / Buyer account with active permissions to browse auction catalogues and view CAP valuation benchmarks.

### Usage Constraints
- Automated access is permitted only via approved API endpoints or verified export feeds.
- Scraping of BCA web portals protected by Cloudflare, WAFs, or CAPTCHA challenges is strictly forbidden.
- Acquired records must be filtered to condition-eligible lots (clean condition, no reported write-off or accident damage) with whole-pound CAP Clean Prices.

### Rate Limits and Cadence
- **Cadence**: Conservative pacing of 1 request per second.
- **Concurrency**: Bounded to single-worker concurrency (`concurrency = 1`).
- **Throttling**: Respect HTTP 429 and `Retry-After` headers. Maximum 3 retry attempts before hard stop.

---

## 3. Auto Trader

### Permitted Access Mechanisms
- **Auto Trader Connect API**: Official Developer Platform REST API using OAuth2 client credentials (`client_id`, `client_secret`) or assigned API keys.
- **Market Snapshot Manual Feed**: Structured JSON/CSV export files loaded directly into the market input boundary.

### Account Permissions
- Commercial partner or approved developer credentials with vehicle search and stock read scopes.

### Usage Constraints
- Auto Trader terms of use strictly prohibit scraping public consumer search pages, bypassing Akamai Bot Manager, solving CAPTCHAs, or rotating proxies.
- Only live UK advertised listings with Cash Price are ingested. Finance illustrations, leasing estimates, and historical sales are excluded.

### Rate Limits and Cadence
- **Cadence**: Bounded rate limit of up to 5 requests per second.
- **Concurrency**: Bounded concurrency (`concurrency = 1` for refresh runs).
- **Throttling**: Respect HTTP 429 and `Retry-After` headers. Maximum 3 retry attempts before hard stop.

---

## 4. Credential Isolation and Revocation

### Isolation
- Credential objects (`BcaCredentials`, `AutoTraderCredentials`) are encapsulated inside the source access layer.
- `__repr__` and `__str__` implementations mask secret values (e.g. `api_key="***"`) so that tokens cannot appear in application logs, error traces, or diagnostic dumps.
- Domain models (`AuctionLot`, `AutoTraderListing`, `MarketSnapshot`, `CandidateVehicle`, `OpportunityList`) contain zero authentication or transport state.

### Revocation Procedure
- **BCA**: Invalidate API keys via the BCA partner developer portal or change trade portal passwords. In application memory, call `credentials.revoke()` to clear active tokens immediately.
- **Auto Trader**: Rotate `client_secret` or revoke API tokens via the Auto Trader Developer Portal. In application memory, call `credentials.revoke()` to clear stored secrets and cached bearer tokens.

---

## 5. Resilience, Backoff, and Hard Stops

### Cadence, Caching, and Deduplication
- **Cadence**: Pacing enforced before sending each HTTP request.
- **Caching**: In-memory response cache with key/TTL support to avoid repeated queries for unchanged lots or listings during a run.
- **Deduplication**: Source IDs (`AuctionLotId`, `AutoTraderListingId`) are deduplicated prior to emission.

### Retry-After-Aware Exponential Backoff
- When encountering a transient HTTP 429 (Too Many Requests), the client checks for a `Retry-After` header (seconds or HTTP date).
- If present, the client pauses for the duration specified.
- If absent, exponential backoff with jitter is applied: `delay = min(max_delay, base_delay * 2^attempt) + jitter`.
- Retries are bounded to a maximum of 3 attempts.

### Hard Stops (No Evasion)
The system executes an immediate hard stop without retrying, rotating proxies, or attempting evasion in any of the following scenarios:
1. **Authentication Challenge (HTTP 401 / 403)**: Invalid, expired, or missing credentials.
2. **Anti-Bot / CAPTCHA Detection**: Response body or headers indicate a Cloudflare, Akamai, or CAPTCHA challenge.
3. **Repeated Throttling**: Exceeding the maximum retry count on HTTP 429 responses.

---

## 6. No-Go Decision and Manual Import Route

When automated API access is not permitted (e.g., missing API credentials, unapproved account type, or presence of bot challenges):
1. The access layer records a clear `NO_GO_MANUAL_REQUIRED` access decision with detailed rationale.
2. The system falls back to supported manual import routes:
   - `ManualBcaImporter`: Ingests JSON/CSV catalogue exports into `AuctionLot` records via `BcaAcquisition`.
   - `ManualAutoTraderImporter`: Ingests JSON/CSV market snapshot feeds into `MarketSnapshot` via `AutoTraderAcquisition`.
3. This guarantees compliant, verified operation without compromising account security or violating third-party terms.
