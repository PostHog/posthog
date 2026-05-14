from __future__ import annotations

from uuid import UUID

from .. import logic
from ..models import Incident, Monitor, StatusPage
from . import contracts


def _to_dto(obj: Monitor) -> contracts.MonitorDTO:
    return contracts.MonitorDTO(
        id=obj.id,
        name=obj.name,
        url=obj.url,
        created_at=obj.created_at,
    )


def _incident_to_dto(incident: Incident) -> contracts.IncidentDTO:
    return contracts.IncidentDTO(
        id=incident.id,
        monitor_id=incident.monitor_id,
        name=incident.name,
        description=incident.description,
        started_at=incident.started_at,
        resolved_at=incident.resolved_at,
        resolution_note=incident.resolution_note,
        created_at=incident.created_at,
        updated_at=incident.updated_at,
    )


def _status_page_to_dto(page: StatusPage) -> contracts.StatusPageDTO:
    return contracts.StatusPageDTO(
        id=page.id,
        title=page.title,
        slug=page.slug,
        monitor_ids=list(page.monitor_ids),
        is_published=page.is_published,
        published_at=page.published_at,
        created_at=page.created_at,
        updated_at=page.updated_at,
    )


def _summary_dict_to_dto(row: dict) -> contracts.MonitorSummaryDTO:
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


def create(input: contracts.CreateMonitorInput) -> contracts.MonitorDTO:
    obj = logic.create_monitor(team_id=input.team_id, name=input.name, url=input.url)
    return _to_dto(obj)


def update(input: contracts.UpdateMonitorInput) -> contracts.MonitorDTO:
    obj = logic.update_monitor(team_id=input.team_id, monitor_id=input.monitor_id, name=input.name, url=input.url)
    return _to_dto(obj)


def delete(*, team_id: int, monitor_id: UUID) -> None:
    logic.delete_monitor(team_id=team_id, monitor_id=monitor_id)


def reorder(input: contracts.ReorderMonitorsInput) -> None:
    logic.reorder_monitors(team_id=input.team_id, ordered_ids=input.ordered_ids)


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
    return [_summary_dict_to_dto(row) for row in rows]


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


def create_status_page(*, team_id: int) -> contracts.StatusPageDTO:
    return _status_page_to_dto(logic.create_status_page(team_id=team_id))


def list_status_pages(*, team_id: int) -> list[contracts.StatusPageDTO]:
    return [_status_page_to_dto(p) for p in logic.list_status_pages(team_id=team_id)]


def get_status_page(*, team_id: int, page_id: UUID) -> contracts.StatusPageDTO:
    return _status_page_to_dto(logic.get_status_page(team_id=team_id, page_id=page_id))


def update_status_page(input: contracts.UpdateStatusPageInput) -> contracts.StatusPageDTO:
    return _status_page_to_dto(
        logic.update_status_page(
            team_id=input.team_id,
            page_id=input.page_id,
            title=input.title,
            slug=input.slug,
            monitor_ids=input.monitor_ids,
        )
    )


def publish_status_page(*, team_id: int, page_id: UUID) -> contracts.StatusPageDTO:
    return _status_page_to_dto(logic.publish_status_page(team_id=team_id, page_id=page_id))


def unpublish_status_page(*, team_id: int, page_id: UUID) -> contracts.StatusPageDTO:
    return _status_page_to_dto(logic.unpublish_status_page(team_id=team_id, page_id=page_id))


def delete_status_page(*, team_id: int, page_id: UUID) -> None:
    logic.delete_status_page(team_id=team_id, page_id=page_id)


def get_public_status_page(*, slug: str) -> contracts.PublicStatusPageDTO | None:
    view = logic.get_public_status_page_view(slug=slug)
    if view is None:
        return None
    return contracts.PublicStatusPageDTO(
        title=view["title"],
        monitors=[_summary_dict_to_dto(row) for row in view["monitors"]],
        published_at=view["published_at"],
        ongoing_incidents=[_incident_to_dto(i) for i in view["ongoing_incidents"]],
        recent_incidents=[_incident_to_dto(i) for i in view["recent_incidents"]],
    )


def create_incident(input: contracts.CreateIncidentInput) -> contracts.IncidentDTO:
    return _incident_to_dto(
        logic.create_incident(
            team_id=input.team_id,
            monitor_id=input.monitor_id,
            name=input.name,
            description=input.description,
            started_at=input.started_at,
            resolved_at=input.resolved_at,
            resolution_note=input.resolution_note,
        )
    )


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


def update_incident(input: contracts.UpdateIncidentInput) -> contracts.IncidentDTO:
    return _incident_to_dto(
        logic.update_incident(
            team_id=input.team_id,
            incident_id=input.incident_id,
            name=input.name,
            description=input.description,
            started_at=input.started_at,
            resolved_at=input.resolved_at,
            resolution_note=input.resolution_note,
            clear_resolved_at=input.clear_resolved_at,
        )
    )


def resolve_incident(input: contracts.ResolveIncidentInput) -> contracts.IncidentDTO:
    return _incident_to_dto(
        logic.resolve_incident(
            team_id=input.team_id,
            incident_id=input.incident_id,
            resolution_note=input.resolution_note,
        )
    )


def reopen_incident(*, team_id: int, incident_id: UUID) -> contracts.IncidentDTO:
    return _incident_to_dto(logic.reopen_incident(team_id=team_id, incident_id=incident_id))


def delete_incident(*, team_id: int, incident_id: UUID) -> None:
    logic.delete_incident(team_id=team_id, incident_id=incident_id)


def get_incident(*, team_id: int, incident_id: UUID) -> contracts.IncidentDTO:
    return _incident_to_dto(logic.get_incident(team_id=team_id, incident_id=incident_id))


def list_incidents(*, team_id: int) -> list[contracts.IncidentDTO]:
    return [_incident_to_dto(i) for i in logic.list_incidents(team_id=team_id)]


def list_incidents_for_monitor(*, team_id: int, monitor_id: UUID) -> list[contracts.IncidentDTO]:
    return [_incident_to_dto(i) for i in logic.list_incidents_for_monitor(team_id=team_id, monitor_id=monitor_id)]
