"""Immutable domain types for auction and retail-market comparison."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum


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

    def __post_init__(self) -> None:
        if self.mileage < 0:
            raise ValueError("Market Comparable mileage must be non-negative")
        if self.trim is not None and not self.trim.strip():
            raise ValueError(
                "Market Comparable trim must be a non-blank string or None"
            )


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


@dataclass(frozen=True)
class NoComparableEvidence:
    @property
    def comparable_supply(self) -> int:
        return 0

    def price_spread(self, cap_clean_price: CapCleanPrice) -> "NoComparableEvidence":
        return self


@dataclass(frozen=True)
class CandidateVehicle:
    auction_lot: AuctionLot
    comparable_evidence: ComparableEvidence | NoComparableEvidence

    @property
    def comparable_supply(self) -> int:
        return self.comparable_evidence.comparable_supply

    @property
    def price_spread(self) -> PriceSpread | NoComparableEvidence:
        return self.comparable_evidence.price_spread(self.auction_lot.cap_clean_price)


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
