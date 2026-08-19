"""Tests for the user-assisted Auto Trader capture command (issue #9)."""

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from car_flip_search import (
    AutoTraderAcquisition,
    AutoTraderCardObservation,
    CaptureHooks,
    CaptureOptions,
    SourceKind,
    StopReason,
    autotrader_capture_strategy,
    observe_autotrader_cards,
    print_capture_summary,
    run_capture,
    save_capture,
    validate_autotrader_observation,
)


@dataclass(frozen=True, kw_only=True)
class ListingSpec:
    """Fixture knobs for one Auto Trader search card modelled on the real DOM."""

    listing_id: str = "202603271072975"
    title: str = "BMW 320d M Sport Saloon"
    price: int | None = 8_995
    mileage: int | None = 117_004
    year: int | None = 2016
    fuel: str | None = "Diesel"
    transmission: str | None = "Automatic"
    doors: int | None = 4
    seller: str | None = "Trade seller"
    subtitle: str | None = "M Sport"


def make_listing_card(spec: ListingSpec | None = None) -> str:
    """One Auto Trader search card built from a ListingSpec."""
    spec = spec or ListingSpec()
    items = []
    if spec.mileage is not None:
        items.append(f"<li>{spec.mileage:,} miles</li>")
    if spec.year is not None:
        items.append(f"<li>{spec.year} (16 reg)</li>")
    if spec.fuel is not None:
        items.append(f"<li>{spec.fuel}</li>")
    if spec.transmission is not None:
        items.append(f"<li>{spec.transmission}</li>")
    if spec.doors is not None:
        items.append(f"<li>{spec.doors} doors</li>")
    if spec.seller is not None:
        items.append(f"<li>{spec.seller}</li>")
    price = f"<p>£{spec.price:,}</p>" if spec.price is not None else ""
    subtitle = (
        f'<p data-testid="search-listing-subtitle">{spec.subtitle}</p>'
        if spec.subtitle is not None
        else ""
    )
    return f"""
    <div data-testid="search-listing">
        <a href="https://www.autotrader.co.uk/car-details/{spec.listing_id}">
            <h3 data-testid="search-listing-title">{spec.title}</h3>
        </a>
        {subtitle}
        {price}
        <ul>{"".join(items)}</ul>
    </div>
    """


def make_page(*cards: str) -> str:
    return "<html><body>" + "".join(cards) + "</body></html>"


class FakePageSource:
    """Deterministic in-memory page source for Auto Trader capture-loop tests."""

    def __init__(self, pages: list[str]) -> None:
        self._pages = pages
        self._reads = 0

    def current_html(self) -> str:
        self._reads += 1
        # Infinite scroll: scrolling past the last known page yields no new
        # content, so the kernel's no-new-results rule ends the run.
        index = min(self._reads - 1, len(self._pages) - 1)
        return self._pages[index]

    def advance(self) -> bool:
        return True


def no_pace(_seconds: float) -> None:
    """No-op pacer so tests never sleep."""


def at_options(tmp_path: Path | None = None, **kwargs: object) -> CaptureOptions:
    return CaptureOptions(
        search_name="BMW 320d",
        source=SourceKind.AUTOTRADER,
        movement_delay_seconds=1,
        data_dir=tmp_path,
        **kwargs,  # type: ignore[arg-type]
    )


# --- Observation and validation -------------------------------------------------


def test_observe_autotrader_cards_returns_one_observation_per_listing() -> None:
    page = make_page(
        make_listing_card(),
        make_listing_card(ListingSpec(listing_id="202603271099999", title="AUDI A4")),
    )

    observations = observe_autotrader_cards(page)

    assert len(observations) == 2
    observation = observations[0]
    assert observation.listing_id == "202603271072975"
    assert observation.make == "BMW"
    assert observation.model_variant == "320d"
    assert observation.registration_year == 2016
    assert observation.fuel_type == "Diesel"
    assert observation.transmission == "Automatic"
    assert observation.body_style == "Saloon"
    assert observation.door_count == 4
    assert observation.mileage == 117_004
    assert observation.cash_price == 8_995
    assert observation.seller_type == "dealer"
    assert observation.trim == "M Sport"
    assert observation.source_url == (
        "https://www.autotrader.co.uk/car-details/202603271072975"
    )


