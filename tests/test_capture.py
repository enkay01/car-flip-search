"""Tests for the user-assisted capture kernel (issues #8 and #9)."""

import json
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from car_flip_search import (
    BcaAcquisition,
    BcaCardObservation,
    CaptureChallengeError,
    CaptureHooks,
    CaptureOptions,
    CaptureOutcome,
    SkippedCar,
    SourceKind,
    StopReason,
    bca_capture_strategy,
    new_capture_id,
    observe_bca_cards,
    print_capture_summary,
    run_capture,
    save_capture,
    validate_bca_observation,
)


@dataclass(frozen=True, kw_only=True)
class CardSpec:
    """Fixture knobs for one BCA search card modelled on the real DOM."""

    lot_id: str = "KS18 ZFM"
    lot_link: bool = True
    title_href: str | None = None
    title: str = "MERCEDES-BENZ A160 1.6 SPORT ED.DCT Hatchback"
    mileage: int | None = 84_468
    year: int | None = 2018
    fuel: str | None = "Petrol"
    transmission: str | None = "Auto Clutch"
    doors: int | None = 5
    cap_clean_price: int | None = 7_800
    condition_block: bool = True
    write_off: bool = False


def make_stub(lot_id: str = "KS18 ZFM") -> str:
    """The link-only card variant every vehicle renders under the desktop card."""
    encoded = lot_id.replace(" ", "%20")
    return (
        '<div><a data-testid="card-link-desktop" '
        f'href="https://www.bca.co.uk/lot/{encoded}"></a></div>'
    )


def make_card(spec: CardSpec | None = None) -> str:
    """One full BCA search card built from a CardSpec."""
    spec = spec or CardSpec()
    encoded = spec.lot_id.replace(" ", "%20")
    marker_anchor = (
        f'<a data-testid="card-link-desktop" '
        f'href="https://www.bca.co.uk/lot/{encoded}?q=test"></a>'
        if spec.lot_link
        else ""
    )
    resolved_title_href = spec.title_href or f"https://www.bca.co.uk/lot/{encoded}"
    title_anchor = (
        f'<a class="VehicleResultCardDesktop__StyledLink-sc-123" '
        f'href="{resolved_title_href}">{spec.title}</a>'
    )
    spec_items = []
    if spec.mileage is not None:
        spec_items.append(
            f'<li><p color="grey-blue">{spec.mileage:,} miles (Warranted)</p></li>'
        )
    if spec.year is not None:
        spec_items.append(f'<li><p color="grey-blue">{spec.year} (18 reg)</p></li>')
    if spec.fuel is not None:
        spec_items.append(f'<li><p color="grey-blue">{spec.fuel}</p></li>')
    if spec.transmission is not None:
        spec_items.append(f'<li><p color="grey-blue">{spec.transmission}</p></li>')
    if spec.doors is not None:
        spec_items.append(f'<li><p color="grey-blue">{spec.doors} doors</p></li>')
    condition = (
        '<div data-testid="condition-report-icon">BCA Assured</div>'
        if spec.condition_block
        else ""
    )
    write_off_marker = '<div class="damage">Cat S</div>' if spec.write_off else ""
    price = (
        f"<p>£{spec.cap_clean_price:,}</p>" if spec.cap_clean_price is not None else ""
    )
    return f"""
    <div class="VehicleResultCardDesktop">
        {marker_anchor}
        {title_anchor}
        <ul>{"".join(spec_items)}</ul>
        {condition}
        {write_off_marker}
        <div><p>CAP Clean</p>{price}</div>
    </div>
    """


def make_page(*cards: str) -> str:
    return "<html><body>" + "".join(cards) + "</body></html>"


def base_observation() -> BcaCardObservation:
    return BcaCardObservation(
        lot_id="KS18 ZFM",
        make="MERCEDES-BENZ",
        model_variant="A160",
        registration_year=2018,
        fuel_type="Petrol",
        transmission="Auto Clutch",
        body_style="Hatchback",
        door_count=5,
        mileage=84_468,
        cap_clean_price=7_800,
        clean_condition=True,
        write_off_reported=False,
        accident_damage_reported=False,
    )


