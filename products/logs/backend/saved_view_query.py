from __future__ import annotations

import logging

from pydantic import ValidationError

from posthog.schema import DateRange, FilterLogicalOperator, LogsOrderBy, LogsQuery, PropertyGroupFilter

from posthog.models.team import Team

from products.logs.backend.models import LogsView

logger = logging.getLogger(__name__)


def _filter_group_from_filters(filters: dict) -> PropertyGroupFilter:
    filter_group = filters.get("filterGroup")
    if filter_group:
        return PropertyGroupFilter.model_validate(filter_group)
    return PropertyGroupFilter(type=FilterLogicalOperator.AND_, values=[])


def build_logs_query_for_saved_view(
    team: Team,
    short_id: str,
    *,
    order_by: LogsOrderBy,
    limit: int,
    offset: int = 0,
    exclude_attributes: bool = True,
) -> LogsQuery | None:
    """Resolve a saved logs view into a LogsQuery. Returns None if the view is missing or unusable.

    The saved view owns the date range, severity, service, search, and property filters; the
    caller still controls orderBy and limit. A `None` return lets the caller fall back to its own
    config — this covers both a deleted view and a view whose stored `filters` blob no longer
    matches the schema (the `filters` JSON has no inner validation on write).
    """
    view = LogsView.objects.filter(team=team, short_id=short_id).first()
    if view is None:
        return None

    filters = view.filters or {}
    date_range_raw = filters.get("dateRange") or {}
    try:
        return LogsQuery(
            kind="LogsQuery",
            dateRange=DateRange(date_from=date_range_raw.get("date_from"), date_to=date_range_raw.get("date_to")),
            severityLevels=filters.get("severityLevels") or [],
            serviceNames=filters.get("serviceNames") or [],
            searchTerm=filters.get("searchTerm"),
            filterGroup=_filter_group_from_filters(filters),
            orderBy=order_by,
            limit=limit,
            offset=offset,
            excludeAttributes=exclude_attributes,
        )
    except ValidationError:
        logger.warning("logs_widget_saved_view_filters_invalid", extra={"short_id": short_id, "team_id": team.pk})
        return None
