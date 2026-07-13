from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Account:
    id: str
    name: str
    email: str
    timezone: str  # IANA name, e.g. "America/Los_Angeles", chosen at signup


@dataclass(frozen=True)
class Order:
    id: str
    account_id: str
    total_cents: int
    placed_at: datetime  # timezone-aware, stored in UTC


@dataclass(frozen=True)
class DailyReport:
    account_id: str
    date: str  # ISO date the report covers
    order_ids: tuple[str, ...]
    order_count: int
    total_cents: int
