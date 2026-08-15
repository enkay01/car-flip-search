from dataclasses import replace

import pytest

from car_flip_search import (
    AdvertisedPrice,
    AuctionLot,
    AuctionLotId,
    AutoTraderListingId,
    CandidateFilter,
    CandidateVehicle,
    CapCleanPrice,
    CashPrice,
    ComparableEvidence,
    CoreVehicleIdentity,
    HighMileageReference,
    MarketComparable,
    NoComparableEvidence,
    NoRetailFloorEvidence,
    OpportunityList,
    RetailFloorEvidence,
    SellerType,
    SortCriterion,
    SortField,
)

BASE_IDENTITY = CoreVehicleIdentity(
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
    identity=BASE_IDENTITY,
    mileage=40_000,
    cap_clean_price=CapCleanPrice(10_000),
    trim=None,
)

IDENTITY_FIELDS = {
    "make",
    "model_variant",
    "registration_year",
    "fuel_type",
    "transmission",
    "body_style",
    "door_count",
}


def comparable_evidence(
    supply: int, lowest_price: int
) -> ComparableEvidence | NoComparableEvidence:
    if supply == 0:
        return NoComparableEvidence()
    return ComparableEvidence(
        tuple(
            MarketComparable(
                AutoTraderListingId(f"at-c-{index}"),
                BASE_IDENTITY,
                40_000,
                AdvertisedPrice(CashPrice(lowest_price + index)),
                SellerType.DEALER,
                None,
                False,
            )
            for index in range(supply)
        )
    )


def retail_floor_evidence(
    prices: tuple[int, ...],
) -> RetailFloorEvidence | NoRetailFloorEvidence:
    if not prices:
        return NoRetailFloorEvidence()
    return RetailFloorEvidence(
        tuple(
            HighMileageReference(
                AutoTraderListingId(f"at-r-{index}"),
                BASE_IDENTITY,
                60_000 + index,
                AdvertisedPrice(CashPrice(price)),
                SellerType.DEALER,
                None,
            )
            for index, price in enumerate(prices)
        )
    )


def candidate(
    lot: AuctionLot,
    supply: int = 0,
    lowest_price: int = 12_000,
    reference_prices: tuple[int, ...] = (),
) -> CandidateVehicle:
    return CandidateVehicle(
        lot,
        comparable_evidence(supply, lowest_price),
        retail_floor_evidence(reference_prices),
    )


def vary_attribute(lot: AuctionLot, field: str, value: str | int) -> AuctionLot:
    if field in IDENTITY_FIELDS:
        return replace(lot, identity=replace(lot.identity, **{field: value}))
    if field == "mileage":
        return replace(lot, mileage=value)
    return replace(lot, cap_clean_price=CapCleanPrice(value))


def ids(candidates: OpportunityList) -> list[str]:
    return [candidate.auction_lot.id.value for candidate in candidates.candidates]


@pytest.mark.parametrize(
    ("attribute", "matching", "non_matching"),
    [
        ("make", "Mercedes-Benz", "Audi"),
        ("model_variant", "A180d", "A200d"),
        ("registration_year", 2020, 2019),
        ("fuel_type", "Diesel", "Petrol"),
        ("transmission", "Automatic", "Manual"),
        ("body_style", "Hatchback", "Saloon"),
        ("door_count", 5, 3),
        ("mileage", 40_000, 50_000),
        ("cap_clean_price", 10_000, 8_000),
    ],
)
def test_filter_by_scalar_vehicle_attribute(
    attribute: str, matching: str | int, non_matching: str | int
) -> None:
    match = candidate(
        replace(vary_attribute(BASE_LOT, attribute, matching), id=AuctionLotId("match"))
    )
    miss = candidate(
        replace(
            vary_attribute(BASE_LOT, attribute, non_matching), id=AuctionLotId("miss")
        )
    )

    result = OpportunityList((match, miss)).filter(
        CandidateFilter(**{attribute: matching})
    )

    assert ids(result) == ["match"]


def test_filter_by_trim_value_and_presence() -> None:
    with_trim = candidate(replace(BASE_LOT, id=AuctionLotId("trimmed"), trim="M Sport"))
    without_trim = candidate(replace(BASE_LOT, id=AuctionLotId("bare"), trim=None))

    by_value = OpportunityList((with_trim, without_trim)).filter(
        CandidateFilter(trim="M Sport")
    )
    assert ids(by_value) == ["trimmed"]

    present = OpportunityList((with_trim, without_trim)).filter(
        CandidateFilter(has_trim=True)
    )
    assert ids(present) == ["trimmed"]

    absent = OpportunityList((with_trim, without_trim)).filter(
        CandidateFilter(has_trim=False)
    )
    assert ids(absent) == ["bare"]


def test_filter_by_comparable_supply() -> None:
    one = candidate(replace(BASE_LOT, id=AuctionLotId("one")), supply=1)
    two = candidate(replace(BASE_LOT, id=AuctionLotId("two")), supply=2)
    zero = candidate(replace(BASE_LOT, id=AuctionLotId("zero")), supply=0)

    result = OpportunityList((one, two, zero)).filter(
        CandidateFilter(comparable_supply=1)
    )

    assert ids(result) == ["one"]