class FakePageSource:
    """Deterministic in-memory page source for capture-loop tests."""

    def __init__(
        self,
        pages: list[str],
        *,
        advance_results: list[bool] | None = None,
        error_on_read: int | None = None,
        error_on_advance: int | None = None,
    ) -> None:
        self._pages = pages
        self._advance_results = list(advance_results or [])
        self._error_on_read = error_on_read
        self._error_on_advance = error_on_advance
        self._reads = 0
        self._advances = 0

    def current_html(self) -> str:
        self._reads += 1
        if self._error_on_read == self._reads:
            raise CaptureChallengeError("session expired")
        return self._pages[self._reads - 1]

    def advance(self) -> bool:
        self._advances += 1
        if self._error_on_advance == self._advances:
            raise CaptureChallengeError("login page reached")
        if self._advances <= len(self._advance_results):
            return self._advance_results[self._advances - 1]
        return True


def no_pace(_seconds: float) -> None:
    """No-op pacer so tests never sleep."""


# --- CaptureOptions validation -------------------------------------------------


def test_capture_options_reject_zero_and_negative_delay() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        CaptureOptions(search_name="BMW A-Class", movement_delay_seconds=0)
    with pytest.raises(ValueError, match="greater than zero"):
        CaptureOptions(search_name="BMW A-Class", movement_delay_seconds=-1)


def test_capture_options_reject_bad_movement_limit_and_blank_name() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        CaptureOptions(search_name="BMW A-Class", movement_limit=0)
    with pytest.raises(ValueError, match="non-blank"):
        CaptureOptions(search_name="   ")


def test_capture_options_defaults() -> None:
    options = CaptureOptions(search_name="BMW A-Class")
    assert options.source is SourceKind.BCA
    assert options.movement_limit == 5
    assert options.movement_delay_seconds == 60.0
    assert options.data_dir == Path("data/captures/bca")


def test_capture_options_default_data_dir_follows_source() -> None:
    autotrader_options = CaptureOptions(
        search_name="BMW A-Class", source=SourceKind.AUTOTRADER
    )
    assert autotrader_options.data_dir == Path("data/captures/autotrader")


# --- Observation and validation -------------------------------------------------


def test_observe_bca_cards_merges_responsive_card_variants() -> None:
    observations = observe_bca_cards(make_page(make_stub(), make_card()))

    assert len(observations) == 1
    observation = observations[0]
    assert observation.lot_id == "KS18 ZFM"
    assert observation.make == "MERCEDES-BENZ"
    assert observation.model_variant == "A160"
    assert observation.registration_year == 2018
    assert observation.fuel_type == "Petrol"
    assert observation.transmission == "Auto Clutch"
    assert observation.body_style == "Hatchback"
    assert observation.door_count == 5
    assert observation.mileage == 84_468
    assert observation.cap_clean_price == 7_800
    assert observation.trim == "1.6 SPORT ED.DCT"
    assert observation.clean_condition is True


def test_observe_bca_cards_returns_one_observation_per_vehicle() -> None:
    page = make_page(
        make_stub("KS18 ZFM"),
        make_card(CardSpec(lot_id="KS18 ZFM")),
        make_stub("GL70 XKF"),
        make_card(
            CardSpec(lot_id="GL70 XKF", title="VOLKSWAGEN GOLF 1.5 TSI Hatchback")
        ),
    )
    observations = observe_bca_cards(page)

    assert len(observations) == 2
    assert [observation.lot_id for observation in observations] == [
        "KS18 ZFM",
        "GL70 XKF",
    ]


