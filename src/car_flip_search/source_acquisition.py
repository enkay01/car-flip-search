"""Parse BCA and Auto Trader payloads into complete domain records at the acquisition seam."""

import contextlib
import json
import re
from collections.abc import Iterable
from html.parser import HTMLParser
from typing import TypedDict

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

    # Also extract cards from rendered BCA HTML search result pages
    dom_cards = _extract_bca_cards_from_html(html_content)
    all_records.extend(dom_cards)

    return tuple(all_records)


class _CardSpecs(TypedDict):
    mileage: int
    year: int
    fuel: str
    transmission: str
    doors: int


def _extract_bca_cards_from_html(html_content: str) -> list[BcaRawRecord]:
    card_splits = re.split(r'data-testid=["\']card-link-desktop["\']', html_content)
    if len(card_splits) <= 1:
        return []

    records: list[BcaRawRecord] = []
    for chunk in card_splits[1:]:
        card = _parse_single_bca_card(chunk)
        if card is not None:
            records.append(card)

    return records


def _parse_single_bca_card(chunk: str) -> BcaRawRecord | None:
    try:
        vrm_match = re.search(r'/lot/([^?\"\'/\s]+)', chunk)
        if not vrm_match:
            return None
        vrm = vrm_match.group(1).replace("%20", " ").strip()

        title_match = re.search(
            r'VehicleResultCardDesktop__StyledLink[^\"]*\"[^>]*>([^<]+)</a>', chunk
        )
        if not title_match:
            return None
        title = title_match.group(1).strip()

        cap_match = re.search(r"CAP Clean</p>\s*<p[^>]*>£([\d,]+)</p>", chunk)
        if not cap_match:
            return None
        cap_clean = int(cap_match.group(1).replace(",", ""))

        items = re.findall(r'<p [^>]*>([^<]+)</p>', chunk)
        specs = _extract_card_specs(items)
        if specs is None:
            return None

        parts = title.split()
        make = parts[0]
        model_variant = parts[1] if len(parts) > 1 else ""
        body_style = parts[-1] if len(parts) > 2 else "Hatchback"
        trim = " ".join(parts[2:-1]) if len(parts) > 3 else None

        identity: BcaRawIdentity = {
            "make": make,
            "model_variant": model_variant,
            "registration_year": specs["year"],
            "fuel_type": specs["fuel"],
            "transmission": specs["transmission"],
            "body_style": body_style,
            "door_count": specs["doors"],
        }
        record: BcaRawRecord = {
            "id": vrm,
            "identity": identity,
            "mileage": specs["mileage"],
            "cap_clean_price": cap_clean,
            "clean_condition": True,
            "write_off_reported": False,
            "accident_damage_reported": False,
        }
        if trim:
            record["trim"] = trim
        return record
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def _extract_card_specs(items: list[str]) -> _CardSpecs | None:
    extracted: dict[str, str | int] = {}
    for item in items:
        m_match = re.search(r"([\d,]+)\s*miles", item, re.IGNORECASE)
        if m_match and "mileage" not in extracted:
            extracted["mileage"] = int(m_match.group(1).replace(",", ""))
        y_match = re.search(r"\b(19\d\d|20\d\d)\b", item)
        if y_match and "year" not in extracted and "reg" in item.lower():
            extracted["year"] = int(y_match.group(1))
        item_lower = item.lower()
        if item_lower in (
            "petrol",
            "diesel",
            "electric",
            "hybrid",
            "petrol plug-in hybrid",
            "diesel plug-in hybrid",
        ):
            extracted["fuel"] = item
        if item_lower in (
            "manual",
            "automatic",
            "auto clutch",
            "auto/manual mode",
            "cvt",
            "cvt/manual mode",
        ):
            extracted["transmission"] = item
        d_match = re.search(r"(\d+)\s*doors", item, re.IGNORECASE)
        if d_match and "doors" not in extracted:
            extracted["doors"] = int(d_match.group(1))

    try:
        return _CardSpecs(
            mileage=int(extracted["mileage"]),
            year=int(extracted["year"]),
            fuel=str(extracted["fuel"]),
            transmission=str(extracted["transmission"]),
            doors=int(extracted["doors"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


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
                    if hasattr(val, "values") or (hasattr(val, "__iter__") and not hasattr(val, "lower")):
                        queue.append(val)
        elif hasattr(current, "__iter__") and not hasattr(current, "lower"):
            with contextlib.suppress(AttributeError, TypeError):
                for elem in current:
                    if hasattr(elem, "values") or (hasattr(elem, "__iter__") and not hasattr(elem, "lower")):
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
    card_splits = re.split(
        r'<li [^>]*data-advertid=[\"\']\d+[\"\']', html_content
    )
    if len(card_splits) <= 1:
        card_splits = re.split(
            r'data-testid=["\']search-listing["\']', html_content
        )
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
            r'(?:id=[\"\']|data-advertid=[\"\']|/car-details/)(\d{10,})', chunk
        )
        if not id_match:
            return None
        advert_id = id_match.group(1).strip()

        title_match = re.search(
            r'data-testid=[\"\']search-listing-title[\"\'][^>]*>([^<]+)', chunk
        ) or re.search(
            r'<h3[^>]*>([^<]+)', chunk
        )
        if not title_match:
            return None
        title = title_match.group(1).strip()

        sub_match = re.search(
            r'data-testid=[\"\']search-listing-subtitle[\"\'][^>]*>([^<]+)', chunk
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
            r'data-testid=[\"\']mileage[\"\'][^>]*>([\d,]+)\s*miles', chunk
        ) or re.search(r"([\d,]+)\s*miles", chunk)
        if not mileage_match:
            return None
        mileage = int(mileage_match.group(1).replace(",", ""))

        year_match = re.search(
            r'data-testid=[\"\']registered_year[\"\'][^>]*>.*?\b(19\d\d|20\d\d)\b',
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
        elif re.search(
            r"\b(convertible|cabriolet)\b", full_text, re.IGNORECASE
        ):
            body_style = "Convertible"
        else:
            body_style = "Hatchback"

        seller_type = (
            "private" if "private seller" in chunk.lower() else "dealer"
        )

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
                trim_val = (
                    current.get("trim") if hasattr(current, "get") else None
                )
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
