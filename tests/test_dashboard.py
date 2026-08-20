import json
from dataclasses import dataclass
from pathlib import Path

from car_flip_search import AutoTraderRawRecord, BcaRawRecord, SourceKind
from car_flip_search.dashboard import (
    DashboardRequest,
    build_capture_management_page,
    build_dashboard_page,
    create_app,
    delete_captures,
    discover_captures,
    validate_source_link,
)

type RawRecord = BcaRawRecord | AutoTraderRawRecord

IDENTITY = {
    "make": "BMW",
    "model_variant": "320d",
    "registration_year": 2016,
    "fuel_type": "Diesel",
    "transmission": "Automatic",
    "body_style": "Saloon",
    "door_count": 4,
}


def bca_record(
    record_id: str = "bca-1",
    *,
    source_url: str | None = None,
    cap_clean_price: int = 5_000,
) -> BcaRawRecord:
    record: BcaRawRecord = {
        "id": record_id,
        "identity": IDENTITY,
        "mileage": 40_000,
        "cap_clean_price": cap_clean_price,
        "clean_condition": True,
        "write_off_reported": False,
        "accident_damage_reported": False,
    }
    if source_url is not None:
        record["source_url"] = source_url
    return record


def autotrader_record(
    record_id: str = "at-1",
    *,
    mileage: int = 40_000,
    cash_price: int = 9_000,
    source_url: str | None = None,
) -> AutoTraderRawRecord:
    record: AutoTraderRawRecord = {
        "id": record_id,
        "identity": IDENTITY,
        "mileage": mileage,
        "cash_price": cash_price,
        "seller_type": "dealer",
    }
    if source_url is not None:
        record["source_url"] = source_url
    return record


@dataclass(frozen=True, kw_only=True)
class CaptureFixture:
    data_root: Path
    source: SourceKind
    capture_id: str
    saved_at: str
    records: tuple[RawRecord, ...]
    search_name: str = "BMW 320d"
    stop_reason: str = "completed"
    source_in_manifest: str | None = None


