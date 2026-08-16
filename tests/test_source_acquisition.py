import json
from pathlib import Path

import pytest

from car_flip_search import (
    AuctionLot,
    AuctionLotId,
    AutoTraderAcquisition,
    AutoTraderListing,
    AutoTraderListingId,
    AutoTraderRawRecord,
    BcaAcquisition,
    BcaRawRecord,
    CapCleanPrice,
    CashPrice,
    CoreVehicleIdentity,
    ManualAutoTraderImporter,
    ManualBcaImporter,
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


def make_autotrader_record() -> AutoTraderRawRecord:
    return {
        "id": "202603271072975",
        "identity": {
            "make": "BMW",
            "model_variant": "320d",
            "registration_year": 2016,
            "fuel_type": "Diesel",
            "transmission": "Automatic",
            "body_style": "Saloon",
            "door_count": 4,
        },
        "mileage": 117_004,
        "cash_price": 8_995,
        "seller_type": "dealer",
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


def incomplete_autotrader_records() -> tuple[AutoTraderRawRecord, ...]:
    missing_id = make_autotrader_record()
    missing_id.pop("id")

    missing_identity = make_autotrader_record()
    missing_identity.pop("identity")

    incomplete_identity = make_autotrader_record()
    incomplete_identity["identity"].pop("door_count")

    missing_mileage = make_autotrader_record()
    missing_mileage.pop("mileage")

    negative_mileage = make_autotrader_record()
    negative_mileage["mileage"] = -1

    missing_cash_price = make_autotrader_record()
    missing_cash_price.pop("cash_price")

    negative_cash_price = make_autotrader_record()
    negative_cash_price["cash_price"] = -1

    missing_seller_type = make_autotrader_record()
    missing_seller_type.pop("seller_type")

    invalid_seller_type = make_autotrader_record()
    invalid_seller_type["seller_type"] = "auctioneer"

    return (
        missing_id,
        missing_identity,
        incomplete_identity,
        missing_mileage,
        negative_mileage,
        missing_cash_price,
        negative_cash_price,
        missing_seller_type,
        invalid_seller_type,
    )


def sample_bca_dom_html() -> str:
    return """
    <!DOCTYPE html>
    <html>
    <head><title>BCA Search Results</title></head>
    <body>
        <div class="search-results">
            <div class="lot-card"
                 data-lot-id="YF66 FEJ"
                 data-make="BMW"
                 data-model-variant="320d"
                 data-registration-year="2016"
                 data-fuel-type="Diesel"
                 data-transmission="Automatic"
                 data-body-style="Saloon"
                 data-door-count="4"
                 data-mileage="130319"
                 data-cap-clean-price="5450"
                 data-clean-condition="true"
                 data-write-off-reported="false"
                 data-accident-damage-reported="false"
                 data-trim="M Sport">
                <h2>BMW 320d M Sport</h2>
            </div>
        </div>
    </body>
    </html>
    """


def sample_bca_json_script_html() -> str:
    payload = json.dumps([make_record()])
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <script id="__NEXT_DATA__" type="application/json">
        {{"props": {{"pageProps": {{"searchResults": {payload}}}}}}}
        </script>
    </head>
    <body><h1>BCA Portal</h1></body>
    </html>
    """


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


def test_autotrader_acquisition_emits_strict_listing_and_snapshot() -> None:
    acquisition = AutoTraderAcquisition()
    listings = acquisition.acquire([make_autotrader_record()])

    assert listings == (
        AutoTraderListing(
            id=AutoTraderListingId("202603271072975"),
            identity=DEFAULT_IDENTITY,
            mileage=117_004,
            cash_price=CashPrice(8_995),
            seller_type=SellerType.DEALER,
            trim="M Sport",
        ),
    )

    snapshot = acquisition.acquire_snapshot([make_autotrader_record()])
    assert snapshot.listings == listings


@pytest.mark.parametrize("invalid_record", incomplete_autotrader_records())
def test_autotrader_acquisition_silently_discards_incomplete_records(
    invalid_record: AutoTraderRawRecord,
) -> None:
    assert AutoTraderAcquisition().acquire([invalid_record]) == ()


def test_autotrader_acquisition_allows_omitted_trim() -> None:
    record = make_autotrader_record()
    record.pop("trim")

    listings = AutoTraderAcquisition().acquire([record])
    assert listings[0].trim is None


def test_manual_bca_importer_parses_json_and_records() -> None:
    importer = ManualBcaImporter()
    record = make_record()

    imported_from_records = importer.import_from_records([record])
    assert len(imported_from_records) == 1
    assert imported_from_records[0].id == AuctionLotId("YF66 FEJ")

    json_payload = json.dumps([record])
    imported_from_json = importer.import_from_json(json_payload)
    assert len(imported_from_json) == 1
    assert imported_from_json[0].id == AuctionLotId("YF66 FEJ")

    assert importer.import_from_json("invalid json") == ()
    assert importer.import_from_json('{"not": "a list"}') == ()


def sample_bca_live_card_html() -> str:
    return """
    <!DOCTYPE html>
    <html>
    <body>
        <div class="VehicleResultCardDesktop">
            <a data-testid="card-link-desktop" href="https://www.bca.co.uk/lot/KS18%20ZFM?q=test"></a>
            <a class="VehicleResultCardDesktop__StyledLink-sc-123" href="https://www.bca.co.uk/lot/KS18%20ZFM">MERCEDES-BENZ A160 1.6 SPORT ED.DCT Hatchback</a>
            <ul>
                <li><p color="grey-blue">84,468 miles (Warranted)</p></li>
                <li><p color="grey-blue">2018 (18 reg)</p></li>
                <li><p color="grey-blue">Petrol</p></li>
                <li><p color="grey-blue">Auto Clutch</p></li>
                <li><p color="grey-blue">5 doors</p></li>
            </ul>
            <div>
                <p>CAP Clean</p>
                <p>£7,800</p>
            </div>
        </div>
    </body>
    </html>
    """


def test_manual_bca_importer_parses_dom_html_and_json_scripts(tmp_path: Path) -> None:
    importer = ManualBcaImporter()

    # 1. Parse from HTML DOM data attributes
    lots_from_dom = importer.import_from_html(sample_bca_dom_html())
    assert len(lots_from_dom) == 1
    assert lots_from_dom[0].id == AuctionLotId("YF66 FEJ")
    assert lots_from_dom[0].cap_clean_price == CapCleanPrice(5_450)

    # 2. Parse from HTML embedded JSON script tags
    lots_from_json_script = importer.import_from_html(sample_bca_json_script_html())
    assert len(lots_from_json_script) == 1
    assert lots_from_json_script[0].id == AuctionLotId("YF66 FEJ")

    # 3. Parse from live BCA search result card DOM
    lots_from_live_cards = importer.import_from_html(sample_bca_live_card_html())
    assert len(lots_from_live_cards) == 1
    assert lots_from_live_cards[0].id == AuctionLotId("KS18 ZFM")
    assert lots_from_live_cards[0].identity.make == "MERCEDES-BENZ"
    assert lots_from_live_cards[0].identity.model_variant == "A160"
    assert lots_from_live_cards[0].identity.registration_year == 2018
    assert lots_from_live_cards[0].mileage == 84_468
    assert lots_from_live_cards[0].cap_clean_price == CapCleanPrice(7_800)
    assert lots_from_live_cards[0].trim == "1.6 SPORT ED.DCT"

    # 4. Parse from saved HTML file on disk
    file_path = tmp_path / "bca_page.html"
    file_path.write_text(sample_bca_dom_html(), encoding="utf-8")
    lots_from_file = importer.import_from_html_file(str(file_path))
    assert len(lots_from_file) == 1
    assert lots_from_file[0].id == AuctionLotId("YF66 FEJ")

    # 5. Non-existent file returns empty tuple
    assert importer.import_from_html_file(str(tmp_path / "missing.html")) == ()


def sample_autotrader_live_card_html() -> str:
    return """
    <!DOCTYPE html>
    <html>
    <body>
        <div data-testid="search-listing">
            <a href="https://www.autotrader.co.uk/car-details/202603271072975">
                <h3 data-testid="search-listing-title">BMW 320d M Sport Saloon</h3>
            </a>
            <p>£8,995</p>
            <ul>
                <li>117,004 miles</li>
                <li>2016 (16 reg)</li>
                <li>Diesel</li>
                <li>Automatic</li>
                <li>4 doors</li>
                <li>Trade seller</li>
            </ul>
        </div>
    </body>
    </html>
    """


def test_manual_autotrader_importer_parses_json_and_records(tmp_path: Path) -> None:
    importer = ManualAutoTraderImporter()
    record = make_autotrader_record()

    snapshot_from_records = importer.import_from_records([record])
    assert len(snapshot_from_records.listings) == 1
    assert snapshot_from_records.listings[0].id == AutoTraderListingId("202603271072975")

    json_payload = json.dumps([record])
    snapshot_from_json = importer.import_from_json(json_payload)
    assert len(snapshot_from_json.listings) == 1
    assert snapshot_from_json.listings[0].id == AutoTraderListingId("202603271072975")

    assert importer.import_from_json("invalid json").listings == ()
    assert importer.import_from_json('{"not": "a list"}').listings == ()

    # HTML string import
    snapshot_from_html = importer.import_from_html(sample_autotrader_live_card_html())
    assert len(snapshot_from_html.listings) == 1
    assert snapshot_from_html.listings[0].id == AutoTraderListingId("202603271072975")
    assert snapshot_from_html.listings[0].cash_price == CashPrice(8_995)
    assert snapshot_from_html.listings[0].seller_type == SellerType.DEALER

    # HTML file import
    file_path = tmp_path / "autotrader_page.html"
    file_path.write_text(sample_autotrader_live_card_html(), encoding="utf-8")
    snapshot_from_file = importer.import_from_html_file(str(file_path))
    assert len(snapshot_from_file.listings) == 1
    assert snapshot_from_file.listings[0].id == AutoTraderListingId("202603271072975")

    # Missing file returns empty snapshot
    assert importer.import_from_html_file(str(tmp_path / "missing.html")).listings == ()
