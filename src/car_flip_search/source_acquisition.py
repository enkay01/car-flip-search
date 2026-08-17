"""Parse BCA and Auto Trader payloads into complete domain records at the acquisition seam."""

import contextlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import TypedDict
from urllib.parse import unquote

from .model import (
    AuctionLot,
    AuctionLotId,
    AutoTraderListing,
    AutoTraderListingId,
    CapCleanPrice,
    CashPrice,
    CoreVehicleIdentity,
    MarketSnapshot,
    SellerType,
)


class BcaRawIdentity(TypedDict, total=False):
    """Raw BCA identity fields; missing fields are rejected during parsing."""

    make: str
    model_variant: str
    registration_year: int
    fuel_type: str
    transmission: str
    body_style: str
    door_count: int


class BcaRawRecord(TypedDict, total=False):
    """External BCA payload, not a partially valid domain object."""

    id: str
    identity: BcaRawIdentity
    mileage: int
    cap_clean_price: int
    clean_condition: bool
    write_off_reported: bool
    accident_damage_reported: bool
    trim: str


class BcaAcquisition:
    """Parse discoverable BCA payloads into strict Auction Lot inputs."""

    def acquire(self, records: Iterable[BcaRawRecord]) -> tuple[AuctionLot, ...]:
        acquired_lots: list[AuctionLot] = []
        try:
            for record in records:
                auction_lot = _parse_bca_record(record)
                if auction_lot is not None:
                    acquired_lots.append(auction_lot)
        except TypeError:
            return ()
        return tuple(acquired_lots)


class AutoTraderRawIdentity(TypedDict, total=False):
    """Raw Auto Trader identity fields; missing fields are rejected during parsing."""

    make: str
    model_variant: str
    registration_year: int
    fuel_type: str
    transmission: str
    body_style: str
    door_count: int


class AutoTraderRawRecord(TypedDict, total=False):
    """External Auto Trader payload, not a partially valid domain object."""

    id: str
    identity: AutoTraderRawIdentity
    mileage: int
    cash_price: int
    seller_type: str
    trim: str


class AutoTraderAcquisition:
    """Parse discoverable Auto Trader payloads into strict market inputs."""

    def acquire(
        self, records: Iterable[AutoTraderRawRecord]
    ) -> tuple[AutoTraderListing, ...]:
        acquired_listings: list[AutoTraderListing] = []
        try:
            for record in records:
                listing = _parse_autotrader_record(record)
                if listing is not None:
                    acquired_listings.append(listing)
        except TypeError:
            return ()
        return tuple(acquired_listings)

    def acquire_snapshot(
        self, records: Iterable[AutoTraderRawRecord]
    ) -> MarketSnapshot:
        return MarketSnapshot(self.acquire(records))


class ManualBcaImporter:
    """Import BCA records from supported manual exports, JSON feeds, or saved HTML pages."""

    def __init__(self, acquisition: BcaAcquisition | None = None) -> None:
        self._acquisition = acquisition or BcaAcquisition()

    def import_from_records(
        self, records: Iterable[BcaRawRecord]
    ) -> tuple[AuctionLot, ...]:
        return self._acquisition.acquire(records)

    def import_from_json(self, json_data: str) -> tuple[AuctionLot, ...]:
        try:
            parsed = json.loads(json_data)
            return self._acquisition.acquire(parsed)
        except (json.JSONDecodeError, TypeError, ValueError):
            return ()

    def import_from_html(self, html_content: str) -> tuple[AuctionLot, ...]:
        records = _parse_bca_html(html_content)
        return self._acquisition.acquire(records)

    def import_from_html_file(self, file_path: str) -> tuple[AuctionLot, ...]:
        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()
            return self.import_from_html(content)
        except (OSError, UnicodeDecodeError):
            return ()


class ManualAutoTraderImporter:
    """Import Auto Trader records from supported manual exports or JSON feeds."""

    def __init__(self, acquisition: AutoTraderAcquisition | None = None) -> None:
        self._acquisition = acquisition or AutoTraderAcquisition()

    def import_from_records(
        self, records: Iterable[AutoTraderRawRecord]
    ) -> MarketSnapshot:
        return self._acquisition.acquire_snapshot(records)

    def import_from_json(self, json_data: str) -> MarketSnapshot:
        try:
            parsed = json.loads(json_data)
            return self._acquisition.acquire_snapshot(parsed)
        except (json.JSONDecodeError, TypeError, ValueError):
            return MarketSnapshot(())

    def import_from_html(self, html_content: str) -> MarketSnapshot:
        records = _parse_autotrader_html(html_content)
        return self._acquisition.acquire_snapshot(records)

    def import_from_html_file(self, file_path: str) -> MarketSnapshot:
        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()
            return self.import_from_html(content)
        except (OSError, UnicodeDecodeError):
            return MarketSnapshot(())


