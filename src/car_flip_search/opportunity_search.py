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
        immutable_auction_lots = tuple(auction_lots)
        if len(immutable_auction_lots) != 1 or len(market_snapshot.listings) != 1:
            raise ValueError(
                "Opportunity Search supports exactly one Auction Lot and one "
                "Auto Trader Listing"
            )
        auction_lot = immutable_auction_lots[0]
        listing = market_snapshot.listings[0]
        if not _is_market_comparable(auction_lot, listing):
            evidence: ComparableEvidence | NoComparableEvidence = NoComparableEvidence()
        else:
            evidence = ComparableEvidence(
                (
                    MarketComparable(
                        listing.id,
                        listing.identity,
                        listing.mileage,
                        AdvertisedPrice(listing.cash_price),
                        listing.seller_type,
                        listing.trim,
                    ),
                )
            )
        return OpportunityList((CandidateVehicle(auction_lot, evidence),))


def _is_market_comparable(
    auction_lot: AuctionLot,
    listing: AutoTraderListing,
) -> bool:
    return (
        listing.cash_price.money.currency == "GBP"
        and listing.identity == auction_lot.identity
        and abs(listing.mileage - auction_lot.mileage) <= MILEAGE_BAND_MILES
    )
