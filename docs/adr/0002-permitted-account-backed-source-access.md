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
   - **BCA**: Supported B2B / Partner API (REST with API key / OAuth token) or
     authenticated trade catalogue export feeds (JSON/CSV) via trade buyer
     accounts.
   - **Auto Trader**: Auto Trader Connect Developer API (OAuth2 client
     credentials / API key) for registered partners.
   - **Strict No-Evasion Rule**: Unauthorized web scraping, headless browser
     automation against consumer login walls, CAPTCHA solving, and proxy
     rotation are explicitly prohibited.

2. **Hard Stops and Account Safety**:
   - Immediate hard stop on authentication challenges (HTTP 401 / 403).
   - Immediate hard stop on anti-bot or CAPTCHA challenge detection.
   - Immediate hard stop on repeated throttling after Retry-After-aware backoff
     exhaustion.
   - No evasion or retry loops when an access restriction is encountered.

3. **Cadence, Caching, and Deduplication**:
   - Low concurrency (single-worker bounded cadence).
   - Conservative request pacing (e.g., 1 request per second for BCA; max 5
     requests per second for Auto Trader).
   - In-memory response caching and ID deduplication to prevent redundant
     source queries.
   - Retry-After-aware exponential backoff with jitter for transient 429
     responses.

4. **Credential Isolation and Revocation**:
   - Credentials exist strictly within the source access boundary and are
     masked in string representations to prevent logging or leakage.
   - Domain models (`AuctionLot`, `AutoTraderListing`, `OpportunityList`)
     remain free of transport, authentication, or session fields.
   - Explicit credential revocation and clearance methods are provided.

5. **No-Go Constraint and Manual Import Fallback**:
   - When approved API credentials are not provisioned or when an automated path
     is challenged, the system records an explicit `NO_GO_MANUAL_REQUIRED`
     decision.
   - Structured manual import paths (`ManualBcaImporter` and
     `ManualAutoTraderImporter`) are provided and preserved as supported first-class
     acquisition routes.
