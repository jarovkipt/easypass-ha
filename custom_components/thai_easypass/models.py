"""Typed data models for Thai Easy Pass."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class CardInfo:
    """Safe card information returned by the portal."""

    card_id: str
    account_number: str | None
    balance: Decimal
    card_name: str | None = None
    tag_status: str | None = None
    tag_action: str | None = None
    plate_no: str | None = None
    car_model: str | None = None
    car_color: str | None = None
    account_status: str | None = None


@dataclass(frozen=True, slots=True)
class LastTrip:
    """The most recent toll transaction."""

    location: str
    position: str | None
    occurred_at: datetime | None
    amount: Decimal
    balance_after: Decimal


@dataclass(frozen=True, slots=True)
class UsageSummary:
    """Current-month aggregate for one card."""

    toll_total: Decimal
    topup_total: Decimal
    other_total: Decimal
    trip_count: int
    last_trip: LastTrip | None
    period_start: datetime


@dataclass(frozen=True, slots=True)
class CardSnapshot:
    """Coordinator data for one card."""

    card: CardInfo
    usage: UsageSummary | None
    usage_available: bool


type AccountSnapshot = dict[str, CardSnapshot]

