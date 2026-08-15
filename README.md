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

## Development

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```
