# Car Flip Search

A Python library for identifying potential vehicle resale opportunities from
BCA Auction Lots and a live Auto Trader Market Snapshot.

## Usage

```python
from car_flip_search import OpportunitySearch

opportunities = OpportunitySearch().search(auction_lots, market_snapshot)
```

`auction_lots` is an iterable of `AuctionLot` values and `market_snapshot` is
a `MarketSnapshot`. The result is an `OpportunityList` of comparison-eligible
candidates and their valuation signals.

## Capturing BCA search results

The BCA capture command opens a visible browser with a fresh session, lets you
log in and run one search, then captures the search results for Opportunity
Search. It never sees or stores your BCA credentials.

```bash
uv run python tools/bca_headed_fetch.py --search-name "A-Class Petrol" --result-limit 5 --move-delay 60
```

Each run saves a never-overwritten capture (with the search name and a unique
capture ID) under `data/captures/bca/<capture_id>/`, keeping the original page
data, the valid parsed car records, and a skipped-car log. A zero movement
delay is rejected; a capture that stops early is still saved and usable.

## Capturing Auto Trader search results

The Auto Trader capture command opens a visible browser with a fresh session
and captures one search for Opportunity Search. Auto Trader does not require
login for this workflow, so no credentials are configured, requested, or
stored.

```bash
uv run python tools/autotrader_headed_fetch.py --search-name "A-Class Petrol" --result-limit 5 --move-delay 60
```

Auto Trader results load by infinite scroll, so the command moves through the
results in scroll batches up to the configurable result limit (default 5), at
a configurable non-zero move delay (default 60s), and stops early once two
consecutive movements produce no new listing IDs. Each run saves a
never-overwritten capture under `data/captures/autotrader/<capture_id>/` with
the same layout: original page data, valid parsed records, and a skipped-car
log. Cars are deduplicated by Auto Trader listing ID, keeping the latest
version. A capture that stops early is still saved and usable.

## Opportunity dashboard

After both captures are saved, start the local dashboard:

```bash
uv run dev
```

`uv run dashboard` is an alias. The app binds to `127.0.0.1:5000`, opens a
browser tab, and reads `data/captures/`. Use `--no-browser`, `--port`, or
`--data-root` when needed:

```bash
uv run dev --no-browser --port 5050 --data-root /path/to/captures
```

The dashboard defaults to the newest usable BCA and Auto Trader Captures. It
keeps an explicitly selected Capture Pair in the URL, shows all strict
Candidate Vehicles, and opens source pages in separate tabs for inspection.
Use Manage Captures to select and delete old saved Captures, including several
at once. Watchlisting remains on BCA.

## Development

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```
