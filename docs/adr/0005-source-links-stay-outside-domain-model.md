# Source Links stay outside the valuation model

Source Links are optional inspection metadata stored with raw Capture records and loaded into a separate dashboard mapping keyed by source kind and source ID. Core domain objects and evidence keep source IDs and valuation fields only, so the dashboard can open observed HTTPS source pages without making source transport details part of identity or calculation.

## Consequences

- Prefer BCA title links, then card links; use Auto Trader car-details links.
- Resolve relative URLs and accept only expected HTTPS host and path.
- Missing links do not remove the record; the dashboard never reconstructs or probes URLs.
- The dashboard opens links in a new tab and shows all retained evidence links in detail.
