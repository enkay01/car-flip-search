"""Parse BCA and Auto Trader payloads into complete domain records at the acquisition seam."""

import json
from collections.abc import Iterable
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
    """Import BCA records from supported manual exports or JSON feeds."""

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
