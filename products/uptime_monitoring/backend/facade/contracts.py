"""
Contract types for uptime_monitoring.

Frozen dataclasses that define what this product exposes.
No Django imports. Used by facade as inputs/outputs.
"""

from datetime import datetime
from uuid import UUID

from pydantic.dataclasses import dataclass

from .enums import UptimeMonitorMethod

MIN_INTERVAL_SECONDS = 60
MAX_INTERVAL_SECONDS = 24 * 60 * 60
DEFAULT_INTERVAL_SECONDS = 300
MIN_TIMEOUT_SECONDS = 1
MAX_TIMEOUT_SECONDS = 10
DEFAULT_TIMEOUT_SECONDS = 10


class UptimeMonitorNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class UptimeMonitor:
    id: UUID
    team_id: int
    name: str
    url: str
    method: UptimeMonitorMethod
    interval_seconds: int
    timeout_seconds: int
    enabled: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CreateUptimeMonitorInput:
    name: str
    url: str
    method: UptimeMonitorMethod = UptimeMonitorMethod.GET
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    enabled: bool = True


@dataclass(frozen=True)
class UpdateUptimeMonitorInput:
    """Fields left as None keep their stored value."""

    name: str | None = None
    url: str | None = None
    method: UptimeMonitorMethod | None = None
    interval_seconds: int | None = None
    timeout_seconds: int | None = None
    enabled: bool | None = None