def test_validate_autotrader_observation_returns_record_when_complete() -> None:
    observations = observe_autotrader_cards(make_page(make_listing_card()))

    result = validate_autotrader_observation(observations[0])
    assert result.reasons == ()
    assert result.record is not None
    assert result.record["id"] == "202603271072975"
    assert result.record["cash_price"] == 8_995
    assert result.record["seller_type"] == "dealer"
    assert result.record["source_url"] == (
        "https://www.autotrader.co.uk/car-details/202603271072975"
    )


def test_observation_never_invents_unstated_fields() -> None:
    card = make_listing_card(
        ListingSpec(
            fuel=None,
            transmission=None,
            doors=None,
            seller=None,
            price=None,
            mileage=None,
            year=None,
        )
    )

    observations = observe_autotrader_cards(make_page(card))
    observation = observations[0]

    assert observation.fuel_type is None
    assert observation.transmission is None
    assert observation.door_count is None
    assert observation.seller_type is None
    assert observation.cash_price is None
    assert observation.mileage is None
    assert observation.registration_year is None


def test_validation_saves_record_when_optional_identity_is_unobserved() -> None:
    card = make_listing_card(
        ListingSpec(
            title="Mercedes-Benz A Class",
            subtitle="1.3 A200 AMG Line 7G-DCT Euro 6 (s/s) 5dr",
            fuel=None,
            transmission=None,
            doors=None,
        )
    )

    observation = observe_autotrader_cards(make_page(card))[0]
    result = validate_autotrader_observation(observation)

    assert result.reasons == ()
    assert result.record is not None
    assert result.record["identity"] == {
        "make": "Mercedes-Benz",
        "model_variant": "A",
        "registration_year": 2016,
    }


def test_validation_lists_every_reason_for_a_bad_card() -> None:
    card = make_listing_card(
        ListingSpec(
            mileage=None,
            price=None,
            seller=None,
            fuel=None,
            transmission=None,
            doors=None,
            year=None,
        )
    )
    observations = observe_autotrader_cards(make_page(card))

    result = validate_autotrader_observation(observations[0])
    assert result.record is None
    assert result.reasons == (
        "missing registration year",
        "missing mileage",
        "missing Cash Price",
        "missing Seller Type",
    )


def test_validation_reports_each_missing_field() -> None:
    cases = [
        (ListingSpec(listing_id=""), "missing listing id"),
        (ListingSpec(price=None), "missing Cash Price"),
        (ListingSpec(mileage=None), "missing mileage"),
        (ListingSpec(year=None), "missing registration year"),
        (ListingSpec(seller=None), "missing Seller Type"),
    ]
    for spec, expected_reason in cases:
        observations = observe_autotrader_cards(make_page(make_listing_card(spec)))
        result = validate_autotrader_observation(observations[0])
        assert result.record is None
        assert expected_reason in result.reasons


def test_validation_accepts_private_seller_type() -> None:
    card = make_listing_card(ListingSpec(seller="Private seller"))
    observations = observe_autotrader_cards(make_page(card))

    result = validate_autotrader_observation(observations[0])
    assert result.reasons == ()
    assert result.record is not None
    assert result.record["seller_type"] == "private"


def test_validation_rejects_invalid_seller_type() -> None:
    observation = AutoTraderCardObservation(
        listing_id="202603271072975",
        make="BMW",
        model_variant="320d",
        registration_year=2016,
        fuel_type="Diesel",
        transmission="Automatic",
        body_style="Saloon",
        door_count=4,
        mileage=117_004,
        cash_price=8_995,
        seller_type="auctioneer",
    )

    result = validate_autotrader_observation(observation)
    assert result.record is None
    assert "invalid Seller Type" in result.reasons


