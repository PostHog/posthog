from datetime import datetime
from typing import Any
from uuid import UUID

from posthog.schema import DateRange, ErrorTrackingQuery

from posthog.models.team.team import Team

from products.error_tracking.backend.facade import contracts
from products.error_tracking.backend.facade.queries import run_error_tracking_query


def list_active_issue_impact(team_id: int, days: int, limit: int) -> list[contracts.ErrorTrackingIssueImpact]:
    """Active issues seen in the last `days` days, newest first seen first."""
    team = Team.objects.get(id=team_id)
    query = ErrorTrackingQuery(
        kind="ErrorTrackingQuery",
        dateRange=DateRange(date_from=f"-{days}d"),
        status="active",
        filterTestAccounts=True,
        volumeResolution=days,
        limit=limit,
        orderBy="first_seen",
        orderDirection="DESC",
        withAggregations=True,
        withFirstEvent=False,
        withLastEvent=False,
        tags={"productKey": "error_tracking"},
    )
    data = run_error_tracking_query(team, query)
    results = data.get("results") or []
    return [_to_issue_impact(row) for row in results if row.get("first_seen") and row.get("last_seen")]


def _to_issue_impact(row: dict[str, Any]) -> contracts.ErrorTrackingIssueImpact:
    aggregations = row.get("aggregations") or {}
    return contracts.ErrorTrackingIssueImpact(
        id=UUID(row["id"]),
        name=row.get("name"),
        description=row.get("description"),
        severity=row.get("severity"),
        is_assigned=row.get("assignee") is not None,
        source=row.get("source"),
        first_seen=_parse_datetime(row["first_seen"]),
        last_seen=_parse_datetime(row["last_seen"]),
        occurrences=int(aggregations.get("occurrences") or 0),
        users=int(aggregations.get("users") or 0),
        sessions=int(aggregations.get("sessions") or 0),
        daily_occurrences=tuple(int(count or 0) for count in aggregations.get("volumeRange") or []),
    )


def _parse_datetime(value: str | datetime) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)
