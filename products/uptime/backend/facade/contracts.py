from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from .enums import PingOutcome

MonitorOverallStatus = Literal["up", "down", "no_data"]
MonitorDailyStatus = Literal["up", "degraded", "down", "no_data"]


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
class UpdateMonitorInput:
    team_id: int
    monitor_id: UUID
    name: str | None = None
    url: str | None = None


@dataclass(frozen=True)
class DailyBucketDTO:
    date: date
    total: int
    failed: int
    status: MonitorDailyStatus


@dataclass(frozen=True)
class MonitorSummaryDTO:
    id: UUID
    name: str
    url: str
    created_at: datetime
    status: MonitorOverallStatus
    uptime_90d: float | None
    avg_latency_24h_ms: int | None
    last_ping_at: datetime | None
    last_ping_outcome: PingOutcome | None
    daily_buckets: list[DailyBucketDTO]


@dataclass(frozen=True)
class PingDTO:
    monitor_id: UUID
    timestamp: datetime
    latency_ms: int
    status_code: int | None
    outcome: PingOutcome


@dataclass(frozen=True)
class OutageDTO:
    monitor_id: UUID
    started_at: datetime
    resolved_at: datetime | None
    fail_count: int
    last_status_code: int | None
