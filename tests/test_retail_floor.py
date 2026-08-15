from dataclasses import replace

from car_flip_search import (
    AdvertisedPrice,
    AuctionLot,
    AuctionLotId,
    AutoTraderListing,
    AutoTraderListingId,
    CapCleanPrice,
    CashPrice,
    CoreVehicleIdentity,
    HighMileageReference,
    MarketSnapshot,
    NoComparableEvidence,
    NoRetailFloorEvidence,
    OpportunitySearch,
    PriceSpread,
    RetailFloor,
    RetailFloorEvidence,
    RetailFloorSpread,
    SellerType,
)

A180D_IDENTITY = CoreVehicleIdentity(
    make="Mercedes-Benz",
    model_variant="A180d",
    registration_year=2020,
    fuel_type="Diesel",
    transmission="Automatic",
    body_style="Hatchback",
    door_count=5,
)

BASE_LOT = AuctionLot(
    id=AuctionLotId("bca-1"),
    identity=A180D_IDENTITY,
    mileage=40_000,
    cap_clean_price=CapCleanPrice(10_000),
    trim=None,
)

BASE_LISTING = AutoTraderListing(
    id=AutoTraderListingId("at-1"),
    identity=A180D_IDENTITY,
    mileage=40_000,
    cash_price=CashPrice(12_500),
    seller_type=SellerType.DEALER,
    trim=None,
)


def listing(*, id: str, mileage: int, cash_price: int) -> AutoTraderListing:
    return replace(
        BASE_LISTING,
        id=AutoTraderListingId(id),
        mileage=mileage,
        cash_price=CashPrice(cash_price),
    )


def test_listing_above_the_mileage_band_is_a_high_mileage_reference_not_a_comparable() -> (
    None
):
    above = listing(id="at-high", mileage=55_001, cash_price=8_500)

    candidate = (
        OpportunitySearch().search([BASE_LOT], MarketSnapshot([above])).candidates[0]
    )

    assert candidate.comparable_supply == 0
    assert candidate.comparable_evidence == NoComparableEvidence()
    assert candidate.retail_floor_evidence == RetailFloorEvidence(
        (
            HighMileageReference(
                AutoTraderListingId("at-high"),
                A180D_IDENTITY,
                55_001,
                AdvertisedPrice(CashPrice(8_500)),
                SellerType.DEALER,
                None,
            ),
        )
    )


def test_upper_band_boundary_is_still_a_direct_comparable_not_a_reference() -> None:
    at_boundary = listing(id="at-boundary", mileage=55_000, cash_price=12_000)

    candidate = (
        OpportunitySearch()
        .search([BASE_LOT], MarketSnapshot([at_boundary]))
        .candidates[0]
    )

    assert candidate.comparable_supply == 1
    assert candidate.retail_floor_evidence == NoRetailFloorEvidence()


def test_listing_below_the_band_is_neither_comparable_nor_reference() -> None:
    below = listing(id="at-low", mileage=24_999, cash_price=9_000)

    candidate = (
        OpportunitySearch().search([BASE_LOT], MarketSnapshot([below])).candidates[0]
    )

    assert candidate.comparable_supply == 0
    assert candidate.comparable_evidence == NoComparableEvidence()
    assert candidate.retail_floor_evidence == NoRetailFloorEvidence()


def test_identity_mismatch_above_the_band_is_not_a_reference() -> None:
    other_variant = replace(
        listing(id="at-other", mileage=70_000, cash_price=8_000),
        identity=replace(A180D_IDENTITY, model_variant="A200d"),
    )

    candidate = (
        OpportunitySearch()
        .search([BASE_LOT], MarketSnapshot([other_variant]))
        .candidates[0]
    )

    assert candidate.comparable_supply == 0
    assert candidate.retail_floor_evidence == NoRetailFloorEvidence()


def test_retail_floor_is_the_minimum_high_mileage_reference_cash_price() -> None:
    first = listing(id="at-high-1", mileage=60_000, cash_price=9_000)
    second = listing(id="at-high-2", mileage=70_000, cash_price=8_500)

    candidate = (
        OpportunitySearch()
        .search([BASE_LOT], MarketSnapshot([first, second]))
        .candidates[0]
    )

    assert candidate.retail_floor == RetailFloor(8_500)
    assert candidate.retail_floor_evidence.retail_floor == RetailFloor(8_500)


def test_retail_floor_spread_is_retail_floor_minus_cap_clean_price() -> None:
    reference = listing(id="at-high", mileage=60_000, cash_price=8_500)

    candidate = (
        OpportunitySearch()
        .search([BASE_LOT], MarketSnapshot([reference]))
        .candidates[0]
    )

    assert candidate.retail_floor_spread == RetailFloorSpread(-1_500)


def test_retail_floor_evidence_appears_alongside_direct_evidence() -> None:
    comparable = listing(id="at-direct", mileage=40_000, cash_price=12_500)
    reference = listing(id="at-high", mileage=60_000, cash_price=8_500)

    candidate = (
        OpportunitySearch()
        .search([BASE_LOT], MarketSnapshot([comparable, reference]))
        .candidates[0]
    )

    assert candidate.comparable_supply == 1
    assert candidate.price_spread == PriceSpread(2_500)
    assert candidate.retail_floor == RetailFloor(8_500)
    assert candidate.retail_floor_spread == RetailFloorSpread(-1_500)
    assert candidate.comparable_evidence != NoComparableEvidence()
    assert candidate.retail_floor_evidence != NoRetailFloorEvidence()


def test_absent_retail_floor_evidence_is_represented_explicitly() -> None:
    comparable = listing(id="at-direct", mileage=40_000, cash_price=12_500)

    candidate = (
        OpportunitySearch()
        .search([BASE_LOT], MarketSnapshot([comparable]))
        .candidates[0]
    )

    assert candidate.retail_floor_evidence == NoRetailFloorEvidence()
    assert candidate.retail_floor == NoRetailFloorEvidence()
    assert candidate.retail_floor_spread == NoRetailFloorEvidence()


def test_high_mileage_reference_retains_source_details() -> None:
    reference = replace(
        listing(id="at-high", mileage=65_000, cash_price=7_995),
        seller_type=SellerType.PRIVATE,
        trim="AMG Line",
    )

    candidate = (
        OpportunitySearch()
        .search([BASE_LOT], MarketSnapshot([reference]))
        .candidates[0]
    )

    selected = candidate.retail_floor_evidence.high_mileage_references[0]
    assert selected.listing_id == AutoTraderListingId("at-high")
    assert selected.identity == A180D_IDENTITY
    assert selected.mileage == 65_000
    assert selected.advertised_price == AdvertisedPrice(CashPrice(7_995))
    assert selected.seller_type == SellerType.PRIVATE
    assert selected.trim == "AMG Line"


def test_references_and_comparables_are_kept_in_distinct_evidence() -> None:
    comparable = listing(id="at-direct", mileage=40_000, cash_price=12_500)
    reference = listing(id="at-high", mileage=60_000, cash_price=8_500)

    candidate = (
        OpportunitySearch()
        .search([BASE_LOT], MarketSnapshot([comparable, reference]))
        .candidates[0]
    )

    assert candidate.comparable_evidence.market_comparables[0].listing_id.value == (
        "at-direct"
    )
    assert (
        candidate.retail_floor_evidence.high_mileage_references[0].listing_id.value
        == "at-high"
    )
