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
   - **BCA**: User-assisted headed browser capture only (`tools/bca_headed_fetch.py`),
     or saved HTML pages imported through `ManualBcaImporter`. The BCA API-key
     credential path was removed (#8): the tool opens a fresh visible session
     per run, never receives or stores BCA credentials or sessions, and the
     user performs their own login and search.
   - **Auto Trader**: Auto Trader Connect Developer API (OAuth2 client
     credentials / API key) for registered partners, or user-assisted headed browser
     DOM capture / saved HTML pages / manual market snapshot feeds.
   - **Strict No-Evasion Rule**: Unauthorized headless scraping against bot
     defenses, CAPTCHA solving, and proxy rotation are explicitly prohibited.

2. **Headed Browser Capture Workflow (BCA)**:
   - Data is acquired through a single user-assisted capture run
     (`tools/bca_headed_fetch.py`). The user supplies a search name; the command
     opens a visible browser with a fresh session, the user logs in and runs one
     search, and the command captures up to a configurable page limit (default 5)
     at a configurable non-zero delay between page movements (default 60 seconds).
   - **Capture Storage**: Each run saves a capture directory under
     `data/captures/bca/<capture_id>/` that is never overwritten: the original
     page data (`pages/`), the valid parsed car records (`cars.json`), and a
     skipped-car log (`skipped.json`) with every skip reason. Cars are
     deduplicated by BCA lot ID, keeping the latest captured version.
   - **Strict Pacing**: Configurable page delay; the default is 60 seconds
     (max 1 page per minute) and a zero delay is rejected.
   - **Bounded Scope**: Maximum 5 search result pages per run by default.
   - **Local Offline Parsing**: Captured pages are parsed locally by the
     observation layer (`observe_bca_cards` / `validate_bca_observation`); no
     value for condition, identity, mileage, or CAP Clean Price is ever invented.

3. **Hard Stops and Account Safety**:
   - Immediate hard stop on authentication challenges and login expiry: the
     user is told to log in again, but the capture never retries or bypasses.
   - Immediate hard stop on anti-bot or CAPTCHA challenge detection (Cloudflare,
     Akamai, reCAPTCHA, hCaptcha, PerimeterX).
   - Immediate hard stop on repeated throttling after Retry-After-aware backoff
     exhaustion.
   - A stopped capture still saves everything captured so far; it is not an error.

4. **Cadence, Caching, and Deduplication**:
   - Low concurrency (single-worker bounded cadence).
   - Conservative request pacing (1 request per second for direct BCA API is
     obsolete; browser capture uses a configurable page delay; max 5 req/s for
     Auto Trader API).
   - In-memory response caching and ID deduplication to prevent redundant
     source queries (Auto Trader); captures deduplicate by BCA lot ID.

5. **Credential Isolation and Revocation**:
   - BCA has no credential objects in the application: the user's username and
     password stay with the user and in the browser session only, and every
     capture starts from a fresh browser context.
   - Auto Trader credentials (`AutoTraderCredentials`) exist strictly within the
     source access boundary and are masked in string representations to prevent
     logging or leakage.
   - Domain models (`AuctionLot`, `AutoTraderListing`, `MarketSnapshot`,
     `OpportunityList`) remain free of transport, authentication, or session fields.
   - Explicit credential revocation and clearance methods are provided
     (`credentials.revoke()`) for Auto Trader.

6. **No-Go Constraint and Supported Import Fallback**:
   - When an automated path is challenged, the system records an explicit
     decision and stops without bypass.
   - Structured import paths (`ManualBcaImporter` and `ManualAutoTraderImporter`)
     are preserved as supported first-class acquisition routes for JSON, CSV, and
     saved HTML DOM files.
