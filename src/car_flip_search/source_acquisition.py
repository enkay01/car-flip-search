"""Parse BCA payloads into complete domain lots at the acquisition seam."""

from collections.abc import Iterable
from typing import TypedDict

from .model import AuctionLot, AuctionLotId, CapCleanPrice, CoreVehicleIdentity


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
        for record in records:
            auction_lot = _parse_record(record)
            if auction_lot is not None:
                acquired_lots.append(auction_lot)
        return tuple(acquired_lots)


def _parse_record(record: BcaRawRecord) -> AuctionLot | None:
    try:
        if not _is_condition_eligible(record):
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


def _is_condition_eligible(record: BcaRawRecord) -> bool:
    """Accept only known-clean lots with no reported write-off or accident damage."""

    return (
        record["clean_condition"] is True
        and record["write_off_reported"] is False
        and record["accident_damage_reported"] is False
    )
