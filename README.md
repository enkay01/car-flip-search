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
uv run python tools/bca_headed_fetch.py --search-name "A-Class Petrol" --page-limit 5 --page-delay 60
```

Each run saves a never-overwritten capture (with the search name and a unique
capture ID) under `data/captures/bca/<capture_id>/`, keeping the original page
data, the valid parsed car records, and a skipped-car log. A zero page delay is
rejected; a capture that stops early is still saved and usable.

## Development

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```
