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


def create(input: contracts.CreateMonitorInput) -> contracts.MonitorDTO:
    obj = logic.create_monitor(team_id=input.team_id, name=input.name, url=input.url)
    return _to_dto(obj)


def update(input: contracts.UpdateMonitorInput) -> contracts.MonitorDTO:
    obj = logic.update_monitor(team_id=input.team_id, monitor_id=input.monitor_id, name=input.name, url=input.url)
    return _to_dto(obj)


def delete(*, team_id: int, monitor_id: UUID) -> None:
    logic.delete_monitor(team_id=team_id, monitor_id=monitor_id)


def retrieve_monitor_summary(*, team_id: int, monitor_id: UUID) -> contracts.MonitorSummaryDTO | None:
    row = logic.retrieve_monitor_summary(team_id=team_id, monitor_id=monitor_id)
    if row is None:
        return None
    return contracts.MonitorSummaryDTO(
        id=row["id"],
        name=row["name"],
        url=row["url"],
        created_at=row["created_at"],
        status=row["status"],
        uptime_30d=row["uptime_30d"],
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


def bulk_create(input: contracts.BulkCreateMonitorInput) -> list[contracts.MonitorDTO]:
    objs = logic.bulk_create_monitors(
        team_id=input.team_id,
        items=[{"name": item.name, "url": item.url} for item in input.items],
    )
    return [_to_dto(obj) for obj in objs]


def list_all() -> list[contracts.MonitorDTO]:
    return [_to_dto(obj) for obj in logic.list_monitors()]


def list_monitor_summaries(*, team_id: int) -> list[contracts.MonitorSummaryDTO]:
    rows = logic.list_monitor_summaries(team_id=team_id)
    return [
        contracts.MonitorSummaryDTO(
            id=row["id"],
            name=row["name"],
            url=row["url"],
            created_at=row["created_at"],
            status=row["status"],
            uptime_30d=row["uptime_30d"],
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
        for row in rows
    ]


def list_suggested_urls(*, team_id: int, days: int = 30, limit: int = 20) -> list[contracts.SuggestedUrlDTO]:
    rows = logic.list_suggested_urls(team_id=team_id, days=days, limit=limit)
    return [
        contracts.SuggestedUrlDTO(
            url=row["url"],
            host=row["host"],
            event_count=row["event_count"],
            unique_paths=row["unique_paths"],
            last_seen=row["last_seen"],
        )
        for row in rows
    ]


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