def test_observation_without_lot_link_is_kept_for_skip_reasons() -> None:
    # A card chunk between two markers that lacks any /lot/ link
    marker = (
        '<a data-testid="card-link-desktop" href="https://www.bca.co.uk/search"></a>'
    )
    nameless_card = make_card(
        CardSpec(lot_link=False, title_href="https://www.bca.co.uk/search")
    )
    page = f"<html><body>{marker}{nameless_card}{marker}</body></html>"

    observations = observe_bca_cards(page)
    assert len(observations) == 1
    unnamed = observations[0]
    assert unnamed.lot_id is None
    result = validate_bca_observation(unnamed)
    assert result.record is None
    assert "missing lot id" in result.reasons


def test_validate_observation_returns_record_when_complete() -> None:
    observations = observe_bca_cards(make_page(make_card()))

    result = validate_bca_observation(observations[0])
    assert result.reasons == ()
    assert result.record is not None
    assert result.record["id"] == "KS18 ZFM"
    assert result.record["cap_clean_price"] == 7_800
    assert result.record["clean_condition"] is True


def test_validation_lists_every_reason_for_a_bad_card() -> None:
    card = make_card(
        CardSpec(mileage=None, cap_clean_price=None, condition_block=False)
    )
    observations = observe_bca_cards(make_page(card))

    result = validate_bca_observation(observations[0])
    assert result.record is None
    assert result.reasons == (
        "missing mileage",
        "missing CAP Clean price",
        "condition not reported on search card",
    )


def test_validation_flags_write_off_and_condition_reasons() -> None:
    card = make_card(CardSpec(write_off=True, condition_block=False))
    observations = observe_bca_cards(make_page(card))

    result = validate_bca_observation(observations[0])
    assert result.record is None
    assert "write-off reported on search card" in result.reasons
    assert "condition not reported on search card" in result.reasons


@pytest.mark.parametrize(
    ("spec", "expected_reason"),
    [
        (CardSpec(mileage=None), "missing mileage"),
        (CardSpec(year=None), "missing registration year"),
        (CardSpec(fuel=None), "missing fuel type"),
        (CardSpec(transmission=None), "missing transmission"),
        (CardSpec(doors=None), "missing door count"),
        (CardSpec(cap_clean_price=None), "missing CAP Clean price"),
        (CardSpec(condition_block=False), "condition not reported on search card"),
    ],
)
def test_validation_reports_each_missing_field(
    spec: CardSpec, expected_reason: str
) -> None:
    observations = observe_bca_cards(make_page(make_card(spec)))

    result = validate_bca_observation(observations[0])
    assert result.record is None
    assert expected_reason in result.reasons


def test_validation_rejects_impossible_values_without_fabrication() -> None:
    cases = [
        (replace(base_observation(), mileage=-1), "invalid mileage"),
        (
            replace(base_observation(), registration_year=1000),
            "invalid registration year",
        ),
        (replace(base_observation(), door_count=0), "invalid door count"),
        (replace(base_observation(), cap_clean_price=-5), "invalid CAP Clean price"),
    ]
    for observation, expected_reason in cases:
        result = validate_bca_observation(observation)
        assert result.record is None
        assert expected_reason in result.reasons


# --- run_capture orchestration --------------------------------------------------


def test_run_capture_keeps_valid_cars_and_logs_skips() -> None:
    options = CaptureOptions(
        search_name="BMW A-Class", movement_limit=3, movement_delay_seconds=1
    )
    good_page = make_page(make_stub(), make_card())
    bad_page = make_page(
        make_stub("GL70 XKF"),
        make_card(CardSpec(lot_id="GL70 XKF", condition_block=False)),
    )
    source = FakePageSource([good_page, bad_page], advance_results=[True, False])

    outcome = run_capture(
        options, source, bca_capture_strategy, hooks=CaptureHooks(pace=no_pace)
    )

    assert outcome.stop_reason == StopReason.NO_FURTHER_PAGES
    assert len(outcome.records) == 1
    assert outcome.records[0]["id"] == "KS18 ZFM"
    assert len(outcome.skipped) == 1
    assert outcome.skipped[0].record_id == "GL70 XKF"
    assert outcome.skipped[0].page_number == 2
    assert outcome.skipped[0].reasons == ("condition not reported on search card",)


