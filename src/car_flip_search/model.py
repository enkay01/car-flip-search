"""Immutable domain types for auction and retail-market comparison."""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import TypeGuard


@dataclass(frozen=True)
class AuctionLotId:
    value: str

    def __post_init__(self) -> None:
        if not _is_exact_type(self.value, str) or not self.value.strip():
            raise ValueError("Auction Lot ID must be a non-blank string")


@dataclass(frozen=True)
class AutoTraderListingId:
    value: str

    def __post_init__(self) -> None:
        if not _is_exact_type(self.value, str) or not self.value.strip():
            raise ValueError("Auto Trader Listing ID must be a non-blank string")


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if not _is_exact_type(self.amount, Decimal):
            raise TypeError("Money amount must be a Decimal")
        if not self.amount.is_finite():
            raise ValueError("Money amount must be finite")
        if (
            not _is_exact_type(self.currency, str)
            or len(self.currency) != 3
            or not self.currency.isupper()
            or not self.currency.isalpha()
        ):
            raise ValueError("Money currency must be an ISO 4217 currency code")
        exponent = self.amount.normalize().as_tuple().exponent
        if -exponent > 2:
            raise ValueError("Money amount can have at most two fractional digits")


@dataclass(frozen=True)
class CashPrice:
    money: Money

    def __post_init__(self) -> None:
        if not _is_exact_type(self.money, Money):
            raise TypeError("Cash Price must contain Money")
        if self.money.amount < 0:
            raise ValueError("Cash Price cannot be negative")


@dataclass(frozen=True)
class CapCleanPrice:
    money: Money

    def __post_init__(self) -> None:
        if not _is_exact_type(self.money, Money):
            raise TypeError("CAP Clean Price must contain Money")
        if self.money.currency != "GBP":
            raise ValueError("CAP Clean Price must be GBP")
        if self.money.amount < 0:
            raise ValueError("CAP Clean Price cannot be negative")


@dataclass(frozen=True)
class AdvertisedPrice:
    cash_price: CashPrice

    def __post_init__(self) -> None:
        if not _is_exact_type(self.cash_price, CashPrice):
            raise TypeError("Advertised Price must be derived from a Cash Price")
        if self.cash_price.money.currency != "GBP":
            raise ValueError("Advertised Price must be derived from a GBP Cash Price")


@dataclass(frozen=True)
class PriceSpread:
    money: Money

    def __post_init__(self) -> None:
        if not _is_exact_type(self.money, Money):
            raise TypeError("Price Spread must contain Money")
        if self.money.currency != "GBP":
            raise ValueError("Price Spread must be GBP")

    @classmethod
    def between(
        cls,
        advertised_price: AdvertisedPrice,
        cap_clean_price: CapCleanPrice,
    ) -> "PriceSpread":
        return cls(
            Money(
                advertised_price.cash_price.money.amount - cap_clean_price.money.amount,
                "GBP",
            )
        )


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
        if any(
            not _is_exact_type(value, str) or not value.strip() for value in text_fields
        ):
            raise ValueError(
                "Core Vehicle Identity text fields must be non-blank strings"
            )
        if (
            not _is_exact_type(self.registration_year, int)
            or not 1886 <= self.registration_year <= 9999
        ):
            raise ValueError("Core Vehicle Identity registration year must be valid")
        if not _is_exact_type(self.door_count, int) or self.door_count < 1:
            raise ValueError("Core Vehicle Identity door count must be positive")


@dataclass(frozen=True)
class AuctionLot:
    id: AuctionLotId
    identity: CoreVehicleIdentity
    mileage: int
    cap_clean_price: CapCleanPrice
    trim: str | None = None

    def __post_init__(self) -> None:
        if not _is_exact_type(self.id, AuctionLotId):
            raise TypeError("Auction Lot must use an AuctionLotId")
        if not _is_exact_type(self.identity, CoreVehicleIdentity):
            raise TypeError("Auction Lot must have a Core Vehicle Identity")
        if not _is_exact_type(self.mileage, int) or self.mileage < 0:
            raise ValueError("Auction Lot mileage must be a non-negative integer")
        if not _is_exact_type(self.cap_clean_price, CapCleanPrice):
            raise TypeError("Auction Lot must have a CAP Clean Price")
        if self.trim is not None and (
            not _is_exact_type(self.trim, str) or not self.trim.strip()
        ):
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
        if not _is_exact_type(self.id, AutoTraderListingId):
            raise TypeError("Auto Trader Listing must use an AutoTraderListingId")
        if not _is_exact_type(self.identity, CoreVehicleIdentity):
            raise TypeError("Auto Trader Listing must have a Core Vehicle Identity")
        if not _is_exact_type(self.mileage, int) or self.mileage < 0:
            raise ValueError(
                "Auto Trader Listing mileage must be a non-negative integer"
            )
        if not _is_exact_type(self.cash_price, CashPrice):
            raise TypeError("Auto Trader Listing must have a Cash Price")
        if not _is_exact_type(self.seller_type, SellerType):
            raise TypeError("Auto Trader Listing must have a Seller Type")
        if self.trim is not None and (
            not _is_exact_type(self.trim, str) or not self.trim.strip()
        ):
            raise ValueError(
                "Auto Trader Listing trim must be a non-blank string or None"
            )


