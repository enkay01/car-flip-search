import pytest

from car_flip_search import (
    AuctionLot,
    AuctionLotId,
    AutoTraderListing,
    AutoTraderListingId,
    BcaAcquisition,
    BcaRawRecord,
    CapCleanPrice,
    CashPrice,
    CoreVehicleIdentity,
    MarketSnapshot,
    OpportunitySearch,
    SellerType,
)

DEFAULT_IDENTITY = CoreVehicleIdentity(
    make="BMW",
    model_variant="320d",
    registration_year=2016,
    fuel_type="Diesel",
    transmission="Automatic",
    body_style="Saloon",
    door_count=4,
)


def make_record() -> BcaRawRecord:
    return {
        "id": "YF66 FEJ",
        "identity": {
            "make": "BMW",
            "model_variant": "320d",
            "registration_year": 2016,
            "fuel_type": "Diesel",
            "transmission": "Automatic",
            "body_style": "Saloon",
            "door_count": 4,
        },
        "mileage": 130_319,
        "cap_clean_price": 5_450,
        "clean_condition": True,
        "write_off_reported": False,
        "accident_damage_reported": False,
        "trim": "M Sport",
    }


def incomplete_records() -> tuple[BcaRawRecord, ...]:
    missing_id = make_record()
    missing_id.pop("id")

    missing_identity = make_record()
    missing_identity.pop("identity")

    incomplete_identity = make_record()
    incomplete_identity["identity"].pop("door_count")

    missing_mileage = make_record()
    missing_mileage.pop("mileage")

    negative_mileage = make_record()
    negative_mileage["mileage"] = -1

    missing_cap_clean_price = make_record()
    missing_cap_clean_price.pop("cap_clean_price")

    negative_cap_clean_price = make_record()
    negative_cap_clean_price["cap_clean_price"] = -1

    missing_clean_condition = make_record()
    missing_clean_condition.pop("clean_condition")

    false_clean_condition = make_record()
    false_clean_condition["clean_condition"] = False

    missing_write_off_status = make_record()
    missing_write_off_status.pop("write_off_reported")

    reported_write_off = make_record()
    reported_write_off["write_off_reported"] = True

    missing_accident_status = make_record()
    missing_accident_status.pop("accident_damage_reported")

    reported_accident_damage = make_record()
    reported_accident_damage["accident_damage_reported"] = True

    return (
        missing_id,
        missing_identity,
        incomplete_identity,
        missing_mileage,
        negative_mileage,
        missing_cap_clean_price,
        negative_cap_clean_price,
        missing_clean_condition,
        false_clean_condition,
        missing_write_off_status,
        reported_write_off,
        missing_accident_status,
        reported_accident_damage,
    )


def test_bca_acquisition_emits_a_strict_auction_lot() -> None:
    acquired_lots = BcaAcquisition().acquire([make_record()])

    assert acquired_lots == (
        AuctionLot(
            id=AuctionLotId("YF66 FEJ"),
            identity=DEFAULT_IDENTITY,
            mileage=130_319,
            cap_clean_price=CapCleanPrice(5_450),
            trim="M Sport",
        ),
    )


@pytest.mark.parametrize("invalid_record", incomplete_records())
def test_bca_acquisition_silently_discards_incomplete_records(
    invalid_record: BcaRawRecord,
) -> None:
    assert BcaAcquisition().acquire([invalid_record]) == ()


def test_bca_acquisition_can_rediscover_a_record_after_missing_data_is_added() -> None:
    record_without_mileage = make_record()
    record_without_mileage.pop("mileage")

    assert BcaAcquisition().acquire([record_without_mileage]) == ()
    assert len(BcaAcquisition().acquire([make_record()])) == 1


def test_bca_acquisition_allows_raw_payloads_to_omit_optional_trim() -> None:
    record_without_trim = make_record()
    record_without_trim.pop("trim")

    assert BcaAcquisition().acquire([record_without_trim])[0].trim is None


def test_acquired_bca_lot_passes_to_opportunity_search_without_lifecycle_inputs() -> (
    None
):
    auction_lot = BcaAcquisition().acquire([make_record()])[0]
    listing = AutoTraderListing(
        id=AutoTraderListingId("202603271072975"),
        identity=DEFAULT_IDENTITY,
        mileage=117_004,
        cash_price=CashPrice(8_995),
        seller_type=SellerType.DEALER,
    )

    opportunities = OpportunitySearch().search(
        [auction_lot],
        MarketSnapshot([listing]),
    )

    assert opportunities.candidates[0].auction_lot == auction_lot
    assert opportunities.candidates[0].comparable_supply == 1
    assert opportunities.candidates[0].price_spread.pounds == 3_545
