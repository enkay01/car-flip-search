"""Immutable domain types for auction and retail-market comparison."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import cmp_to_key
from typing import NamedTuple


@dataclass(frozen=True)
class AuctionLotId:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("Auction Lot ID must be a non-blank string")


@dataclass(frozen=True)
class AutoTraderListingId:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("Auto Trader Listing ID must be a non-blank string")


@dataclass(frozen=True)
class CashPrice:
    pounds: int

    def __post_init__(self) -> None:
        if self.pounds < 0:
            raise ValueError("Cash Price cannot be negative")


@dataclass(frozen=True)
class CapCleanPrice:
    pounds: int

    def __post_init__(self) -> None:
        if self.pounds < 0:
            raise ValueError("CAP Clean Price cannot be negative")


@dataclass(frozen=True)
class AdvertisedPrice:
    cash_price: CashPrice

    @property
    def pounds(self) -> int:
        return self.cash_price.pounds


@dataclass(frozen=True)
class PriceSpread:
    pounds: int

    @classmethod
    def between(
        cls,
        advertised_price: AdvertisedPrice,
        cap_clean_price: CapCleanPrice,
    ) -> "PriceSpread":
        return cls(advertised_price.pounds - cap_clean_price.pounds)


@dataclass(frozen=True)
class CoreVehicleIdentity:
    make: str
    model_variant: str
    registration_year: int
    fuel_type: str
    transmission: str
    body_style: str
    door_count: int

    def __post_init__(self) -> None:
        text_fields = (
            self.make,
            self.model_variant,
            self.fuel_type,
            self.transmission,
            self.body_style,
        )
        if any(not value.strip() for value in text_fields):
            raise ValueError(
                "Core Vehicle Identity text fields must be non-blank strings"
            )
        if not 1886 <= self.registration_year <= 9999:
            raise ValueError("Core Vehicle Identity registration year must be valid")
        if self.door_count < 1:
            raise ValueError("Core Vehicle Identity door count must be positive")


@dataclass(frozen=True)
class AuctionLot:
    id: AuctionLotId
    identity: CoreVehicleIdentity
    mileage: int
    cap_clean_price: CapCleanPrice
    trim: str | None = None

    def __post_init__(self) -> None:
        if self.mileage < 0:
            raise ValueError("Auction Lot mileage must be non-negative")
        if self.trim is not None and not self.trim.strip():
            raise ValueError("Auction Lot trim must be a non-blank string or None")


class SellerType(StrEnum):
    PRIVATE = "private"
    DEALER = "dealer"


@dataclass(frozen=True)
class AutoTraderListing:
    id: AutoTraderListingId
    identity: CoreVehicleIdentity
    mileage: int
    cash_price: CashPrice
    seller_type: SellerType
    trim: str | None = None

    def __post_init__(self) -> None:
        if self.mileage < 0:
            raise ValueError("Auto Trader Listing mileage must be non-negative")
        if self.trim is not None and not self.trim.strip():
            raise ValueError(
                "Auto Trader Listing trim must be a non-blank string or None"
            )


@dataclass(frozen=True)
class MarketSnapshot:
    listings: tuple[AutoTraderListing, ...]

    def __init__(self, listings: Sequence[AutoTraderListing]) -> None:
        immutable_listings = tuple(listings)
        if len({listing.id for listing in immutable_listings}) != len(
            immutable_listings
        ):
            raise ValueError(
                "Market Snapshot cannot contain duplicate Auto Trader Listing IDs"
            )
        object.__setattr__(self, "listings", immutable_listings)


@dataclass(frozen=True)
class MarketComparable:
    listing_id: AutoTraderListingId
    identity: CoreVehicleIdentity
    mileage: int
    advertised_price: AdvertisedPrice
    seller_type: SellerType
    trim: str | None
    trim_match: bool

    def __post_init__(self) -> None:
        if self.mileage < 0:
            raise ValueError("Market Comparable mileage must be non-negative")
        if self.trim is not None and not self.trim.strip():
            raise ValueError(
                "Market Comparable trim must be a non-blank string or None"
            )
        if self.trim_match and self.trim is None:
            raise ValueError("A Trim Match requires a known trim on the listing")


@dataclass(frozen=True)
class ComparableEvidence:
    market_comparables: tuple[MarketComparable, ...]

    def __post_init__(self) -> None:
        if not self.market_comparables:
            raise ValueError("Comparable Evidence requires a Market Comparable")
        if len({item.listing_id for item in self.market_comparables}) != len(
            self.market_comparables
        ):
            raise ValueError(
                "Comparable Evidence cannot contain duplicate Auto Trader Listing IDs"
            )
        ordered = tuple(
            sorted(self.market_comparables, key=lambda item: not item.trim_match)
        )
        object.__setattr__(self, "market_comparables", ordered)

    @property
    def comparable_supply(self) -> int:
        return len(self.market_comparables)

    @property
    def advertised_price(self) -> AdvertisedPrice:
        return min(
            self.market_comparables,
            key=lambda item: item.advertised_price.pounds,
        ).advertised_price

    def price_spread(self, cap_clean_price: CapCleanPrice) -> PriceSpread:
        return PriceSpread.between(self.advertised_price, cap_clean_price)

    def price_spread_pounds(self, cap_clean_price: CapCleanPrice) -> int | None:
        return self.price_spread(cap_clean_price).pounds


@dataclass(frozen=True)
class NoComparableEvidence:
    @property
    def comparable_supply(self) -> int:
        return 0

    def price_spread(self, cap_clean_price: CapCleanPrice) -> "NoComparableEvidence":
        return self

    def price_spread_pounds(self, cap_clean_price: CapCleanPrice) -> int | None:
        return None


@dataclass(frozen=True)
class HighMileageReference:
    listing_id: AutoTraderListingId
    identity: CoreVehicleIdentity
    mileage: int
    advertised_price: AdvertisedPrice
    seller_type: SellerType
    trim: str | None

    def __post_init__(self) -> None:
        if self.mileage < 0:
            raise ValueError("High-Mileage Reference mileage must be non-negative")
        if self.trim is not None and not self.trim.strip():
            raise ValueError(
                "High-Mileage Reference trim must be a non-blank string or None"
            )


@dataclass(frozen=True)
class RetailFloor:
    pounds: int

    def __post_init__(self) -> None:
        if self.pounds < 0:
            raise ValueError("Retail Floor cannot be negative")


@dataclass(frozen=True)
class RetailFloorSpread:
    pounds: int

    @classmethod
    def between(
        cls,
        retail_floor: RetailFloor,
        cap_clean_price: CapCleanPrice,
    ) -> "RetailFloorSpread":
        return cls(retail_floor.pounds - cap_clean_price.pounds)


@dataclass(frozen=True)
class RetailFloorEvidence:
    high_mileage_references: tuple[HighMileageReference, ...]

    def __post_init__(self) -> None:
        if not self.high_mileage_references:
            raise ValueError("Retail Floor Evidence requires a High-Mileage Reference")
        if len({item.listing_id for item in self.high_mileage_references}) != len(
            self.high_mileage_references
        ):
            raise ValueError(
                "Retail Floor Evidence cannot contain duplicate Auto Trader Listing IDs"
            )

    @property
    def retail_floor(self) -> RetailFloor:
        return RetailFloor(
            min(item.advertised_price.pounds for item in self.high_mileage_references)
        )

    def retail_floor_spread(self, cap_clean_price: CapCleanPrice) -> RetailFloorSpread:
        return RetailFloorSpread.between(self.retail_floor, cap_clean_price)

    def retail_floor_spread_pounds(self, cap_clean_price: CapCleanPrice) -> int | None:
        return self.retail_floor_spread(cap_clean_price).pounds


@dataclass(frozen=True)
class NoRetailFloorEvidence:
    @property
    def retail_floor(self) -> "NoRetailFloorEvidence":
        return self

    def retail_floor_spread(
        self, cap_clean_price: CapCleanPrice
    ) -> "NoRetailFloorEvidence":
        return self

    def retail_floor_spread_pounds(self, cap_clean_price: CapCleanPrice) -> int | None:
        return None


@dataclass(frozen=True)
class CandidateVehicle:
    auction_lot: AuctionLot
    comparable_evidence: ComparableEvidence | NoComparableEvidence
    retail_floor_evidence: RetailFloorEvidence | NoRetailFloorEvidence

    @property
    def comparable_supply(self) -> int:
        return self.comparable_evidence.comparable_supply

    @property
    def price_spread(self) -> PriceSpread | NoComparableEvidence:
        return self.comparable_evidence.price_spread(self.auction_lot.cap_clean_price)

    @property
    def retail_floor(self) -> RetailFloor | NoRetailFloorEvidence:
        return self.retail_floor_evidence.retail_floor

    @property
    def retail_floor_spread(self) -> RetailFloorSpread | NoRetailFloorEvidence:
        return self.retail_floor_evidence.retail_floor_spread(
            self.auction_lot.cap_clean_price
        )

    @property
    def price_spread_pounds(self) -> int | None:
        return self.comparable_evidence.price_spread_pounds(
            self.auction_lot.cap_clean_price
        )

    @property
    def retail_floor_spread_pounds(self) -> int | None:
        return self.retail_floor_evidence.retail_floor_spread_pounds(
            self.auction_lot.cap_clean_price
        )


class SortField(StrEnum):
    MAKE = "make"
    MODEL_VARIANT = "model_variant"
    REGISTRATION_YEAR = "registration_year"
    FUEL_TYPE = "fuel_type"
    TRANSMISSION = "transmission"
    BODY_STYLE = "body_style"
    DOOR_COUNT = "door_count"
    MILEAGE = "mileage"
    CAP_CLEAN_PRICE = "cap_clean_price"
    TRIM = "trim"
    COMPARABLE_SUPPLY = "comparable_supply"
    PRICE_SPREAD = "price_spread"
    RETAIL_FLOOR_SPREAD = "retail_floor_spread"


@dataclass(frozen=True, kw_only=True)
class SortCriterion:
    field: SortField
    descending: bool = False


@dataclass(frozen=True, kw_only=True)
class CandidateFilter:
    make: str | None = None
    model_variant: str | None = None
    registration_year: int | None = None
    fuel_type: str | None = None
    transmission: str | None = None
    body_style: str | None = None
    door_count: int | None = None
    mileage: int | None = None
    cap_clean_price: int | None = None
    trim: str | None = None
    has_trim: bool | None = None
    comparable_supply: int | None = None
    price_spread: int | None = None
    has_price_spread: bool | None = None
    retail_floor_spread: int | None = None
    has_retail_floor_spread: bool | None = None


@dataclass(frozen=True)
class OpportunityList:
    candidates: tuple[CandidateVehicle, ...]

    def __init__(self, candidates: Sequence[CandidateVehicle]) -> None:
        immutable_candidates = tuple(candidates)
        if len({candidate.auction_lot.id for candidate in immutable_candidates}) != len(
            immutable_candidates
        ):
            raise ValueError(
                "Opportunity List cannot contain duplicate Auction Lot IDs"
            )
        object.__setattr__(self, "candidates", immutable_candidates)

    def filter(self, criteria: CandidateFilter) -> "OpportunityList":
        return OpportunityList(
            tuple(
                candidate
                for candidate in self.candidates
                if _matches(candidate, criteria)
            )
        )

    def sort(self, *criteria: SortCriterion) -> "OpportunityList":
        ordered = list(self.candidates)
        for criterion in reversed(criteria):
            ordered = _sort_stably(ordered, criterion)
        return OpportunityList(tuple(ordered))


def _matches(candidate: CandidateVehicle, criteria: CandidateFilter) -> bool:
    lot = candidate.auction_lot
    identity = lot.identity
    if criteria.make is not None and identity.make != criteria.make:
        return False
    if (
        criteria.model_variant is not None
        and identity.model_variant != criteria.model_variant
    ):
        return False
    if (
        criteria.registration_year is not None
        and identity.registration_year != criteria.registration_year
    ):
        return False
    if criteria.fuel_type is not None and identity.fuel_type != criteria.fuel_type:
        return False
    if (
        criteria.transmission is not None
        and identity.transmission != criteria.transmission
    ):
        return False
    if criteria.body_style is not None and identity.body_style != criteria.body_style:
        return False
    if criteria.door_count is not None and identity.door_count != criteria.door_count:
        return False
    if criteria.mileage is not None and lot.mileage != criteria.mileage:
        return False
    if (
        criteria.cap_clean_price is not None
        and lot.cap_clean_price.pounds != criteria.cap_clean_price
    ):
        return False
    if criteria.trim is not None and lot.trim != criteria.trim:
        return False
    if criteria.has_trim is not None:
        has_trim = lot.trim is not None
        if has_trim != criteria.has_trim:
            return False
    if (
        criteria.comparable_supply is not None
        and candidate.comparable_supply != criteria.comparable_supply
    ):
        return False
    if criteria.has_price_spread is not None:
        has_price_spread = candidate.price_spread_pounds is not None
        if has_price_spread != criteria.has_price_spread:
            return False
    if (
        criteria.price_spread is not None
        and candidate.price_spread_pounds != criteria.price_spread
    ):
        return False
    if criteria.has_retail_floor_spread is not None:
        has_retail_floor_spread = candidate.retail_floor_spread_pounds is not None
        if has_retail_floor_spread != criteria.has_retail_floor_spread:
            return False
    if criteria.retail_floor_spread is not None:
        return candidate.retail_floor_spread_pounds == criteria.retail_floor_spread
    return True


def _sort_stably(
    candidates: list[CandidateVehicle], criterion: SortCriterion
) -> list[CandidateVehicle]:
    def compare(left: CandidateVehicle, right: CandidateVehicle) -> int:
        left_value = _sort_value(left, criterion.field)
        right_value = _sort_value(right, criterion.field)
        if left_value is None and right_value is None:
            return 0
        if left_value is None:
            return 1
        if right_value is None:
            return -1
        if left_value < right_value:
            return 1 if criterion.descending else -1
        if left_value > right_value:
            return -1 if criterion.descending else 1
        return 0

    return sorted(candidates, key=cmp_to_key(compare))


class _SortKey(NamedTuple):
    number: int
    text: str


def _sort_value(candidate: CandidateVehicle, field: SortField) -> _SortKey | None:
    match field:
        case SortField.MAKE:
            return _text_sort_key(candidate.auction_lot.identity.make)
        case SortField.MODEL_VARIANT:
            return _text_sort_key(candidate.auction_lot.identity.model_variant)
        case SortField.REGISTRATION_YEAR:
            return _number_sort_key(candidate.auction_lot.identity.registration_year)
        case SortField.FUEL_TYPE:
            return _text_sort_key(candidate.auction_lot.identity.fuel_type)
        case SortField.TRANSMISSION:
            return _text_sort_key(candidate.auction_lot.identity.transmission)
        case SortField.BODY_STYLE:
            return _text_sort_key(candidate.auction_lot.identity.body_style)
        case SortField.DOOR_COUNT:
            return _number_sort_key(candidate.auction_lot.identity.door_count)
        case SortField.MILEAGE:
            return _number_sort_key(candidate.auction_lot.mileage)
        case SortField.CAP_CLEAN_PRICE:
            return _number_sort_key(candidate.auction_lot.cap_clean_price.pounds)
        case SortField.TRIM:
            trim = candidate.auction_lot.trim
            return None if trim is None else _text_sort_key(trim)
        case SortField.COMPARABLE_SUPPLY:
            return _number_sort_key(candidate.comparable_supply)
        case SortField.PRICE_SPREAD:
            price_spread_value = candidate.price_spread_pounds
            return (
                None
                if price_spread_value is None
                else _number_sort_key(price_spread_value)
            )
        case SortField.RETAIL_FLOOR_SPREAD:
            retail_floor_spread_value = candidate.retail_floor_spread_pounds
            return (
                None
                if retail_floor_spread_value is None
                else _number_sort_key(retail_floor_spread_value)
            )
        case _:
            raise ValueError(f"Unknown sort field: {field}")


def _text_sort_key(value: str) -> _SortKey:
    return _SortKey(0, value)


def _number_sort_key(value: int) -> _SortKey:
    return _SortKey(value, "")