@dataclass(frozen=True)
class MarketSnapshot:
    listings: tuple[AutoTraderListing, ...]

    def __init__(self, listings: Sequence[AutoTraderListing]) -> None:
        immutable_listings = tuple(listings)
        if any(
            not _is_exact_type(listing, AutoTraderListing)
            for listing in immutable_listings
        ):
            raise TypeError("Market Snapshot contains Auto Trader Listings")
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
        if not _is_exact_type(self.listing_id, AutoTraderListingId):
            raise TypeError("Market Comparable must have an Auto Trader Listing ID")
        if not _is_exact_type(self.identity, CoreVehicleIdentity):
            raise TypeError("Market Comparable must have a Core Vehicle Identity")
        if not _is_exact_type(self.mileage, int) or self.mileage < 0:
            raise ValueError("Market Comparable mileage must be a non-negative integer")
        if not _is_exact_type(self.advertised_price, AdvertisedPrice):
            raise TypeError("Market Comparable must have an Advertised Price")
        if not _is_exact_type(self.seller_type, SellerType):
            raise TypeError("Market Comparable must have a Seller Type")
        if self.trim is not None and (
            not _is_exact_type(self.trim, str) or not self.trim.strip()
        ):
            raise ValueError(
                "Market Comparable trim must be a non-blank string or None"
            )


@dataclass(frozen=True)
class ComparableEvidence:
    market_comparables: tuple[MarketComparable, ...]

    def __post_init__(self) -> None:
        if not self.market_comparables:
            raise ValueError("Comparable Evidence requires a Market Comparable")
        if any(
            not _is_exact_type(item, MarketComparable)
            for item in self.market_comparables
        ):
            raise TypeError("Comparable Evidence contains Market Comparables")
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
            key=lambda item: item.advertised_price.cash_price.money.amount,
        ).advertised_price


@dataclass(frozen=True)
class NoComparableEvidence:
    pass


@dataclass(frozen=True)
class Candidate:
    auction_lot: AuctionLot
    comparable_evidence: ComparableEvidence | NoComparableEvidence

    def __post_init__(self) -> None:
        if not _is_exact_type(self.auction_lot, AuctionLot):
            raise TypeError("Candidate must contain an Auction Lot")
        if not (
            _is_exact_type(self.comparable_evidence, ComparableEvidence)
            or _is_exact_type(self.comparable_evidence, NoComparableEvidence)
        ):
            raise TypeError("Candidate must contain explicit comparable evidence")

    @property
    def comparable_supply(self) -> int:
        if _is_exact_type(self.comparable_evidence, NoComparableEvidence):
            return 0
        return self.comparable_evidence.comparable_supply

    @property
    def price_spread(self) -> PriceSpread | NoComparableEvidence:
        if _is_exact_type(self.comparable_evidence, NoComparableEvidence):
            return self.comparable_evidence
        return PriceSpread.between(
            self.comparable_evidence.advertised_price,
            self.auction_lot.cap_clean_price,
        )


@dataclass(frozen=True)
class OpportunityList:
    candidates: tuple[Candidate, ...]

    def __init__(self, candidates: Sequence[Candidate]) -> None:
        immutable_candidates = tuple(candidates)
        if any(
            not _is_exact_type(candidate, Candidate)
            for candidate in immutable_candidates
        ):
            raise TypeError("Opportunity List contains Candidates")
        if len({candidate.auction_lot.id for candidate in immutable_candidates}) != len(
            immutable_candidates
        ):
            raise ValueError(
                "Opportunity List cannot contain duplicate Auction Lot IDs"
            )
        object.__setattr__(self, "candidates", immutable_candidates)


def _is_exact_type[Value, ExpectedType](
    value: Value,
    expected: type[ExpectedType],
) -> TypeGuard[ExpectedType]:
    return type(value) is expected
