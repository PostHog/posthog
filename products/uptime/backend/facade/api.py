from __future__ import annotations

from uuid import UUID

from .. import logic
from ..models import Monitor
from . import contracts


def _to_dto(obj: Monitor) -> contracts.MonitorDTO:
    return contracts.MonitorDTO(
        id=obj.id,
        name=obj.name,
        url=obj.url,
        created_at=obj.created_at,
    )


def _summary_dict_to_dto(row: dict) -> contracts.MonitorSummaryDTO:
    return contracts.MonitorSummaryDTO(
        id=row["id"],
        name=row["name"],
        url=row["url"],
        created_at=row["created_at"],
        status=row["status"],
        uptime_90d=row["uptime_90d"],
        avg_latency_24h_ms=row["avg_latency_24h_ms"],
        last_ping_at=row["last_ping_at"],
        last_ping_outcome=row["last_ping_outcome"],
        daily_buckets=[
            contracts.DailyBucketDTO(
                date=bucket["date"],
                total=bucket["total"],
                failed=bucket["failed"],
                status=bucket["status"],
            )
            for bucket in row["daily_buckets"]
        ],
    )


def create(input: contracts.CreateMonitorInput) -> contracts.MonitorDTO:
    obj = logic.create_monitor(team_id=input.team_id, name=input.name, url=input.url)
    return _to_dto(obj)


def update(input: contracts.UpdateMonitorInput) -> contracts.MonitorDTO:
    obj = logic.update_monitor(team_id=input.team_id, monitor_id=input.monitor_id, name=input.name, url=input.url)
    return _to_dto(obj)


def delete(*, team_id: int, monitor_id: UUID) -> None:
    logic.delete_monitor(team_id=team_id, monitor_id=monitor_id)


def list_all() -> list[contracts.MonitorDTO]:
    return [_to_dto(obj) for obj in logic.list_monitors()]


def list_monitor_summaries(*, team_id: int) -> list[contracts.MonitorSummaryDTO]:
    rows = logic.list_monitor_summaries(team_id=team_id)
    return [_summary_dict_to_dto(row) for row in rows]


def retrieve_monitor_summary(*, team_id: int, monitor_id: UUID) -> contracts.MonitorSummaryDTO | None:
    row = logic.retrieve_monitor_summary(team_id=team_id, monitor_id=monitor_id)
    if row is None:
        return None
    return _summary_dict_to_dto(row)


def list_recent_pings(*, team_id: int, monitor_id: UUID, limit: int = 50) -> list[contracts.PingDTO]:
    rows = logic.list_recent_pings(team_id=team_id, monitor_id=monitor_id, limit=limit)
    return [
        contracts.PingDTO(
            monitor_id=row["monitor_id"],
            timestamp=row["timestamp"],
            latency_ms=row["latency_ms"],
            status_code=row["status_code"],
            outcome=row["outcome"],
        )
        for row in rows
    ]


def list_outages_for_monitor(*, team_id: int, monitor_id: UUID, days: int = 7) -> list[contracts.OutageDTO]:
    rows = logic.list_outages_for_monitor(team_id=team_id, monitor_id=monitor_id, days=days)
    return [
        contracts.OutageDTO(
            monitor_id=row["monitor_id"],
            started_at=row["started_at"],
            resolved_at=row["resolved_at"],
            fail_count=row["fail_count"],
            last_status_code=row["last_status_code"],
        )
        for row in rows
    ]
