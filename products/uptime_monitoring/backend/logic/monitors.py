from dataclasses import asdict
from uuid import UUID

from ..facade.contracts import CreateUptimeMonitorInput, UpdateUptimeMonitorInput, UptimeMonitorNotFoundError
from ..models import UptimeMonitor


def get_monitor(team_id: int, monitor_id: UUID) -> UptimeMonitor:
    try:
        return UptimeMonitor.objects.for_team(team_id).get(id=monitor_id)
    except UptimeMonitor.DoesNotExist as e:
        raise UptimeMonitorNotFoundError(f"Uptime monitor {monitor_id} not found") from e


def list_monitors(team_id: int, *, limit: int, offset: int) -> tuple[list[UptimeMonitor], int]:
    monitors = UptimeMonitor.objects.for_team(team_id)
    return list(monitors.order_by("-created_at", "id")[offset : offset + limit]), monitors.count()


def create_monitor(team_id: int, created_by_id: int | None, data: CreateUptimeMonitorInput) -> UptimeMonitor:
    return UptimeMonitor.objects.for_team(team_id).create(team_id=team_id, created_by_id=created_by_id, **asdict(data))


def update_monitor(team_id: int, monitor_id: UUID, data: UpdateUptimeMonitorInput) -> UptimeMonitor:
    monitor = get_monitor(team_id, monitor_id)
    changes = {field: value for field, value in asdict(data).items() if value is not None}
    for field, value in changes.items():
        setattr(monitor, field, value)
    if changes:
        monitor.save(update_fields=[*changes, "updated_at"])
    return monitor


def delete_monitor(team_id: int, monitor_id: UUID) -> None:
    get_monitor(team_id, monitor_id).delete()
