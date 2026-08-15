from decimal import Decimal

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
    Money,
    NoComparableEvidence,
    OpportunityList,
    SellerType,
)


def test_money_rejects_float_non_iso_currency_and_more_than_two_fractional_digits() -> (
    None
):
    with pytest.raises(TypeError):
        Money(10000.0, "GBP")
    with pytest.raises(ValueError):
        Money(Decimal("10000.00"), "gbp")
    with pytest.raises(ValueError):
        Money(Decimal("10000.001"), "GBP")
    with pytest.raises(ValueError):
        Money(Decimal("NaN"), "GBP")


def test_money_preserves_a_sensible_trailing_zero_scale() -> None:
    assert Money(Decimal("10000.000"), "GBP") == Money(Decimal("10000.00"), "GBP")


def test_source_ids_reject_whitespace_only_values() -> None:
    with pytest.raises(ValueError):
        AuctionLotId("  ")
    with pytest.raises(ValueError):
        AutoTraderListingId("\t")


def test_auction_lot_rejects_auto_trader_listing_id() -> None:
    identity = CoreVehicleIdentity(
        "Ford", "Focus", 2021, "Petrol", "Manual", "Hatchback", 5
    )

    with pytest.raises(TypeError):
        AuctionLot(
            AutoTraderListingId("at-456"),
            identity,
            41_000,
            CapCleanPrice(Money(Decimal("10000.00"), "GBP")),
        )


def test_market_snapshot_rejects_duplicate_auto_trader_listing_ids() -> None:
    identity = CoreVehicleIdentity(
        "Ford", "Focus", 2021, "Petrol", "Manual", "Hatchback", 5
    )
    listing = AutoTraderListing(
        AutoTraderListingId("at-456"),
        identity,
        40_000,
        CashPrice(Money(Decimal("12500.00"), "GBP")),
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
        AdvertisedPrice(CashPrice(Money(Decimal("12500.00"), "GBP"))),
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
        CapCleanPrice(Money(Decimal("10000.00"), "GBP")),
    )

    with pytest.raises(ValueError, match="duplicate"):
        OpportunityList([CandidateVehicle(lot, NoComparableEvidence())] * 2)


def test_source_prices_reject_negative_money() -> None:
    with pytest.raises(ValueError):
        CashPrice(Money(Decimal("-1.00"), "GBP"))
    with pytest.raises(ValueError):
        CapCleanPrice(Money(Decimal("-1.00"), "GBP"))
