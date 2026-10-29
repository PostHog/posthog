"""
Facade for uptime_monitoring.

The ONLY module other products are allowed to import.
Accept frozen dataclasses, call logic/, return frozen
dataclasses. Never return ORM instances or import DRF.
"""

from __future__ import annotations

from uuid import UUID

from ..feature_flags import is_uptime_monitoring_enabled
from ..logic import monitors
from ..models import UptimeMonitor as UptimeMonitorModel
from . import contracts
from .enums import UptimeMonitorMethod


def is_enabled(team_id: int) -> bool:
    return is_uptime_monitoring_enabled(team_id)


def _to_contract(monitor: UptimeMonitorModel) -> contracts.UptimeMonitor:
    return contracts.UptimeMonitor(
        id=monitor.id,
        team_id=monitor.team_id,
        name=monitor.name,
        url=monitor.url,
        method=UptimeMonitorMethod(monitor.method),
        interval_seconds=monitor.interval_seconds,
        timeout_seconds=monitor.timeout_seconds,
        enabled=monitor.enabled,
        created_at=monitor.created_at,
        updated_at=monitor.updated_at,
    )


def list_monitors(team_id: int, *, limit: int, offset: int) -> tuple[list[contracts.UptimeMonitor], int]:
    """One page of the team's monitors, newest first, and the total count, paged in SQL."""
    page, count = monitors.list_monitors(team_id, limit=limit, offset=offset)
    return [_to_contract(m) for m in page], count


def get_monitor(team_id: int, monitor_id: UUID) -> contracts.UptimeMonitor:
    return _to_contract(monitors.get_monitor(team_id, monitor_id))


def create_monitor(
    team_id: int, created_by_id: int | None, data: contracts.CreateUptimeMonitorInput
) -> contracts.UptimeMonitor:
    return _to_contract(monitors.create_monitor(team_id, created_by_id, data))


def update_monitor(team_id: int, monitor_id: UUID, data: contracts.UpdateUptimeMonitorInput) -> contracts.UptimeMonitor:
    return _to_contract(monitors.update_monitor(team_id, monitor_id, data))


def delete_monitor(team_id: int, monitor_id: UUID) -> None:
    monitors.delete_monitor(team_id, monitor_id)