def write_capture(fixture: CaptureFixture) -> Path:
    capture_path = fixture.data_root / fixture.source.value / fixture.capture_id
    capture_path.mkdir(parents=True)
    manifest = {
        "capture_id": fixture.capture_id,
        "source": fixture.source_in_manifest or fixture.source.value,
        "search_name": fixture.search_name,
        "movement_limit": 1,
        "movement_delay_seconds": 1,
        "pages_captured": 1,
        "records_captured": len(fixture.records),
        "records_skipped": 0,
        "stop_reason": fixture.stop_reason,
        "saved_at": fixture.saved_at,
    }
    (capture_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (capture_path / "records.json").write_text(
        json.dumps(fixture.records), encoding="utf-8"
    )
    return capture_path


def test_empty_data_root_renders_setup_state(tmp_path: Path) -> None:
    response = create_app(tmp_path).test_client().get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "No usable Capture Pair" in body
    assert "No saved Captures" in body
    assert "Opportunity List" not in body


def test_capture_manager_lists_valid_and_unreadable_capture_directories(
    tmp_path: Path,
) -> None:
    write_capture(
        CaptureFixture(
            data_root=tmp_path,
            source=SourceKind.BCA,
            capture_id="bca-old",
            saved_at="2026-08-18T12:00:00+00:00",
            records=(bca_record(),),
        )
    )
    write_capture(
        CaptureFixture(
            data_root=tmp_path,
            source=SourceKind.AUTOTRADER,
            capture_id="at-old",
            saved_at="2026-08-19T12:00:00+00:00",
            records=(autotrader_record(),),
        )
    )
    broken_path = tmp_path / SourceKind.BCA.value / "bca-broken"
    broken_path.mkdir(parents=True)
    (broken_path / "manifest.json").write_text("not json", encoding="utf-8")

    page = build_capture_management_page(tmp_path)
    assert [entry.capture_id for entry in page.entries] == [
        "at-old",
        "bca-old",
        "bca-broken",
    ]
    assert page.entries[-1].status_label == "Unavailable"

    response = create_app(tmp_path).test_client().get("/captures")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Manage Captures" in body
    assert 'value="bca:bca-old"' in body
    assert 'value="autotrader:at-old"' in body
    assert "bca-broken" in body
    assert "Unavailable" in body


def test_delete_captures_removes_selected_directories_in_bulk(tmp_path: Path) -> None:
    write_capture(
        CaptureFixture(
            data_root=tmp_path,
            source=SourceKind.BCA,
            capture_id="bca-delete",
            saved_at="2026-08-18T12:00:00+00:00",
            records=(bca_record(),),
        )
    )
    write_capture(
        CaptureFixture(
            data_root=tmp_path,
            source=SourceKind.BCA,
            capture_id="bca-keep",
            saved_at="2026-08-19T12:00:00+00:00",
            records=(bca_record("bca-2"),),
        )
    )
    write_capture(
        CaptureFixture(
            data_root=tmp_path,
            source=SourceKind.AUTOTRADER,
            capture_id="at-delete",
            saved_at="2026-08-19T13:00:00+00:00",
            records=(autotrader_record(),),
        )
    )

    response = (
        create_app(tmp_path)
        .test_client()
        .post(
            "/captures/delete",
            data={"capture": ["bca:bca-delete", "autotrader:at-delete"]},
            follow_redirects=True,
        )
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "2 Captures deleted." in body
    assert not (tmp_path / "bca" / "bca-delete").exists()
    assert not (tmp_path / "autotrader" / "at-delete").exists()
    assert (tmp_path / "bca" / "bca-keep").is_dir()
    assert "bca-keep" in body
    assert "bca-delete" not in body


def test_delete_captures_rejects_out_of_root_and_unknown_selections(
    tmp_path: Path,
) -> None:
    outside_path = tmp_path / "outside"
    outside_path.mkdir()
    (outside_path / "keep.txt").write_text("keep", encoding="utf-8")

    result = delete_captures(
        tmp_path,
        ("bca:../outside", "unknown:capture", "bca:missing"),
    )

    assert result.deleted_count == 0
    assert result.skipped_count == 3
    assert (outside_path / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_latest_pair_renders_table_and_evidence_links(tmp_path: Path) -> None:
    write_capture(
        CaptureFixture(
            data_root=tmp_path,
            source=SourceKind.BCA,
            capture_id="bca-new",
            saved_at="2026-08-19T12:00:00+00:00",
            records=(bca_record(source_url="/lot/bca-1"),),
        )
    )
    write_capture(
        CaptureFixture(
            data_root=tmp_path,
            source=SourceKind.AUTOTRADER,
            capture_id="at-new",
            saved_at="2026-08-19T12:01:00+00:00",
            records=(
                autotrader_record(source_url="/car-details/at-1"),
                autotrader_record(
                    "at-2",
                    mileage=60_001,
                    cash_price=8_000,
                    source_url="https://www.autotrader.co.uk/car-details/at-2",
                ),
            ),
        )
    )

    response = create_app(tmp_path).test_client().get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "BMW 320d" in body
    assert "£5,000" in body
    assert "£8,000" in body
    assert "No Retail Floor" not in body
    assert "Open Auction Lot" in body
    assert "https://www.bca.co.uk/lot/bca-1" in body
    assert "https://www.autotrader.co.uk/car-details/at-2" in body
    assert "Sets Retail Floor" in body
    assert "Retail-Floor Spread" in body
    assert "Price Spread" in body


def test_partial_autotrader_identity_keeps_capture_usable_with_warning(
    tmp_path: Path,
) -> None:
    write_capture(
        CaptureFixture(
            data_root=tmp_path,
            source=SourceKind.BCA,
            capture_id="bca-new",
            saved_at="2026-08-19T12:00:00+00:00",
            records=(bca_record(),),
        )
    )
    incomplete_record = autotrader_record()
    incomplete_record["identity"] = {
        "make": "BMW",
        "model_variant": "320d",
        "registration_year": 2016,
        "fuel_type": "Diesel",
        "body_style": "Saloon",
        "door_count": 4,
    }
    write_capture(
        CaptureFixture(
            data_root=tmp_path,
            source=SourceKind.AUTOTRADER,
            capture_id="at-new",
            saved_at="2026-08-19T12:01:00+00:00",
            records=(incomplete_record,),
        )
    )

    page = build_dashboard_page(
        DashboardRequest(
            data_root=tmp_path,
            bca_capture_id=None,
            autotrader_capture_id=None,
            search_query="",
            sort_field="retail_floor_spread",
            direction="desc",
        )
    )

    assert page.has_pair
    assert page.autotrader_capture is not None
    assert page.autotrader_capture.comparison_ready_count == 0
    assert page.notices == (
        (
            "Auto Trader Capture at-new has 1 captured record without complete vehicle "
            "identity; they are excluded from market evidence. The Capture remains usable."
        ),
    )
    assert len(page.candidates) == 1
    assert page.candidates[0].price_spread_label == "No Price Spread"

    response = create_app(tmp_path).test_client().get("/")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "The Capture remains usable." in body
    assert "No Market Comparables." in body


def test_explicit_missing_capture_falls_back_only_for_that_source(
    tmp_path: Path,
) -> None:
    write_capture(
        CaptureFixture(
            data_root=tmp_path,
            source=SourceKind.BCA,
            capture_id="bca-old",
            saved_at="2026-08-19T12:00:00+00:00",
            records=(bca_record(),),
        )
    )
    write_capture(
        CaptureFixture(
            data_root=tmp_path,
            source=SourceKind.AUTOTRADER,
            capture_id="at-selected",
            saved_at="2026-08-19T12:01:00+00:00",
            records=(autotrader_record(),),
        )
    )

    page = build_dashboard_page(
        DashboardRequest(
            data_root=tmp_path,
            bca_capture_id="bca-gone",
            autotrader_capture_id="at-selected",
            search_query="",
            sort_field="retail_floor_spread",
            direction="desc",
        )
    )

    assert page.bca_capture is not None
    assert page.bca_capture.capture_id == "bca-old"
    assert page.autotrader_capture is not None
    assert page.autotrader_capture.capture_id == "at-selected"
    assert page.notices == (
        "BCA Capture bca-gone is unavailable; using newest valid Capture bca-old.",
    )


def test_malformed_capture_is_unavailable_and_does_not_make_a_pair(
    tmp_path: Path,
) -> None:
    write_capture(
        CaptureFixture(
            data_root=tmp_path,
            source=SourceKind.BCA,
            capture_id="bca-bad",
            saved_at="not-a-timestamp",
            records=(bca_record(),),
        )
    )

    inventory = discover_captures(tmp_path, SourceKind.BCA)
    assert inventory.captures == ()
    assert inventory.problems[0].capture_id == "bca-bad"
    assert "saved_at" in inventory.problems[0].reason

    response = create_app(tmp_path).test_client().get("/")
    assert response.status_code == 200
    assert "bca-bad" in response.get_data(as_text=True)
    assert "No usable Capture Pair" in response.get_data(as_text=True)


def test_search_name_mismatch_warns_without_blocking_pair(tmp_path: Path) -> None:
    write_capture(
        CaptureFixture(
            data_root=tmp_path,
            source=SourceKind.BCA,
            capture_id="bca-1",
            saved_at="2026-08-19T12:00:00+00:00",
            records=(bca_record(),),
            search_name="BMW petrol",
        )
    )
    write_capture(
        CaptureFixture(
            data_root=tmp_path,
            source=SourceKind.AUTOTRADER,
            capture_id="at-1",
            saved_at="2026-08-19T12:01:00+00:00",
            records=(autotrader_record(),),
            search_name="BMW diesel",
        )
    )

    page = build_dashboard_page(
        DashboardRequest(
            data_root=tmp_path,
            bca_capture_id=None,
            autotrader_capture_id=None,
            search_query="",
            sort_field="retail_floor_spread",
            direction="desc",
        )
    )

    assert page.search_name_warning is not None
    assert page.candidates


def test_source_link_validation_rejects_untrusted_or_wrong_record_urls() -> None:
    assert (
        validate_source_link(SourceKind.BCA, "KS18 ZFM", "/lot/KS18%20ZFM")
        == "https://www.bca.co.uk/lot/KS18%20ZFM"
    )
    assert (
        validate_source_link(
            SourceKind.AUTOTRADER,
            "202603271072975",
            "https://www.autotrader.co.uk/car-details/202603271072975?src=search",
        )
        == "https://www.autotrader.co.uk/car-details/202603271072975?src=search"
    )
    assert validate_source_link(SourceKind.BCA, "bca-1", "javascript:alert(1)") is None
    assert validate_source_link(SourceKind.BCA, "bca-1", "data:text/html,no") is None
    assert (
        validate_source_link(SourceKind.BCA, "bca-1", "https://example.com/lot/bca-1")
        is None
    )
    assert (
        validate_source_link(SourceKind.BCA, "bca-1", "https://www.bca.co.uk/lot/other")
        is None
    )
