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
class ReorderMonitorsInput:
    team_id: int
    ordered_ids: list[UUID]


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
    uptime_30d: float | None
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
class StatusPageDTO:
    id: UUID
    title: str
    slug: str
    monitor_ids: list[UUID]
    is_published: bool
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class UpdateStatusPageInput:
    team_id: int
    page_id: UUID
    title: str | None = None
    slug: str | None = None
    monitor_ids: list[UUID] | None = None


@dataclass(frozen=True)
class IncidentDTO:
    id: UUID
    monitor_id: UUID
    name: str
    description: str
    started_at: datetime
    resolved_at: datetime | None
    resolution_note: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CreateIncidentInput:
    team_id: int
    monitor_id: UUID
    name: str
    description: str = ""
    started_at: datetime | None = None
    resolved_at: datetime | None = None
    resolution_note: str = ""


@dataclass(frozen=True)
class OutageDTO:
    monitor_id: UUID
    started_at: datetime
    resolved_at: datetime | None
    fail_count: int
    last_status_code: int | None


@dataclass(frozen=True)
class UpdateIncidentInput:
    team_id: int
    incident_id: UUID
    name: str | None = None
    description: str | None = None
    started_at: datetime | None = None
    resolved_at: datetime | None = None
    resolution_note: str | None = None
    clear_resolved_at: bool = False


@dataclass(frozen=True)
class ResolveIncidentInput:
    team_id: int
    incident_id: UUID
    resolution_note: str


@dataclass(frozen=True)
class PublicStatusPageDTO:
    title: str
    monitors: list[MonitorSummaryDTO]
    published_at: datetime | None
    ongoing_incidents: list[IncidentDTO]
    recent_incidents: list[IncidentDTO]