def test_filter_by_price_spread_presence_and_value() -> None:
    positive = candidate(
        replace(BASE_LOT, id=AuctionLotId("positive")), supply=1, lowest_price=12_500
    )
    negative = candidate(
        replace(BASE_LOT, id=AuctionLotId("negative")), supply=1, lowest_price=9_000
    )
    zero = candidate(
        replace(BASE_LOT, id=AuctionLotId("zero")), supply=1, lowest_price=10_000
    )
    absent = candidate(replace(BASE_LOT, id=AuctionLotId("absent")), supply=0)

    present = OpportunityList((positive, negative, zero, absent)).filter(
        CandidateFilter(has_price_spread=True)
    )
    assert ids(present) == ["positive", "negative", "zero"]

    missing = OpportunityList((positive, negative, zero, absent)).filter(
        CandidateFilter(has_price_spread=False)
    )
    assert ids(missing) == ["absent"]

    at_zero = OpportunityList((positive, negative, zero, absent)).filter(
        CandidateFilter(price_spread=0)
    )
    assert ids(at_zero) == ["zero"]


def test_filter_by_retail_floor_spread_presence_and_value() -> None:
    negative = candidate(
        replace(BASE_LOT, id=AuctionLotId("negative")), reference_prices=(8_500,)
    )
    positive = candidate(
        replace(BASE_LOT, id=AuctionLotId("positive")), reference_prices=(11_000,)
    )
    zero = candidate(
        replace(BASE_LOT, id=AuctionLotId("zero")), reference_prices=(10_000,)
    )
    absent = candidate(replace(BASE_LOT, id=AuctionLotId("absent")))

    present = OpportunityList((negative, positive, zero, absent)).filter(
        CandidateFilter(has_retail_floor_spread=True)
    )
    assert ids(present) == ["negative", "positive", "zero"]

    missing = OpportunityList((negative, positive, zero, absent)).filter(
        CandidateFilter(has_retail_floor_spread=False)
    )
    assert ids(missing) == ["absent"]

    at_value = OpportunityList((negative, positive, zero, absent)).filter(
        CandidateFilter(retail_floor_spread=1_000)
    )
    assert ids(at_value) == ["positive"]


def test_filter_composes_multiple_criteria() -> None:
    both = candidate(replace(BASE_LOT, id=AuctionLotId("both")), supply=2)
    single = candidate(replace(BASE_LOT, id=AuctionLotId("single")), supply=1)
    none = candidate(replace(BASE_LOT, id=AuctionLotId("none")), supply=0)

    result = OpportunityList((both, single, none)).filter(
        CandidateFilter(
            make="Mercedes-Benz",
            has_price_spread=True,
            comparable_supply=2,
        )
    )

    assert ids(result) == ["both"]


def test_sort_by_price_spread_with_absent_last() -> None:
    positive = candidate(
        replace(BASE_LOT, id=AuctionLotId("positive")), supply=1, lowest_price=12_500
    )
    negative = candidate(
        replace(BASE_LOT, id=AuctionLotId("negative")), supply=1, lowest_price=9_000
    )
    absent = candidate(replace(BASE_LOT, id=AuctionLotId("absent")), supply=0)

    descending = OpportunityList((negative, absent, positive)).sort(
        SortCriterion(field=SortField.PRICE_SPREAD, descending=True)
    )
    assert ids(descending) == ["positive", "negative", "absent"]

    ascending = OpportunityList((negative, absent, positive)).sort(
        SortCriterion(field=SortField.PRICE_SPREAD)
    )
    assert ids(ascending) == ["negative", "positive", "absent"]


def test_sort_by_retail_floor_spread_with_absent_last() -> None:
    positive = candidate(
        replace(BASE_LOT, id=AuctionLotId("positive")), reference_prices=(11_000,)
    )
    negative = candidate(
        replace(BASE_LOT, id=AuctionLotId("negative")), reference_prices=(8_500,)
    )
    absent = candidate(replace(BASE_LOT, id=AuctionLotId("absent")))

    descending = OpportunityList((negative, absent, positive)).sort(
        SortCriterion(field=SortField.RETAIL_FLOOR_SPREAD, descending=True)
    )
    assert ids(descending) == ["positive", "negative", "absent"]

    ascending = OpportunityList((negative, absent, positive)).sort(
        SortCriterion(field=SortField.RETAIL_FLOOR_SPREAD)
    )
    assert ids(ascending) == ["negative", "positive", "absent"]


def test_sort_by_comparable_supply() -> None:
    zero = candidate(replace(BASE_LOT, id=AuctionLotId("zero")), supply=0)
    two = candidate(replace(BASE_LOT, id=AuctionLotId("two")), supply=2)
    one = candidate(replace(BASE_LOT, id=AuctionLotId("one")), supply=1)

    result = OpportunityList((zero, two, one)).sort(
        SortCriterion(field=SortField.COMPARABLE_SUPPLY, descending=True)
    )

    assert ids(result) == ["two", "one", "zero"]