def test_run_capture_stops_at_movement_limit() -> None:
    options = CaptureOptions(
        search_name="x", movement_limit=1, movement_delay_seconds=1
    )
    source = FakePageSource([make_page(make_card())])

    outcome = run_capture(
        options, source, bca_capture_strategy, hooks=CaptureHooks(pace=no_pace)
    )

    assert outcome.stop_reason == StopReason.COMPLETED
    assert len(outcome.records) == 1
    assert len(outcome.pages) == 1


def test_run_capture_deduplicates_keeping_latest_version() -> None:
    options = CaptureOptions(
        search_name="x", movement_limit=5, movement_delay_seconds=1
    )
    page_1 = make_page(make_card(CardSpec(lot_id="KS18 ZFM", cap_clean_price=7_800)))
    page_2 = make_page(make_card(CardSpec(lot_id="KS18 ZFM", cap_clean_price=6_900)))
    source = FakePageSource([page_1, page_2], advance_results=[True, False])

    outcome = run_capture(
        options, source, bca_capture_strategy, hooks=CaptureHooks(pace=no_pace)
    )

    assert len(outcome.records) == 1
    assert outcome.records[0]["id"] == "KS18 ZFM"
    assert outcome.records[0]["cap_clean_price"] == 6_900


def test_run_capture_halts_on_challenge_and_keeps_cars_so_far() -> None:
    options = CaptureOptions(
        search_name="x", movement_limit=5, movement_delay_seconds=1
    )
    challenge_page = "<html><title>Attention Required! | Cloudflare</title></html>"
    source = FakePageSource(
        [make_page(make_card()), challenge_page], advance_results=[True]
    )

    outcome = run_capture(
        options, source, bca_capture_strategy, hooks=CaptureHooks(pace=no_pace)
    )

    assert outcome.stop_reason == StopReason.CHALLENGE_DETECTED
    assert outcome.stop_message is not None
    assert len(outcome.records) == 1
    assert len(outcome.pages) == 2


def test_run_capture_stops_cleanly_on_login_redirect_from_source() -> None:
    options = CaptureOptions(
        search_name="x", movement_limit=5, movement_delay_seconds=1
    )
    source = FakePageSource(
        [make_page(make_card())], error_on_read=2, advance_results=[True]
    )

    outcome = run_capture(
        options, source, bca_capture_strategy, hooks=CaptureHooks(pace=no_pace)
    )

    assert outcome.stop_reason == StopReason.CHALLENGE_DETECTED
    assert "session expired" in (outcome.stop_message or "")
    assert len(outcome.records) == 1


def test_run_capture_accepts_custom_challenge_detector() -> None:
    options = CaptureOptions(
        search_name="x", movement_limit=1, movement_delay_seconds=1
    )
    source = FakePageSource([make_page(make_card())])

    outcome = run_capture(
        options,
        source,
        bca_capture_strategy,
        hooks=CaptureHooks(
            pace=no_pace,
            challenge_detector=lambda html: (
                "custom block reason" if "MERCEDES-BENZ" in html else None
            ),
        ),
    )

    assert outcome.stop_reason == StopReason.CHALLENGE_DETECTED
    assert outcome.stop_message == "custom block reason"


# --- save_capture and summary ----------------------------------------------------


