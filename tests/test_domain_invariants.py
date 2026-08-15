import pytest

from car_flip_search import (
    AdvertisedPrice,
    AuctionLot,
    AuctionLotId,
    AutoTraderListing,
    AutoTraderListingId,
    CandidateVehicle,
    CapCleanPrice,
    CashPrice,
    ComparableEvidence,
    CoreVehicleIdentity,
    MarketComparable,
    MarketSnapshot,
    NoComparableEvidence,
    OpportunityList,
    SellerType,
)


def test_source_ids_reject_whitespace_only_values() -> None:
    with pytest.raises(ValueError):
        AuctionLotId("  ")
    with pytest.raises(ValueError):
        AutoTraderListingId("\t")


def test_market_snapshot_rejects_duplicate_auto_trader_listing_ids() -> None:
    identity = CoreVehicleIdentity(
        "Ford", "Focus", 2021, "Petrol", "Manual", "Hatchback", 5
    )
    listing = AutoTraderListing(
        AutoTraderListingId("at-456"),
        identity,
        40_000,
        CashPrice(12_500),
        SellerType.DEALER,
    )

    with pytest.raises(ValueError, match="duplicate"):
        MarketSnapshot([listing, listing])


def test_comparable_evidence_rejects_duplicate_auto_trader_listing_ids() -> None:
    identity = CoreVehicleIdentity(
        "Ford", "Focus", 2021, "Petrol", "Manual", "Hatchback", 5
    )
    comparable = MarketComparable(
        AutoTraderListingId("at-456"),
        identity,
        40_000,
        AdvertisedPrice(CashPrice(12_500)),
        SellerType.DEALER,
        None,
    )

    with pytest.raises(ValueError, match="duplicate"):
        ComparableEvidence((comparable, comparable))


def test_opportunity_list_rejects_duplicate_auction_lot_ids() -> None:
    identity = CoreVehicleIdentity(
        "Ford", "Focus", 2021, "Petrol", "Manual", "Hatchback", 5
    )
    lot = AuctionLot(
        AuctionLotId("bca-123"),
        identity,
        41_000,
        CapCleanPrice(10_000),
    )

    with pytest.raises(ValueError, match="duplicate"):
        OpportunityList([CandidateVehicle(lot, NoComparableEvidence())] * 2)


def test_source_prices_reject_negative_whole_pound_amounts() -> None:
    with pytest.raises(ValueError):
        CashPrice(-1)
    with pytest.raises(ValueError):
        CapCleanPrice(-1)
