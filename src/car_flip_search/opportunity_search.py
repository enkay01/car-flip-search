"""The public opportunity-search seam."""

from collections.abc import Iterable

from .model import (
    AdvertisedPrice,
    AuctionLot,
    AutoTraderListing,
    CandidateVehicle,
    ComparableEvidence,
    MarketComparable,
    MarketSnapshot,
    NoComparableEvidence,
    OpportunityList,
)

MILEAGE_BAND_MILES = 15_000


class OpportunitySearch:
    def search(
        self,
        auction_lots: Iterable[AuctionLot],
        market_snapshot: MarketSnapshot,
    ) -> OpportunityList:
        return OpportunityList(
            tuple(
                CandidateVehicle(
                    auction_lot,
                    _select_evidence(auction_lot, market_snapshot),
                )
                for auction_lot in auction_lots
            )
        )


def _select_evidence(
    auction_lot: AuctionLot,
    market_snapshot: MarketSnapshot,
) -> ComparableEvidence | NoComparableEvidence:
    comparables = tuple(
        _to_market_comparable(auction_lot, listing)
        for listing in market_snapshot.listings
        if _is_market_comparable(auction_lot, listing)
    )
    if not comparables:
        return NoComparableEvidence()
    return ComparableEvidence(comparables)


def _to_market_comparable(
    auction_lot: AuctionLot,
    listing: AutoTraderListing,
) -> MarketComparable:
    return MarketComparable(
        listing_id=listing.id,
        identity=listing.identity,
        mileage=listing.mileage,
        advertised_price=AdvertisedPrice(listing.cash_price),
        seller_type=listing.seller_type,
        trim=listing.trim,
        trim_match=_is_trim_match(auction_lot, listing),
    )


def _is_market_comparable(
    auction_lot: AuctionLot,
    listing: AutoTraderListing,
) -> bool:
    return (
        listing.identity == auction_lot.identity
        and abs(listing.mileage - auction_lot.mileage) <= MILEAGE_BAND_MILES
    )


def _is_trim_match(
    auction_lot: AuctionLot,
    listing: AutoTraderListing,
) -> bool:
    return auction_lot.trim is not None and listing.trim == auction_lot.trim
