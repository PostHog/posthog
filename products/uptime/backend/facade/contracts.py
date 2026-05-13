from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from .enums import PingOutcome


@dataclass(frozen=True)
class MonitorDTO:
    id: UUID
    name: str
    url: str
    created_at: datetime


@dataclass(frozen=True)
class CreateMonitorInput:
    team_id: int
    name: str
    url: str


@dataclass(frozen=True)
class BulkCreateMonitorItem:
    name: str
    url: str


@dataclass(frozen=True)
class BulkCreateMonitorInput:
    team_id: int
    items: list[BulkCreateMonitorItem]


@dataclass(frozen=True)
class SuggestedUrlDTO:
    url: str
    host: str
    event_count: int
    unique_paths: int
    last_seen: datetime


@dataclass(frozen=True)
class PingDTO:
    monitor_id: UUID
    timestamp: datetime
    latency_ms: int
    status_code: int | None
    outcome: PingOutcome
