from dataclasses import replace

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
    OpportunitySearch,
    PriceSpread,
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

BASE_LISTING = AutoTraderListing(
    id=AutoTraderListingId("at-1"),
    identity=A180D_IDENTITY,
    mileage=40_000,
    cash_price=CashPrice(12_500),
    seller_type=SellerType.DEALER,
    trim=None,
)

BASE_LOT = AuctionLot(
    id=AuctionLotId("bca-1"),
    identity=A180D_IDENTITY,
    mileage=40_000,
    cap_clean_price=CapCleanPrice(10_000),
    trim=None,
)


def test_matching_listing_is_selected_as_a_market_comparable() -> None:
    listing = BASE_LISTING

    opportunities = OpportunitySearch().search([BASE_LOT], MarketSnapshot([listing]))

    assert opportunities == OpportunityList(
        (
            CandidateVehicle(
                BASE_LOT,
                ComparableEvidence(
                    (
                        MarketComparable(
                            listing.id,
                            listing.identity,
                            listing.mileage,
                            AdvertisedPrice(listing.cash_price),
                            listing.seller_type,
                            listing.trim,
                            False,
                        ),
                    )
                ),
            ),
        )
    )
    assert opportunities.candidates[0].comparable_supply == 1
    assert opportunities.candidates[0].price_spread == PriceSpread(2_500)


@pytest.mark.parametrize(
    ("field", "changed_value"),
    [
        ("make", "Audi"),
        ("model_variant", "A200d"),
        ("registration_year", 2019),
        ("fuel_type", "Petrol"),
        ("transmission", "Manual"),
        ("body_style", "Saloon"),
        ("door_count", 3),
    ],
)
def test_a_single_identity_field_mismatch_excludes_the_listing(
    field: str, changed_value: str | int
) -> None:
    listing = replace(
        BASE_LISTING,
        identity=replace(A180D_IDENTITY, **{field: changed_value}),
    )

    opportunities = OpportunitySearch().search([BASE_LOT], MarketSnapshot([listing]))

    assert opportunities.candidates[0].comparable_evidence == NoComparableEvidence()


@pytest.mark.parametrize(
    ("listing_mileage", "expected_comparable_supply"),
    [(25_000, 1), (24_999, 0), (55_000, 1), (55_001, 0)],
)
def test_market_comparable_respects_the_mileage_band_boundary(
    listing_mileage: int, expected_comparable_supply: int
) -> None:
    listing = replace(BASE_LISTING, mileage=listing_mileage)

    opportunities = OpportunitySearch().search([BASE_LOT], MarketSnapshot([listing]))

    assert opportunities.candidates[0].comparable_supply == expected_comparable_supply


def test_a_non_matching_trim_still_qualifies_as_a_market_comparable() -> None:
    lot = replace(BASE_LOT, trim="M Sport")
    listing = replace(BASE_LISTING, trim="SE")

    opportunities = OpportunitySearch().search([lot], MarketSnapshot([listing]))

    comparable = opportunities.candidates[0].comparable_evidence.market_comparables[0]
    assert opportunities.candidates[0].comparable_supply == 1
    assert comparable.trim_match is False


def test_trim_matches_appear_first_for_inspection() -> None:
    lot = replace(BASE_LOT, trim="M Sport")
    non_matching_trim_listing = replace(
        BASE_LISTING,
        id=AutoTraderListingId("at-1"),
        trim="SE",
        cash_price=CashPrice(11_000),
    )
    matching_trim_listing = replace(
        BASE_LISTING,
        id=AutoTraderListingId("at-2"),
        trim="M Sport",
        cash_price=CashPrice(13_000),
    )

    opportunities = OpportunitySearch().search(
        [lot], MarketSnapshot([non_matching_trim_listing, matching_trim_listing])
    )

    comparables = opportunities.candidates[0].comparable_evidence.market_comparables
    assert [item.listing_id.value for item in comparables] == ["at-2", "at-1"]
    assert [item.trim_match for item in comparables] == [True, False]


def test_both_seller_types_are_selected_as_market_comparables() -> None:
    dealer = replace(
        BASE_LISTING,
        id=AutoTraderListingId("at-dealer"),
        seller_type=SellerType.DEALER,
    )
    private = replace(
        BASE_LISTING,
        id=AutoTraderListingId("at-private"),
        seller_type=SellerType.PRIVATE,
    )

    opportunities = OpportunitySearch().search(
        [BASE_LOT], MarketSnapshot([dealer, private])
    )

    assert opportunities.candidates[0].comparable_supply == 2
    seller_types = {
        item.seller_type
        for item in opportunities.candidates[0].comparable_evidence.market_comparables
    }
    assert seller_types == {SellerType.DEALER, SellerType.PRIVATE}


