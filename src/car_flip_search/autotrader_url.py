"""Build scoped Auto Trader search URLs for vehicle market analysis."""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any, TypedDict
from urllib.parse import urlencode

from .source_acquisition import normalize_model_variant

DEFAULT_POSTCODE = "NG2 3JW"
DEFAULT_SORT = "price-asc"
DEFAULT_SELLER_TYPES: tuple[str, ...] = ("private", "trade")
DEFAULT_CHANNEL = "cars"
AUTOTRADER_SEARCH_BASE_URL = "https://www.autotrader.co.uk/car-search"


class AutoTraderSearchParams(TypedDict, total=False):
    """Sparse parameters used to build a scoped Auto Trader search URL."""

    make: str | None
    model: str | None
    year: int | None
    year_from: int | None
    year_to: int | None
    mileage: int | None
    min_mileage: int | None
    max_mileage: int | None
    engine_size: float | str | None
    min_engine_size: float | str | None
    max_engine_size: float | str | None
    fuel_type: str | None
    transmission: str | None
    body_types: Sequence[str] | None
    trim: str | None
    postcode: str | None
    sort: str | None
    seller_types: Sequence[str] | None
    channel: str | None
    exclude_writeoff_categories: bool | None


def _format_engine_size(value: float | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return f"{float(value):.1f}"
    val_str = str(value).strip()
    if not val_str:
        return None
    try:
        return f"{float(val_str):.1f}"
    except ValueError:
        return val_str


def build_autotrader_search_url(
    params: AutoTraderSearchParams | None = None,
    **kwargs: Any,
) -> str:
    """Construct an Auto Trader search URL from search parameters."""
    merged: AutoTraderSearchParams = dict(params or {})
    merged.update(kwargs)  # type: ignore[typeddict-item]

    postcode_raw = merged.get("postcode")
    resolved_postcode = (
        postcode_raw
        if postcode_raw is not None
        else os.environ.get("CAR_FLIP_POSTCODE", DEFAULT_POSTCODE)
    ).strip()

    raw_make = merged.get("make")
    raw_model = merged.get("model")
    resolved_make = raw_make.strip() if raw_make else None
    resolved_model = raw_model.strip() if raw_model else None
    if resolved_make and resolved_model:
        normalized = normalize_model_variant(resolved_make, resolved_model)
        if normalized:
            resolved_model = normalized

    year_val = merged.get("year")
    year_from_val = merged.get("year_from")
    year_to_val = merged.get("year_to")
    resolved_year_from = year_from_val if year_from_val is not None else year_val
    resolved_year_to = year_to_val if year_to_val is not None else year_val

    mileage_val = merged.get("mileage")
    resolved_min_mileage = merged.get("min_mileage")
    resolved_max_mileage = merged.get("max_mileage")
    if mileage_val is not None:
        if resolved_min_mileage is None:
            resolved_min_mileage = max(0, int(mileage_val) - 15000)
        if resolved_max_mileage is None:
            resolved_max_mileage = int(mileage_val) + 15000

    engine_val = merged.get("engine_size")
    min_engine_val = merged.get("min_engine_size")
    max_engine_val = merged.get("max_engine_size")
    resolved_min_engine = _format_engine_size(
        min_engine_val if min_engine_val is not None else engine_val
    )
    resolved_max_engine = _format_engine_size(
        max_engine_val if max_engine_val is not None else engine_val
    )

    query_items: list[tuple[str, Any]] = []

    trim_val = merged.get("trim")
    if trim_val:
        query_items.append(("aggregatedTrim", trim_val.strip()))

    body_types_val = merged.get("body_types")
    if body_types_val:
        for bt in body_types_val:
            if bt and str(bt).strip():
                query_items.append(("body-type", str(bt).strip()))

    channel_val = merged.get("channel", DEFAULT_CHANNEL)
    if channel_val:
        query_items.append(("channel", channel_val.strip()))

    exclude_writeoff = merged.get("exclude_writeoff_categories", True)
    if exclude_writeoff:
        query_items.append(("exclude-writeoff-categories", "on"))

    fuel_val = merged.get("fuel_type")
    if fuel_val:
        query_items.append(("fuel-type", fuel_val.strip()))

    if resolved_make:
        query_items.append(("make", resolved_make))

    if resolved_max_engine:
        query_items.append(("maximum-badge-engine-size", resolved_max_engine))

    if resolved_max_mileage is not None:
        query_items.append(("maximum-mileage", int(resolved_max_mileage)))

    if resolved_min_engine:
        query_items.append(("minimum-badge-engine-size", resolved_min_engine))

    if resolved_min_mileage is not None:
        query_items.append(("minimum-mileage", int(resolved_min_mileage)))

    if resolved_model:
        query_items.append(("model", resolved_model))

    if resolved_postcode:
        query_items.append(("postcode", resolved_postcode))

    seller_types_val = merged.get("seller_types", DEFAULT_SELLER_TYPES)
    if seller_types_val:
        for st in seller_types_val:
            if st and str(st).strip():
                query_items.append(("seller-type", str(st).strip()))

    sort_val = merged.get("sort", DEFAULT_SORT)
    if sort_val:
        query_items.append(("sort", sort_val.strip()))

    trans_val = merged.get("transmission")
    if trans_val:
        query_items.append(("transmission", trans_val.strip()))

    if resolved_year_from is not None:
        query_items.append(("year-from", int(resolved_year_from)))

    if resolved_year_to is not None:
        query_items.append(("year-to", int(resolved_year_to)))

    query_items.sort(key=lambda item: item[0])
    encoded_query = urlencode(query_items)
    return f"{AUTOTRADER_SEARCH_BASE_URL}?{encoded_query}"
