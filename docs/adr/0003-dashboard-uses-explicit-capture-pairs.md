# Dashboard uses explicit Capture Pairs

The dashboard builds an Opportunity List from one BCA Capture and one Auto Trader Capture, identified by both Capture IDs. It defaults to the newest structurally valid Capture per source using the manifest `saved_at`, preserves an explicit pair across reload, and allows empty or stopped Captures with visible status. It never silently substitutes older data or mixes records between Captures, because freshness and evidence provenance matter more than hiding an incomplete source result.

## Consequences

- Search Name differences warn the user but do not block a manually selected pair.
- Malformed manifests, invalid timestamps, source mismatches, and unreadable records are unavailable for selection.
- A missing selected Capture is replaced only for that source, and the changed pair is shown to the user.
- The dashboard keeps manifest counts separate from records that pass the acquisition boundary.