def test_comparable_supply_and_lowest_advertised_price_cover_the_complete_set() -> None:
    lot = replace(BASE_LOT, trim="M Sport")
    first = replace(
        BASE_LISTING,
        id=AutoTraderListingId("at-1"),
        trim="M Sport",
        cash_price=CashPrice(13_000),
    )
    second = replace(
        BASE_LISTING,
        id=AutoTraderListingId("at-2"),
        trim="SE",
        cash_price=CashPrice(12_000),
    )
    third = replace(
        BASE_LISTING,
        id=AutoTraderListingId("at-3"),
        trim=None,
        cash_price=CashPrice(12_750),
    )

    opportunities = OpportunitySearch().search(
        [lot], MarketSnapshot([first, second, third])
    )

    candidate = opportunities.candidates[0]
    assert candidate.comparable_supply == 3
    assert candidate.comparable_evidence.advertised_price == AdvertisedPrice(
        CashPrice(12_000)
    )
    assert candidate.price_spread == PriceSpread(2_000)
    assert [
        item.listing_id.value
        for item in candidate.comparable_evidence.market_comparables
    ] == ["at-1", "at-2", "at-3"]


def test_non_comparable_listings_are_excluded_from_the_selected_set() -> None:
    matching = replace(
        BASE_LISTING,
        id=AutoTraderListingId("at-match"),
        cash_price=CashPrice(12_000),
    )
    different_variant = replace(
        BASE_LISTING,
        id=AutoTraderListingId("at-variant"),
        identity=replace(A180D_IDENTITY, model_variant="A200d"),
    )
    too_far = replace(
        BASE_LISTING,
        id=AutoTraderListingId("at-far"),
        mileage=55_001,
    )

    opportunities = OpportunitySearch().search(
        [BASE_LOT], MarketSnapshot([matching, different_variant, too_far])
    )

    candidate = opportunities.candidates[0]
    assert candidate.comparable_supply == 1
    assert (
        candidate.comparable_evidence.market_comparables[0].listing_id.value
        == "at-match"
    )


def test_each_auction_lot_produces_its_own_candidate() -> None:
    far_lot = replace(BASE_LOT, id=AuctionLotId("bca-2"), mileage=50_000)
    near_listing = replace(
        BASE_LISTING, id=AutoTraderListingId("at-near"), mileage=30_000
    )
    far_listing = replace(
        BASE_LISTING, id=AutoTraderListingId("at-far"), mileage=60_000
    )

    opportunities = OpportunitySearch().search(
        [BASE_LOT, far_lot],
        MarketSnapshot([near_listing, far_listing]),
    )

    candidates = opportunities.candidates
    assert [candidate.auction_lot.id.value for candidate in candidates] == [
        "bca-1",
        "bca-2",
    ]
    assert candidates[0].comparable_supply == 1
    assert (
        candidates[0].comparable_evidence.market_comparables[0].listing_id.value
        == "at-near"
    )
    assert candidates[1].comparable_supply == 1
    assert (
        candidates[1].comparable_evidence.market_comparables[0].listing_id.value
        == "at-far"
    )


def test_opportunity_search_returns_an_empty_list_for_no_auction_lots() -> None:
    opportunities = OpportunitySearch().search([], MarketSnapshot([BASE_LISTING]))

    assert opportunities == OpportunityList(())


def test_candidate_can_have_a_negative_price_spread() -> None:
    lot = replace(BASE_LOT, cap_clean_price=CapCleanPrice(14_000))
    listing = replace(BASE_LISTING, cash_price=CashPrice(12_500))

    opportunities = OpportunitySearch().search([lot], MarketSnapshot([listing]))

    assert len(opportunities.candidates) == 1
    assert opportunities.candidates[0].price_spread == PriceSpread(-1_500)


def test_candidate_with_equal_advertised_price_and_cap_has_zero_price_spread() -> None:
    at_cap_listing = replace(BASE_LISTING, cash_price=CashPrice(10_000))

    opportunities = OpportunitySearch().search(
        [BASE_LOT], MarketSnapshot([at_cap_listing])
    )

    candidate = opportunities.candidates[0]
    assert candidate.comparable_supply == 1
    assert candidate.price_spread == PriceSpread(0)


def test_candidate_with_no_direct_market_comparable_remains_in_the_list() -> None:
    out_of_band_listing = replace(
        BASE_LISTING,
        id=AutoTraderListingId("at-far"),
        mileage=55_001,
    )

    opportunities = OpportunitySearch().search(
        [BASE_LOT], MarketSnapshot([out_of_band_listing])
    )

    assert len(opportunities.candidates) == 1
    candidate = opportunities.candidates[0]
    assert candidate.comparable_supply == 0
    assert candidate.comparable_evidence == NoComparableEvidence()
    assert candidate.price_spread == NoComparableEvidence()
