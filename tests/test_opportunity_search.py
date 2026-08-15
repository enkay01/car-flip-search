from decimal import Decimal

import pytest

from car_flip_search import (
    AdvertisedPrice,
    AuctionLot,
    AuctionLotId,
    AutoTraderListing,
    AutoTraderListingId,
    Candidate,
    CapCleanPrice,
    CashPrice,
    ComparableEvidence,
    CoreVehicleIdentity,
    MarketComparable,
    MarketSnapshot,
    Money,
    NoComparableEvidence,
    OpportunityList,
    OpportunitySearch,
    PriceSpread,
    SellerType,
)


def test_comparison_eligible_candidate_has_comparable_supply_and_price_spread() -> None:
    identity = CoreVehicleIdentity(
        make="Mercedes-Benz",
        model_variant="A180d",
        registration_year=2020,
        fuel_type="Diesel",
        transmission="Automatic",
        body_style="Hatchback",
        door_count=5,
    )
    auction_lot = AuctionLot(
        id=AuctionLotId("bca-123"),
        identity=identity,
        mileage=41_000,
        cap_clean_price=CapCleanPrice(Money(Decimal("10000.00"), "GBP")),
    )
    listing = AutoTraderListing(
        id=AutoTraderListingId("at-456"),
        identity=identity,
        mileage=40_000,
        cash_price=CashPrice(Money(Decimal("12500.00"), "GBP")),
        seller_type=SellerType.DEALER,
    )

    opportunities = OpportunitySearch().search([auction_lot], MarketSnapshot([listing]))

    assert opportunities == OpportunityList(
        (
            Candidate(
                auction_lot,
                ComparableEvidence(
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
                ),
            ),
        )
    )
    assert opportunities.candidates[0].comparable_supply == 1
    assert opportunities.candidates[0].price_spread == PriceSpread(
        Money(Decimal("2500.00"), "GBP")
    )


def test_candidate_vehicle_with_non_gbp_cash_price_has_no_comparable_evidence() -> None:
    identity = CoreVehicleIdentity(
        "Ford", "Focus", 2021, "Petrol", "Manual", "Hatchback", 5
    )
    auction_lot = AuctionLot(
        AuctionLotId("bca-123"),
        identity,
        41_000,
        CapCleanPrice(Money(Decimal("10000.00"), "GBP")),
    )
    listing = AutoTraderListing(
        AutoTraderListingId("at-456"),
        identity,
        40_000,
        CashPrice(Money(Decimal("12500.00"), "EUR")),
        SellerType.PRIVATE,
    )

    opportunities = OpportunitySearch().search([auction_lot], MarketSnapshot([listing]))

    candidate = opportunities.candidates[0]
    assert candidate.comparable_evidence == NoComparableEvidence()
    assert candidate.comparable_supply == 0
    assert candidate.price_spread == NoComparableEvidence()


def test_opportunity_search_rejects_zero_auction_lots_and_listings() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        OpportunitySearch().search([], MarketSnapshot([]))


def test_opportunity_search_rejects_multiple_auction_lots() -> None:
    identity = CoreVehicleIdentity(
        "Ford", "Focus", 2021, "Petrol", "Manual", "Hatchback", 5
    )
    lot = AuctionLot(
        AuctionLotId("bca-123"),
        identity,
        41_000,
        CapCleanPrice(Money(Decimal("10000.00"), "GBP")),
    )
    listing = AutoTraderListing(
        AutoTraderListingId("at-456"),
        identity,
        40_000,
        CashPrice(Money(Decimal("12500.00"), "GBP")),
        SellerType.PRIVATE,
    )

    with pytest.raises(ValueError, match="exactly one"):
        OpportunitySearch().search([lot, lot], MarketSnapshot([listing]))


def test_opportunity_search_rejects_multiple_auto_trader_listings() -> None:
    identity = CoreVehicleIdentity(
        "Ford", "Focus", 2021, "Petrol", "Manual", "Hatchback", 5
    )
    lot = AuctionLot(
        AuctionLotId("bca-123"),
        identity,
        41_000,
        CapCleanPrice(Money(Decimal("10000.00"), "GBP")),
    )
    listing = AutoTraderListing(
        AutoTraderListingId("at-456"),
        identity,
        40_000,
        CashPrice(Money(Decimal("12500.00"), "GBP")),
        SellerType.PRIVATE,
    )
    another_listing = AutoTraderListing(
        AutoTraderListingId("at-789"),
        identity,
        40_000,
        CashPrice(Money(Decimal("12600.00"), "GBP")),
        SellerType.PRIVATE,
    )

    with pytest.raises(ValueError, match="exactly one"):
        OpportunitySearch().search([lot], MarketSnapshot([listing, another_listing]))


def test_comparison_eligible_candidate_can_have_a_negative_price_spread() -> None:
    identity = CoreVehicleIdentity(
        "Ford", "Focus", 2021, "Petrol", "Manual", "Hatchback", 5
    )
    lot = AuctionLot(
        AuctionLotId("bca-123"),
        identity,
        41_000,
        CapCleanPrice(Money(Decimal("14000.00"), "GBP")),
    )
    listing = AutoTraderListing(
        AutoTraderListingId("at-456"),
        identity,
        40_000,
        CashPrice(Money(Decimal("12500.00"), "GBP")),
        SellerType.PRIVATE,
    )

    opportunity_list = OpportunitySearch().search([lot], MarketSnapshot([listing]))

    assert opportunity_list.candidates[0].price_spread == PriceSpread(
        Money(Decimal("-1500.00"), "GBP")
    )
