# Permitted account-backed source access and manual fallback

## Context

Car Flip Search compares BCA auction lots with live UK Auto Trader listings.
Both sources require account authorization and enforce strict usage terms and
technical controls (such as rate limits, WAFs, and anti-bot verification).
Automated ingestion must remain compliant, account-safe, and verifiable without
attempting to bypass CAPTCHA, web application firewalls, or bot mitigation
systems.

## Decision

1. **Permitted Access Mechanisms**:
   - **BCA**: Supported B2B / Partner API, authenticated trade catalogue export
     feeds (JSON/CSV), or user-assisted headed browser DOM capture / saved HTML
     pages.
   - **Auto Trader**: Auto Trader Connect Developer API (OAuth2 client
     credentials / API key) for registered partners, or manual market snapshot
     feeds.
   - **Strict No-Evasion Rule**: Unauthorized headless scraping against bot
     defenses, CAPTCHA solving, and proxy rotation are explicitly prohibited.

2. **Headed Browser Capture Workflow (BCA API Alternative)**:
   - When direct APIs are unavailable, data is acquired via user-controlled
     headed browser sessions (`tools/bca_headed_fetch.py`) or saved HTML pages.
   - **Strict Pacing**: Maximum 1 page per minute (60-second delay between
     page navigations).
   - **Bounded Scope**: Maximum 5 search results pages per run.
   - **Local Parsing**: The full page DOM is saved locally to disk and parsed
     offline by `ManualBcaImporter.import_from_html`.

3. **Hard Stops and Account Safety**:
   - Immediate hard stop on authentication challenges (HTTP 401 / 403).
   - Immediate hard stop on anti-bot or CAPTCHA challenge detection.
   - Immediate hard stop on repeated throttling after Retry-After-aware backoff
     exhaustion.

4. **Cadence, Caching, and Deduplication**:
   - Low concurrency (single-worker bounded cadence).
   - Conservative request pacing (e.g., 1 request per second for direct API;
     1 page per minute for browser capture; max 5 req/s for Auto Trader).
   - In-memory response caching and ID deduplication to prevent redundant
     source queries.

5. **Credential Isolation and Revocation**:
   - Credentials exist strictly within the source access boundary and are
     masked in string representations to prevent logging or leakage.
   - Domain models (`AuctionLot`, `AutoTraderListing`, `OpportunityList`)
     remain free of transport, authentication, or session fields.
   - Explicit credential revocation and clearance methods are provided.

6. **No-Go Constraint and Manual Import Fallback**:
   - When approved API credentials are not provisioned or when an automated path
     is challenged, the system records an explicit `NO_GO_MANUAL_REQUIRED`
     decision.
   - Structured manual import paths (`ManualBcaImporter` and
     `ManualAutoTraderImporter`) are provided and preserved as supported first-class
     acquisition routes for JSON, CSV, and saved HTML DOM files.