def _parse_bca_record(record: BcaRawRecord) -> AuctionLot | None:
    try:
        if not _is_bca_condition_eligible(record):
            return None
        return AuctionLot(
            id=AuctionLotId(record["id"]),
            identity=CoreVehicleIdentity(**record["identity"]),
            mileage=record["mileage"],
            cap_clean_price=CapCleanPrice(record["cap_clean_price"]),
            trim=record.get("trim"),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _is_bca_condition_eligible(record: BcaRawRecord) -> bool:
    """Accept only known-clean lots with no reported write-off or accident damage."""

    return (
        record["clean_condition"] is True
        and record["write_off_reported"] is False
        and record["accident_damage_reported"] is False
    )


def _parse_autotrader_record(record: AutoTraderRawRecord) -> AutoTraderListing | None:
    try:
        raw_seller = record["seller_type"]
        if raw_seller not in ("private", "dealer"):
            return None
        return AutoTraderListing(
            id=AutoTraderListingId(record["id"]),
            identity=CoreVehicleIdentity(**record["identity"]),
            mileage=record["mileage"],
            cash_price=CashPrice(record["cash_price"]),
            seller_type=SellerType(raw_seller),
            trim=record.get("trim"),
        )
    except (KeyError, TypeError, ValueError):
        return None


class _BcaHtmlTagParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[BcaRawRecord] = []
        self.script_json_blocks: list[str] = []
        self._in_json_script = False
        self._current_script: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict: dict[str, str] = {}
        for key, val in attrs:
            if val is not None:
                attr_dict[key.lower()] = val

        if tag.lower() == "script":
            script_type = attr_dict.get("type", "").lower()
            if "json" in script_type:
                self._in_json_script = True
                self._current_script = []
            return

        lot_id = (
            attr_dict.get("data-lot-id")
            or attr_dict.get("data-vrm")
            or attr_dict.get("data-id")
        )
        if lot_id:
            with contextlib.suppress(KeyError, ValueError):
                record: BcaRawRecord = {
                    "id": str(lot_id),
                    "mileage": int(attr_dict["data-mileage"]),
                    "cap_clean_price": int(attr_dict["data-cap-clean-price"]),
                    "clean_condition": attr_dict.get(
                        "data-clean-condition", "true"
                    ).lower()
                    == "true",
                    "write_off_reported": attr_dict.get(
                        "data-write-off-reported", "false"
                    ).lower()
                    == "true",
                    "accident_damage_reported": attr_dict.get(
                        "data-accident-damage-reported", "false"
                    ).lower()
                    == "true",
                }
                trim_val = attr_dict.get("data-trim")
                if trim_val:
                    record["trim"] = trim_val
                record["identity"] = {
                    "make": str(attr_dict["data-make"]),
                    "model_variant": str(attr_dict["data-model-variant"]),
                    "registration_year": int(attr_dict["data-registration-year"]),
                    "fuel_type": str(attr_dict["data-fuel-type"]),
                    "transmission": str(attr_dict["data-transmission"]),
                    "body_style": str(attr_dict["data-body-style"]),
                    "door_count": int(attr_dict["data-door-count"]),
                }
                self.records.append(record)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._in_json_script:
            self._in_json_script = False
            self.script_json_blocks.append("".join(self._current_script))
            self._current_script = []

    def handle_data(self, data: str) -> None:
        if self._in_json_script:
            self._current_script.append(data)


def _parse_bca_html(html_content: str) -> tuple[BcaRawRecord, ...]:
    parser = _BcaHtmlTagParser()
    with contextlib.suppress(TypeError, ValueError, AssertionError):
        parser.feed(html_content)

    all_records = list(parser.records)
    for script_json in parser.script_json_blocks:
        extracted = _extract_bca_records_from_json_string(script_json)
        all_records.extend(extracted)

    # Extract cards from rendered BCA HTML search result pages. Invalid cards
    # are discarded silently here; the capture command surfaces skip reasons.
    for observation in observe_bca_cards(html_content):
        result = validate_bca_observation(observation)
        if result.record is not None:
            all_records.append(result.record)

    return tuple(all_records)


@dataclass(frozen=True, kw_only=True)
class BcaCardObservation:
    """Every field visible on one BCA search card; None means not observed.

    Nothing here is invented: each attribute is populated only from content
    present on the page, so validation can distinguish a missing field from a
    fabricated default.
    """

    lot_id: str | None = None
    make: str | None = None
    model_variant: str | None = None
    registration_year: int | None = None
    fuel_type: str | None = None
    transmission: str | None = None
    body_style: str | None = None
    door_count: int | None = None
    mileage: int | None = None
    cap_clean_price: int | None = None
    clean_condition: bool | None = None
    write_off_reported: bool | None = None
    accident_damage_reported: bool | None = None
    trim: str | None = None


_WRITE_OFF_MARKERS = (r"\bcat\s?[absn]\b", r"write-?off\b", r"written off")
_ACCIDENT_DAMAGE_MARKERS = (
    r"accident damage",
    r"accident history",
    r"previous accident",
)
_BCA_BODY_STYLE_ALIASES = {
    "cabriolet": "Cabriolet",
    "convertible": "Convertible",
    "coupe": "Coupe",
    "estate": "Estate",
    "hatchback": "Hatchback",
    "mpv": "MPV",
    "panelvan": "PanelVan",
    "pickup": "Pick-up",
    "roadster": "Roadster",
    "saloon": "Saloon",
    "stationwagon": "StationWagon",
    "suv": "SUV",
    "van": "Van",
}


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def _non_blank(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def observe_bca_cards(html_content: str) -> tuple[BcaCardObservation, ...]:
    """Extract one observation per vehicle from a BCA search results page.

    Each vehicle renders as a link stub and a full card under the same
    card-link-desktop anchor; per-vehicle observations are merged so a vehicle
    is never observed twice within one page.
    """
    card_chunks = re.split(r'data-testid=["\']card-link-desktop["\']', html_content)
    if len(card_chunks) <= 1:
        return ()

    observed = [
        observation
        for chunk in card_chunks[1:]
        if (observation := _observe_bca_card_chunk(chunk)) is not None
    ]

    merged: dict[str, BcaCardObservation] = {}
    order: list[str] = []
    for observation in observed:
        if observation.lot_id is None:
            continue
        if observation.lot_id in merged:
            merged[observation.lot_id] = _merge_bca_observations(
                merged[observation.lot_id], observation
            )
        else:
            merged[observation.lot_id] = observation
            order.append(observation.lot_id)

    named = tuple(merged[lid] for lid in order)
    unnamed = tuple(obs for obs in observed if obs.lot_id is None)
    return named + unnamed


def _observe_bca_card_chunk(chunk: str) -> BcaCardObservation | None:
    """Build an observation from one card chunk; None when the chunk is not a card."""
    is_card = (
        'data-testid="condition-report-icon"' in chunk
        or "CAP Clean</p>" in chunk
        or "VehicleResultCardDesktop__StyledLink" in chunk
        or "/lot/" in chunk
    )
    if not is_card:
        return None

    lot_match = re.search(r"/lot/([^?\"'/]+)", chunk)
    lot_id = unquote(lot_match.group(1)).strip() if lot_match else None

    title_match = re.search(
        r"VehicleResultCardDesktop__StyledLink[^\"]*\"[^>]*>([^<]+)</a>", chunk
    )
    title = title_match.group(1).strip() if title_match else None

    cap_match = re.search(r"CAP Clean</p>\s*<p[^>]*>£([\d,]+)</p>", chunk)
    cap_clean_price = int(cap_match.group(1).replace(",", "")) if cap_match else None

    make, model_variant, body_style, trim = _parse_bca_title(title)

    items = re.findall(r"<p [^>]*>([^<]+)</p>", chunk)
    fields = _observe_card_spec_fields(items)

    condition_block_present = 'data-testid="condition-report-icon"' in chunk
    return BcaCardObservation(
        lot_id=lot_id,
        make=make,
        model_variant=model_variant,
        registration_year=fields.get("registration_year"),
        fuel_type=fields.get("fuel_type"),
        transmission=fields.get("transmission"),
        body_style=body_style,
        door_count=fields.get("door_count"),
        mileage=fields.get("mileage"),
        cap_clean_price=cap_clean_price,
        clean_condition=True if condition_block_present else None,
        write_off_reported=_contains_any(chunk, _WRITE_OFF_MARKERS),
        accident_damage_reported=_contains_any(chunk, _ACCIDENT_DAMAGE_MARKERS),
        trim=trim,
    )


def _parse_bca_title(
    title: str | None,
) -> tuple[str | None, str | None, str | None, str | None]:
    """Parse identity only when the title has a known body-style suffix.

    BCA's rendered cards expose the vehicle title as plain text rather than
    separate identity attributes.  The observed search pages use a one-token
    make, a model variant, optional trim text, and a final body-style token.
    An arbitrary final token is not evidence of a body style, so titles without
    a recognized suffix remain incomplete and are rejected by validation.
    """
    if not title:
        return None, None, None, None

    parts = title.split()
    if not parts:
        return None, None, None, None

    make = parts[0]
    model_variant = parts[1] if len(parts) > 1 else None
    body_style: str | None = None
    body_style_start = len(parts)

    for width in (2, 1):
        if len(parts) < width:
            continue
        candidate = " ".join(parts[-width:])
        key = re.sub(r"[^a-z0-9]", "", candidate.casefold())
        if key in _BCA_BODY_STYLE_ALIASES:
            body_style = _BCA_BODY_STYLE_ALIASES[key]
            body_style_start = len(parts) - width
            break

    trim = (
        " ".join(parts[2:body_style_start])
        if body_style is not None and body_style_start > 2
        else None
    )
    return make, model_variant, body_style, trim


def _merge_bca_observations(
    left: BcaCardObservation, right: BcaCardObservation
) -> BcaCardObservation:
    """Merge two observations of the same lot, preferring observed values."""
    return BcaCardObservation(
        lot_id=left.lot_id,
        make=left.make or right.make,
        model_variant=left.model_variant or right.model_variant,
        registration_year=left.registration_year or right.registration_year,
        fuel_type=left.fuel_type or right.fuel_type,
        transmission=left.transmission or right.transmission,
        body_style=left.body_style or right.body_style,
        door_count=left.door_count or right.door_count,
        mileage=left.mileage or right.mileage,
        cap_clean_price=left.cap_clean_price or right.cap_clean_price,
        clean_condition=left.clean_condition or right.clean_condition,
        write_off_reported=left.write_off_reported or right.write_off_reported,
        accident_damage_reported=(
            left.accident_damage_reported or right.accident_damage_reported
        ),
        trim=left.trim or right.trim,
    )


class _CardSpecFields(TypedDict, total=False):
    mileage: int
    registration_year: int
    fuel_type: str
    transmission: str
    door_count: int


def _observe_card_spec_fields(items: list[str]) -> _CardSpecFields:
    """Extract each spec field independently so a missing field hides nothing."""
    fields: _CardSpecFields = {}
    for item in items:
        if "mileage" not in fields:
            mileage_match = re.search(r"([\d,]+)\s*miles", item, re.IGNORECASE)
            if mileage_match:
                fields["mileage"] = int(mileage_match.group(1).replace(",", ""))
        if "registration_year" not in fields:
            year_match = re.search(r"\b(19\d\d|20\d\d)\b", item)
            if year_match and "reg" in item.lower():
                fields["registration_year"] = int(year_match.group(1))
        item_lower = item.lower()
        if "fuel_type" not in fields and item_lower in (
            "petrol",
            "diesel",
            "electric",
            "hybrid",
            "petrol/electric",
            "petrol plug-in hybrid",
            "diesel plug-in hybrid",
        ):
            fields["fuel_type"] = item
        if "transmission" not in fields and item_lower in (
            "manual",
            "automatic",
            "auto clutch",
            "auto/manual mode",
            "cvt",
            "cvt/manual mode",
        ):
            fields["transmission"] = item
        if "door_count" not in fields:
            door_match = re.search(r"(\d+)\s*doors", item, re.IGNORECASE)
            if door_match:
                fields["door_count"] = int(door_match.group(1))
    return fields


@dataclass(frozen=True)
class BcaValidationResult:
    """Outcome of validating one observed card: its record and every skip reason."""

    record: BcaRawRecord | None
    reasons: tuple[str, ...]


def validate_bca_observation(
    observation: BcaCardObservation,
) -> BcaValidationResult:
    """Validate one observed card into a record plus every reason it is skipped.

    Missing or invalid required fields yield skip reasons; the tool never
    invents identity, mileage, CAP Clean Price, or condition values.
    """
    reasons: list[str] = []

    lot_id = _non_blank(observation.lot_id)
    if lot_id is None:
        reasons.append("missing lot id")
    make = _non_blank(observation.make)
    if make is None:
        reasons.append("missing make")
    model_variant = _non_blank(observation.model_variant)
    if model_variant is None:
        reasons.append("missing model variant")
    fuel_type = _non_blank(observation.fuel_type)
    if fuel_type is None:
        reasons.append("missing fuel type")
    transmission = _non_blank(observation.transmission)
    if transmission is None:
        reasons.append("missing transmission")
    body_style = _non_blank(observation.body_style)
    if body_style is None:
        reasons.append("missing body style")

    if observation.registration_year is None:
        reasons.append("missing registration year")
    elif not 1886 <= observation.registration_year <= 9999:
        reasons.append("invalid registration year")
    if observation.door_count is None:
        reasons.append("missing door count")
    elif observation.door_count < 1:
        reasons.append("invalid door count")
    if observation.mileage is None:
        reasons.append("missing mileage")
    elif observation.mileage < 0:
        reasons.append("invalid mileage")
    if observation.cap_clean_price is None:
        reasons.append("missing CAP Clean price")
    elif observation.cap_clean_price < 0:
        reasons.append("invalid CAP Clean price")
    if observation.clean_condition is None:
        reasons.append("condition not reported on search card")
    elif observation.clean_condition is False:
        reasons.append("condition not clean")
    if observation.write_off_reported is True:
        reasons.append("write-off reported on search card")
    if observation.accident_damage_reported is True:
        reasons.append("accident damage reported on search card")

    if reasons:
        return BcaValidationResult(record=None, reasons=tuple(reasons))

    record: BcaRawRecord = {
        "id": lot_id,
        "identity": {
            "make": make,
            "model_variant": model_variant,
            "registration_year": observation.registration_year,
            "fuel_type": fuel_type,
            "transmission": transmission,
            "body_style": body_style,
            "door_count": observation.door_count,
        },
        "mileage": observation.mileage,
        "cap_clean_price": observation.cap_clean_price,
        "clean_condition": True,
        "write_off_reported": False,
        "accident_damage_reported": False,
    }
    if observation.trim:
        record["trim"] = observation.trim
    return BcaValidationResult(record=record, reasons=())


def _extract_bca_records_from_json_string(script_json: str) -> list[BcaRawRecord]:
    try:
        data = json.loads(script_json)
    except (json.JSONDecodeError, TypeError, ValueError):
        return []

    records: list[BcaRawRecord] = []
    queue = [data]
    visited = 0
    max_nodes = 5000

    while queue and visited < max_nodes:
        current = queue.pop(0)
        visited += 1

        with contextlib.suppress(KeyError, TypeError, ValueError):
            ident_raw = current["identity"]
            identity: BcaRawIdentity = {
                "make": str(ident_raw["make"]),
                "model_variant": str(ident_raw["model_variant"]),
                "registration_year": int(ident_raw["registration_year"]),
                "fuel_type": str(ident_raw["fuel_type"]),
                "transmission": str(ident_raw["transmission"]),
                "body_style": str(ident_raw["body_style"]),
                "door_count": int(ident_raw["door_count"]),
            }
            record: BcaRawRecord = {
                "id": str(current["id"]),
                "identity": identity,
                "mileage": int(current["mileage"]),
                "cap_clean_price": int(current["cap_clean_price"]),
                "clean_condition": bool(current["clean_condition"]),
                "write_off_reported": bool(current["write_off_reported"]),
                "accident_damage_reported": bool(current["accident_damage_reported"]),
            }
            trim_val = current.get("trim") if hasattr(current, "get") else None
            if trim_val is not None:
                record["trim"] = str(trim_val)
            records.append(record)
            continue

        if hasattr(current, "values"):
            with contextlib.suppress(AttributeError, TypeError):
                for val in current.values():
                    if hasattr(val, "values") or (
                        hasattr(val, "__iter__") and not hasattr(val, "lower")
                    ):
                        queue.append(val)
        elif hasattr(current, "__iter__") and not hasattr(current, "lower"):
            with contextlib.suppress(AttributeError, TypeError):
                for elem in current:
                    if hasattr(elem, "values") or (
                        hasattr(elem, "__iter__") and not hasattr(elem, "lower")
                    ):
                        queue.append(elem)

    return records


class _AutoTraderCardSpecs(TypedDict):
    mileage: int
    year: int
    fuel: str
    transmission: str
    doors: int
    cash_price: int
    seller_type: str
    body_style: str


class _AutoTraderHtmlTagParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.script_json_blocks: list[str] = []
        self._in_json_script = False
        self._current_script: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict: dict[str, str] = {}
        for key, val in attrs:
            if val is not None:
                attr_dict[key.lower()] = val

        if tag.lower() == "script":
            script_type = attr_dict.get("type", "").lower()
            if "json" in script_type:
                self._in_json_script = True
                self._current_script = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._in_json_script:
            self._in_json_script = False
            self.script_json_blocks.append("".join(self._current_script))
            self._current_script = []

    def handle_data(self, data: str) -> None:
        if self._in_json_script:
            self._current_script.append(data)


def _parse_autotrader_html(html_content: str) -> tuple[AutoTraderRawRecord, ...]:
    parser = _AutoTraderHtmlTagParser()
    with contextlib.suppress(TypeError, ValueError, AssertionError):
        parser.feed(html_content)

    all_records: list[AutoTraderRawRecord] = []
    for script_json in parser.script_json_blocks:
        extracted = _extract_autotrader_records_from_json_string(script_json)
        all_records.extend(extracted)

    dom_cards = _extract_autotrader_cards_from_html(html_content)
    all_records.extend(dom_cards)

    return tuple(all_records)


def _extract_autotrader_cards_from_html(
    html_content: str,
) -> list[AutoTraderRawRecord]:
    card_splits = re.split(r"<li [^>]*data-advertid=[\"\']\d+[\"\']", html_content)
    if len(card_splits) <= 1:
        card_splits = re.split(r'data-testid=["\']search-listing["\']', html_content)
    if len(card_splits) <= 1:
        card_splits = re.split(r'href=["\'][^"\']*/car-details/', html_content)
    if len(card_splits) <= 1:
        return []

    records: list[AutoTraderRawRecord] = []
    seen_ids: set[str] = set()
    for chunk in card_splits[1:]:
        card = _parse_single_autotrader_card(chunk)
        if card is not None and card["id"] not in seen_ids:
            seen_ids.add(card["id"])
            records.append(card)

    return records


def _parse_single_autotrader_card(chunk: str) -> AutoTraderRawRecord | None:
    try:
        id_match = re.search(
            r"(?:id=[\"\']|data-advertid=[\"\']|/car-details/)(\d{10,})", chunk
        )
        if not id_match:
            return None
        advert_id = id_match.group(1).strip()

        title_match = re.search(
            r"data-testid=[\"\']search-listing-title[\"\'][^>]*>([^<]+)", chunk
        ) or re.search(r"<h3[^>]*>([^<]+)", chunk)
        if not title_match:
            return None
        title = title_match.group(1).strip()

        sub_match = re.search(
            r"data-testid=[\"\']search-listing-subtitle[\"\'][^>]*>([^<]+)", chunk
        )
        subtitle = sub_match.group(1).strip() if sub_match else ""

        specs = _extract_autotrader_card_specs(chunk, title, subtitle)
        if specs is None:
            return None

        parts = title.split()
        make = parts[0]
        model_variant = parts[1] if len(parts) > 1 else ""

        identity: AutoTraderRawIdentity = {
            "make": make,
            "model_variant": model_variant,
            "registration_year": specs["year"],
            "fuel_type": specs["fuel"],
            "transmission": specs["transmission"],
            "body_style": specs["body_style"],
            "door_count": specs["doors"],
        }
        record: AutoTraderRawRecord = {
            "id": advert_id,
            "identity": identity,
            "mileage": specs["mileage"],
            "cash_price": specs["cash_price"],
            "seller_type": specs["seller_type"],
        }
        if subtitle:
            record["trim"] = subtitle
        return record
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def _extract_autotrader_card_specs(
    chunk: str, title: str, subtitle: str
) -> _AutoTraderCardSpecs | None:
    try:
        price_match = re.search(r"£([\d,]+)", chunk)
        if not price_match:
            return None
        cash_price = int(price_match.group(1).replace(",", ""))

        mileage_match = re.search(
            r"data-testid=[\"\']mileage[\"\'][^>]*>([\d,]+)\s*miles", chunk
        ) or re.search(r"([\d,]+)\s*miles", chunk)
        if not mileage_match:
            return None
        mileage = int(mileage_match.group(1).replace(",", ""))

        year_match = re.search(
            r"data-testid=[\"\']registered_year[\"\'][^>]*>.*?\b(19\d\d|20\d\d)\b",
            chunk,
        ) or re.search(r"\b(19\d\d|20\d\d)\b", chunk)
        if not year_match:
            return None
        year = int(year_match.group(1))

        full_text = f"{title} {subtitle} {chunk}"

        dr_match = re.search(r"(\d+)\s*(?:dr|doors)", full_text, re.IGNORECASE)
        doors = int(dr_match.group(1)) if dr_match else 5

        if re.search(r"\b(diesel|tdi)\b", full_text, re.IGNORECASE):
            fuel = "Diesel"
        elif re.search(
            r"\b(hybrid|etsi|mhev|phev|gte|plug-in)\b", full_text, re.IGNORECASE
        ):
            fuel = "Hybrid"
        elif re.search(r"\b(electric|ev)\b", full_text, re.IGNORECASE):
            fuel = "Electric"
        else:
            fuel = "Petrol"

        if re.search(r"\b(manual)\b", full_text, re.IGNORECASE):
            transmission = "Manual"
        else:
            transmission = "Automatic"

        if re.search(r"\b(estate|touring|avant|sw)\b", full_text, re.IGNORECASE):
            body_style = "Estate"
        elif re.search(r"\b(saloon|sedan)\b", full_text, re.IGNORECASE):
            body_style = "Saloon"
        elif re.search(r"\b(suv|crossover|4x4)\b", full_text, re.IGNORECASE):
            body_style = "SUV"
        elif re.search(r"\b(coupe)\b", full_text, re.IGNORECASE):
            body_style = "Coupe"
        elif re.search(r"\b(convertible|cabriolet)\b", full_text, re.IGNORECASE):
            body_style = "Convertible"
        else:
            body_style = "Hatchback"

        seller_type = "private" if "private seller" in chunk.lower() else "dealer"

        return _AutoTraderCardSpecs(
            mileage=mileage,
            year=year,
            fuel=fuel,
            transmission=transmission,
            doors=doors,
            cash_price=cash_price,
            seller_type=seller_type,
            body_style=body_style,
        )
    except (KeyError, TypeError, ValueError):
        return None


def _extract_autotrader_records_from_json_string(
    script_json: str,
) -> list[AutoTraderRawRecord]:
    try:
        data = json.loads(script_json)
    except (json.JSONDecodeError, TypeError, ValueError):
        return []

    records: list[AutoTraderRawRecord] = []
    queue = [data]
    visited = 0
    max_nodes = 5000

    while queue and visited < max_nodes:
        current = queue.pop(0)
        visited += 1

        with contextlib.suppress(KeyError, TypeError, ValueError):
            ident_raw = current["identity"]
            identity: AutoTraderRawIdentity = {
                "make": str(ident_raw["make"]),
                "model_variant": str(ident_raw["model_variant"]),
                "registration_year": int(ident_raw["registration_year"]),
                "fuel_type": str(ident_raw["fuel_type"]),
                "transmission": str(ident_raw["transmission"]),
                "body_style": str(ident_raw["body_style"]),
                "door_count": int(ident_raw["door_count"]),
            }
            raw_seller = str(current["seller_type"])
            if raw_seller in ("private", "dealer"):
                record: AutoTraderRawRecord = {
                    "id": str(current["id"]),
                    "identity": identity,
                    "mileage": int(current["mileage"]),
                    "cash_price": int(current["cash_price"]),
                    "seller_type": raw_seller,
                }
                trim_val = current.get("trim") if hasattr(current, "get") else None
                if trim_val is not None:
                    record["trim"] = str(trim_val)
                records.append(record)
                continue

        if hasattr(current, "values"):
            with contextlib.suppress(AttributeError, TypeError):
                for val in current.values():
                    if hasattr(val, "values") or (
                        hasattr(val, "__iter__") and not hasattr(val, "lower")
                    ):
                        queue.append(val)
        elif hasattr(current, "__iter__") and not hasattr(current, "lower"):
            with contextlib.suppress(AttributeError, TypeError):
                for elem in current:
                    if hasattr(elem, "values") or (
                        hasattr(elem, "__iter__") and not hasattr(elem, "lower")
                    ):
                        queue.append(elem)

    return records