@pytest.mark.parametrize(
    ("field", "lower_value", "higher_value"),
    [
        (SortField.MAKE, "Audi", "Volvo"),
        (SortField.MODEL_VARIANT, "A100d", "A200d"),
        (SortField.REGISTRATION_YEAR, 2019, 2021),
        (SortField.FUEL_TYPE, "Electric", "Petrol"),
        (SortField.TRANSMISSION, "Automatic", "Manual"),
        (SortField.BODY_STYLE, "Hatchback", "Saloon"),
        (SortField.DOOR_COUNT, 3, 5),
        (SortField.MILEAGE, 20_000, 40_000),
        (SortField.CAP_CLEAN_PRICE, 8_000, 12_000),
    ],
)
def test_sort_strategy_registry_orders_each_vehicle_field(
    field: SortField, lower_value: str | int, higher_value: str | int
) -> None:
    lower = candidate(
        replace(
            vary_attribute(BASE_LOT, field.value, lower_value),
            id=AuctionLotId("lower"),
        )
    )
    higher = candidate(
        replace(
            vary_attribute(BASE_LOT, field.value, higher_value),
            id=AuctionLotId("higher"),
        )
    )

    result = OpportunityList((higher, lower)).sort(SortCriterion(field=field))

    assert ids(result) == ["lower", "higher"]


def test_sort_strategy_registry_orders_optional_and_derived_fields() -> None:
    cases = {
        SortField.TRIM: (
            candidate(replace(BASE_LOT, id=AuctionLotId("trim-lower"), trim="M Sport")),
            candidate(replace(BASE_LOT, id=AuctionLotId("trim-higher"), trim="SE")),
        ),
        SortField.COMPARABLE_SUPPLY: (
            candidate(replace(BASE_LOT, id=AuctionLotId("supply-lower")), supply=1),
            candidate(replace(BASE_LOT, id=AuctionLotId("supply-higher")), supply=2),
        ),
        SortField.PRICE_SPREAD: (
            candidate(
                replace(BASE_LOT, id=AuctionLotId("spread-lower")),
                supply=1,
                lowest_price=9_000,
            ),
            candidate(
                replace(BASE_LOT, id=AuctionLotId("spread-higher")),
                supply=1,
                lowest_price=12_000,
            ),
        ),
        SortField.RETAIL_FLOOR_SPREAD: (
            candidate(
                replace(BASE_LOT, id=AuctionLotId("floor-lower")),
                reference_prices=(8_000,),
            ),
            candidate(
                replace(BASE_LOT, id=AuctionLotId("floor-higher")),
                reference_prices=(12_000,),
            ),
        ),
    }

    for field, (lower, higher) in cases.items():
        result = OpportunityList((higher, lower)).sort(SortCriterion(field=field))
        assert ids(result) == [
            lower.auction_lot.id.value,
            higher.auction_lot.id.value,
        ]


def test_sort_by_trim_places_absent_value_last() -> None:
    sport = candidate(replace(BASE_LOT, id=AuctionLotId("sport"), trim="M Sport"))
    se = candidate(replace(BASE_LOT, id=AuctionLotId("se"), trim="SE"))
    bare = candidate(replace(BASE_LOT, id=AuctionLotId("bare"), trim=None))

    result = OpportunityList((bare, sport, se)).sort(
        SortCriterion(field=SortField.TRIM)
    )

    assert ids(result) == ["sport", "se", "bare"]


def test_sort_by_multiple_criteria_uses_stable_secondary_order() -> None:
    a = candidate(
        replace(BASE_LOT, id=AuctionLotId("a")), supply=1, lowest_price=12_500
    )
    b = candidate(replace(BASE_LOT, id=AuctionLotId("b")), supply=1, lowest_price=9_000)
    c = candidate(
        replace(BASE_LOT, id=AuctionLotId("c")), supply=2, lowest_price=12_000
    )

    result = OpportunityList((b, c, a)).sort(
        SortCriterion(field=SortField.COMPARABLE_SUPPLY, descending=True),
        SortCriterion(field=SortField.PRICE_SPREAD, descending=True),
    )

    assert ids(result) == ["c", "a", "b"]


def test_filter_then_sort_composes() -> None:
    positive = candidate(
        replace(BASE_LOT, id=AuctionLotId("positive")), supply=1, lowest_price=12_500
    )
    negative = candidate(
        replace(BASE_LOT, id=AuctionLotId("negative")), supply=1, lowest_price=9_000
    )
    absent = candidate(replace(BASE_LOT, id=AuctionLotId("absent")), supply=0)

    result = (
        OpportunityList((positive, negative, absent))
        .filter(CandidateFilter(has_price_spread=True))
        .sort(SortCriterion(field=SortField.PRICE_SPREAD, descending=True))
    )

    assert ids(result) == ["positive", "negative"]