# --- CaptureOptions ---------------------------------------------------------------


def test_autotrader_options_reject_zero_move_delay() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        CaptureOptions(
            search_name="x",
            source=SourceKind.AUTOTRADER,
            movement_delay_seconds=0,
        )


def test_autotrader_options_default_data_dir() -> None:
    options = CaptureOptions(search_name="x", source=SourceKind.AUTOTRADER)
    assert options.movement_limit == 5
    assert options.data_dir == Path("data/captures/autotrader")


# --- run_capture orchestration ----------------------------------------------------


def test_run_capture_deduplicates_by_listing_id_keeping_latest(tmp_path: Path) -> None:
    options = at_options(tmp_path)
    page_1 = make_page(make_listing_card(ListingSpec(price=8_995)))
    page_2 = make_page(make_listing_card(ListingSpec(price=7_500)))
    source = FakePageSource([page_1, page_2])

    outcome = run_capture(
        options, source, autotrader_capture_strategy, hooks=CaptureHooks(pace=no_pace)
    )

    assert len(outcome.records) == 1
    assert outcome.records[0]["id"] == "202603271072975"
    assert outcome.records[0]["cash_price"] == 7_500


def test_run_capture_stops_early_after_two_no_new_movements(tmp_path: Path) -> None:
    options = at_options(tmp_path)
    page = make_page(
        make_listing_card(),
        make_listing_card(ListingSpec(listing_id="202603271099999")),
    )
    source = FakePageSource([page, page, page, page])

    outcome = run_capture(
        options, source, autotrader_capture_strategy, hooks=CaptureHooks(pace=no_pace)
    )

    assert outcome.stop_reason == StopReason.NO_NEW_RESULTS
    assert len(outcome.pages) == 3
    assert len(outcome.records) == 2
    assert "no new listing IDs" in (outcome.stop_message or "")


def test_run_capture_does_not_stop_early_on_skipped_new_listings(
    tmp_path: Path,
) -> None:
    """A new-but-skipped listing still counts as a newly observed ID."""
    options = at_options(tmp_path)
    valid_page = make_page(make_listing_card())
    skipped_page = make_page(
        make_listing_card(
            ListingSpec(listing_id="202603271099999", price=None, seller=None)
        )
    )
    source = FakePageSource(
        [valid_page, skipped_page, skipped_page, skipped_page, skipped_page]
    )

    outcome = run_capture(
        options, source, autotrader_capture_strategy, hooks=CaptureHooks(pace=no_pace)
    )

    # Page 2 introduces a new listing ID (skipped, not captured), so the early
    # stop needs two further no-new movements after it: pages 3 and 4.
    assert outcome.stop_reason == StopReason.NO_NEW_RESULTS
    assert len(outcome.pages) == 4
    assert len(outcome.records) == 1
    assert len(outcome.skipped) == 3


def test_run_capture_stops_at_movement_limit(tmp_path: Path) -> None:
    options = at_options(tmp_path, movement_limit=2)
    page = make_page(make_listing_card())
    source = FakePageSource([page, page])

    outcome = run_capture(
        options, source, autotrader_capture_strategy, hooks=CaptureHooks(pace=no_pace)
    )

    assert outcome.stop_reason == StopReason.COMPLETED
    assert len(outcome.pages) == 2
    assert len(outcome.records) == 1


def test_run_capture_halts_on_challenge_and_keeps_records_so_far(
    tmp_path: Path,
) -> None:
    options = at_options(tmp_path)
    challenge_page = "<html><title>Access Denied - CAPTCHA</title></html>"
    source = FakePageSource([make_page(make_listing_card()), challenge_page])

    outcome = run_capture(
        options, source, autotrader_capture_strategy, hooks=CaptureHooks(pace=no_pace)
    )

    assert outcome.stop_reason == StopReason.CHALLENGE_DETECTED
    assert len(outcome.records) == 1
    assert len(outcome.pages) == 2