def test_save_capture_writes_layout_and_manifest(tmp_path: Path) -> None:
    options = CaptureOptions(
        search_name="BMW A-Class",
        movement_limit=3,
        movement_delay_seconds=1,
        data_dir=tmp_path,
    )
    good_page = make_page(make_stub(), make_card())
    bad_page = make_page(
        make_stub("GL70 XKF"),
        make_card(CardSpec(lot_id="GL70 XKF", condition_block=False)),
    )
    outcome = run_capture(
        options,
        FakePageSource([good_page, bad_page], advance_results=[True, False]),
        bca_capture_strategy,
        hooks=CaptureHooks(pace=no_pace),
    )

    capture_dir = save_capture(outcome, options)

    manifest = json.loads((capture_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["capture_id"] == capture_dir.name
    assert manifest["source"] == "bca"
    assert manifest["search_name"] == "BMW A-Class"
    assert manifest["movement_limit"] == 3
    assert manifest["pages_captured"] == 2
    assert manifest["records_captured"] == 1
    assert manifest["records_skipped"] == 1
    assert manifest["stop_reason"] == "no_further_pages"

    assert (capture_dir / "pages" / "page_01.html").read_text(
        encoding="utf-8"
    ) == good_page
    assert (capture_dir / "pages" / "page_02.html").read_text(
        encoding="utf-8"
    ) == bad_page

    records = json.loads((capture_dir / "records.json").read_text(encoding="utf-8"))
    assert records[0]["id"] == "KS18 ZFM"

    skipped = json.loads((capture_dir / "skipped.json").read_text(encoding="utf-8"))
    assert skipped[0]["record_id"] == "GL70 XKF"
    assert skipped[0]["page_number"] == 2
    assert skipped[0]["reasons"] == ["condition not reported on search card"]


def test_save_capture_never_overwrites(tmp_path: Path) -> None:
    options = CaptureOptions(
        search_name="x", movement_limit=1, movement_delay_seconds=1, data_dir=tmp_path
    )
    outcome = run_capture(
        options,
        FakePageSource([make_page(make_card())]),
        bca_capture_strategy,
        hooks=CaptureHooks(pace=no_pace),
    )

    first_dir = save_capture(outcome, options)
    second_dir = save_capture(outcome, options)

    assert first_dir != second_dir
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(
        [first_dir.name, second_dir.name]
    )


def test_records_json_round_trips_through_acquisition_seam(tmp_path: Path) -> None:
    options = CaptureOptions(
        search_name="x", movement_limit=1, movement_delay_seconds=1, data_dir=tmp_path
    )
    outcome = run_capture(
        options,
        FakePageSource([make_page(make_card())]),
        bca_capture_strategy,
        hooks=CaptureHooks(pace=no_pace),
    )
    capture_dir = save_capture(outcome, options)

    records = json.loads((capture_dir / "records.json").read_text(encoding="utf-8"))
    lots = BcaAcquisition().acquire(records)

    assert len(lots) == 1
    assert lots[0].id.value == "KS18 ZFM"
    assert lots[0].cap_clean_price.pounds == 7_800


def test_print_capture_summary_includes_zero_valid_case(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    options = CaptureOptions(
        search_name="empty search",
        movement_limit=1,
        movement_delay_seconds=1,
        data_dir=tmp_path,
    )
    bad_page = make_page(make_card(CardSpec(condition_block=False)))
    outcome = run_capture(
        options,
        FakePageSource([bad_page]),
        bca_capture_strategy,
        hooks=CaptureHooks(pace=no_pace),
    )
    capture_dir = save_capture(outcome, options)

    print_capture_summary(outcome, capture_dir)
    output = capsys.readouterr().out

    assert "empty search" in output
    assert "Valid records  : 0" in output
    assert "Skipped records: 1" in output


def test_new_capture_ids_are_unique() -> None:
    ids = {new_capture_id() for _ in range(100)}
    assert len(ids) == 100


def test_capture_outcome_is_immutable_and_addressable() -> None:
    outcome = CaptureOutcome(
        search_name="x",
        source=SourceKind.BCA,
        stop_reason=StopReason.COMPLETED,
        stop_message=None,
        pages=("<html></html>",),
        records=(),
        skipped=(
            SkippedCar(record_id="A", page_number=1, card_index=0, reasons=("r",)),
        ),
    )
    assert outcome.stop_reason == StopReason.COMPLETED
    assert outcome.skipped[0].reasons == ("r",)
