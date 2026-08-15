"""Parse BCA and Auto Trader payloads into complete domain records at the acquisition seam."""

import contextlib
import json
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

    return tuple(all_records)


def _extract_bca_records_from_json_string(script_json: str) -> list[BcaRawRecord]:
    try:
        data = json.loads(script_json)
    except (json.JSONDecodeError, TypeError, ValueError):
        return []

    records: list[BcaRawRecord] = []
    queue = [data]
    while queue:
        current = queue.pop(0)
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

        with contextlib.suppress(AttributeError, TypeError):
            queue.extend(current)
        with contextlib.suppress(AttributeError, TypeError):
            for key in current:
                with contextlib.suppress(TypeError, KeyError, IndexError):
                    queue.append(current[key])

    return records