def test_run_capture_logs_skips_for_incomplete_listings(tmp_path: Path) -> None:
    options = at_options(tmp_path, movement_limit=1)
    bad_card = make_listing_card(ListingSpec(price=None, seller=None))
    source = FakePageSource([make_page(bad_card)])

    outcome = run_capture(
        options, source, autotrader_capture_strategy, hooks=CaptureHooks(pace=no_pace)
    )

    assert outcome.stop_reason == StopReason.COMPLETED
    assert len(outcome.records) == 0
    assert len(outcome.skipped) == 1
    assert outcome.skipped[0].record_id == "202603271072975"
    assert "missing Cash Price" in outcome.skipped[0].reasons
    assert "missing Seller Type" in outcome.skipped[0].reasons


# --- save_capture and summary -----------------------------------------------------


def test_save_capture_writes_autotrader_layout(tmp_path: Path) -> None:
    options = at_options(tmp_path, movement_limit=1)
    bad_card = make_listing_card(ListingSpec(price=None, seller=None))
    source = FakePageSource([make_page(make_listing_card(), bad_card)])

    outcome = run_capture(
        options, source, autotrader_capture_strategy, hooks=CaptureHooks(pace=no_pace)
    )
    capture_dir = save_capture(outcome, options)

    manifest = json.loads((capture_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["capture_id"] == capture_dir.name
    assert manifest["source"] == "autotrader"
    assert manifest["search_name"] == "BMW 320d"
    assert manifest["movement_limit"] == 1
    assert manifest["movement_delay_seconds"] == 1
    assert manifest["pages_captured"] == 1
    assert manifest["records_captured"] == 1
    assert manifest["records_skipped"] == 1
    assert manifest["stop_reason"] == "completed"

    records = json.loads((capture_dir / "records.json").read_text(encoding="utf-8"))
    assert records[0]["id"] == "202603271072975"

    skipped = json.loads((capture_dir / "skipped.json").read_text(encoding="utf-8"))
    assert skipped[0]["record_id"] == "202603271072975"
    assert skipped[0]["reasons"] == ["missing Cash Price", "missing Seller Type"]

    assert (capture_dir / "pages" / "page_01.html").exists()


def test_autotrader_records_round_trip_through_acquisition_seam(
    tmp_path: Path,
) -> None:
    options = at_options(tmp_path, movement_limit=1)
    source = FakePageSource([make_page(make_listing_card())])

    outcome = run_capture(
        options, source, autotrader_capture_strategy, hooks=CaptureHooks(pace=no_pace)
    )
    capture_dir = save_capture(outcome, options)

    records = json.loads((capture_dir / "records.json").read_text(encoding="utf-8"))
    snapshot = AutoTraderAcquisition().acquire_snapshot(records)

    assert len(snapshot.listings) == 1
    assert snapshot.listings[0].id.value == "202603271072975"
    assert snapshot.listings[0].cash_price.pounds == 8_995
    assert snapshot.listings[0].seller_type.value == "dealer"


def test_print_capture_summary_includes_zero_valid_case(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    options = at_options(tmp_path, movement_limit=1)
    bad_card = make_listing_card(ListingSpec(price=None, seller=None))
    source = FakePageSource([make_page(bad_card)])

    outcome = run_capture(
        options, source, autotrader_capture_strategy, hooks=CaptureHooks(pace=no_pace)
    )
    capture_dir = save_capture(outcome, options)

    print_capture_summary(outcome, capture_dir)
    output = capsys.readouterr().out

    assert "Auto Trader capture saved" in output
    assert "Valid records  : 0" in output
    assert "Skipped records: 1" in output
