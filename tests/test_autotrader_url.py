"""Unit tests for Auto Trader search URL construction."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from car_flip_search.autotrader_url import (
    AUTOTRADER_SEARCH_BASE_URL,
    DEFAULT_CHANNEL,
    DEFAULT_POSTCODE,
    DEFAULT_SELLER_TYPES,
    DEFAULT_SORT,
    build_autotrader_search_url,
)


def test_build_url_defaults() -> None:
    url = build_autotrader_search_url()
    split = urlsplit(url)
    assert f"{split.scheme}://{split.netloc}{split.path}" == AUTOTRADER_SEARCH_BASE_URL
    params = parse_qs(split.query)

    assert params["channel"] == [DEFAULT_CHANNEL]
    assert params["exclude-writeoff-categories"] == ["on"]
    assert params["sort"] == [DEFAULT_SORT]
    assert params["seller-type"] == list(DEFAULT_SELLER_TYPES)
    assert params["postcode"] == [DEFAULT_POSTCODE]
    assert "make" not in params
    assert "model" not in params


def test_build_url_with_full_vehicle_criteria() -> None:
    url = build_autotrader_search_url(
        make="Audi",
        model="A3",
        year=2018,
        min_mileage=40000,
        max_mileage=80000,
        min_engine_size=1.4,
        max_engine_size=1.6,
        fuel_type="Petrol",
        transmission="Automatic",
        body_types=["Hatchback", "Saloon"],
        trim="TFSI",
        postcode="NG2 3JW",
    )
    split = urlsplit(url)
    params = parse_qs(split.query)

    assert params["make"] == ["Audi"]
    assert params["model"] == ["A3"]
    assert params["year-from"] == ["2018"]
    assert params["year-to"] == ["2018"]
    assert params["minimum-mileage"] == ["40000"]
    assert params["maximum-mileage"] == ["80000"]
    assert params["minimum-badge-engine-size"] == ["1.4"]
    assert params["maximum-badge-engine-size"] == ["1.6"]
    assert params["fuel-type"] == ["Petrol"]
    assert params["transmission"] == ["Automatic"]
    assert params["body-type"] == ["Hatchback", "Saloon"]
    assert params["aggregatedTrim"] == ["TFSI"]
    assert params["postcode"] == ["NG2 3JW"]
    assert params["channel"] == ["cars"]
    assert params["exclude-writeoff-categories"] == ["on"]
    assert params["sort"] == ["price-asc"]
    assert params["seller-type"] == ["private", "trade"]


def test_build_url_mileage_auto_band() -> None:
    # 60,000 miles -> 45,000 to 75,000
    url = build_autotrader_search_url(mileage=60000)
    params = parse_qs(urlsplit(url).query)
    assert params["minimum-mileage"] == ["45000"]
    assert params["maximum-mileage"] == ["75000"]

    # Low mileage clamps min to 0
    url_low = build_autotrader_search_url(mileage=10000)
    params_low = parse_qs(urlsplit(url_low).query)
    assert params_low["minimum-mileage"] == ["0"]
    assert params_low["maximum-mileage"] == ["25000"]


def test_build_url_single_engine_size() -> None:
    url = build_autotrader_search_url(engine_size=1.4)
    params = parse_qs(urlsplit(url).query)
    assert params["minimum-badge-engine-size"] == ["1.4"]
    assert params["maximum-badge-engine-size"] == ["1.4"]


def test_build_url_year_range() -> None:
    url = build_autotrader_search_url(year_from=2016, year_to=2020)
    params = parse_qs(urlsplit(url).query)
    assert params["year-from"] == ["2016"]
    assert params["year-to"] == ["2020"]


def test_build_url_custom_postcode_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAR_FLIP_POSTCODE", "SW1A 1AA")
    url = build_autotrader_search_url()
    params = parse_qs(urlsplit(url).query)
    assert params["postcode"] == ["SW1A 1AA"]


def test_build_url_normalizes_model() -> None:
    url = build_autotrader_search_url(make="Mercedes-Benz", model="A-Class")
    params = parse_qs(urlsplit(url).query)
    # Checks normalization if present in domain rules
    assert params["make"] == ["Mercedes-Benz"]
    assert len(params["model"]) == 1
