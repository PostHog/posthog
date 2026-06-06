"""
Facade for tracing.

This is the ONLY module other products are allowed to import.

Responsibilities:
- Accept frozen dataclasses as input parameters
- Call business logic (logic.py)
- Convert Django models to frozen dataclasses before returning
- Enforce transactions where needed
- Remain thin and stable

Do NOT:
- Implement business logic here (use logic.py)
- Import DRF, serializers, or HTTP concerns
- Return ORM instances or QuerySets
"""

from typing import TYPE_CHECKING

from posthog.schema import (
    CachedTraceSpansAggregationQueryResponse,
    CachedTraceSpansQueryResponse,
    CachedTraceSpansTreeQueryResponse,
    CompareFilter,
    DateRange,
    PropertyGroupFilter,
    TraceSpansAggregationQueryResponse,
    TraceSpansQuery,
    TraceSpansQueryResponse,
    TraceSpansTreeQueryResponse,
)

from products.tracing.backend import logic as _logic
from products.tracing.backend.count_query_runner import run_count_query as _run_count_query
from products.tracing.backend.has_spans_query_runner import team_has_spans as _team_has_spans
from products.tracing.backend.sparkline_query_runner import run_sparkline_query as _run_sparkline_query

if TYPE_CHECKING:
    from posthog.models import Team


def run_spans_query(
    *,
    team: "Team",
    query: TraceSpansQuery,
) -> TraceSpansQueryResponse | CachedTraceSpansQueryResponse:
    """Run a trace spans query and return the spans response."""
    return _logic.run_spans_query(team=team, query=query)


def run_sparkline_query(
    *,
    team: "Team",
    query: TraceSpansQuery,
) -> TraceSpansQueryResponse | CachedTraceSpansQueryResponse:
    """Run a trace spans sparkline (time-bucketed counts per service)."""
    return _run_sparkline_query(team=team, query=query)


def run_count_query(
    *,
    team: "Team",
    date_range: DateRange,
    service_names: list[str] | None = None,
    status_codes: list[int] | None = None,
    filter_group: PropertyGroupFilter | None = None,
) -> TraceSpansQueryResponse | CachedTraceSpansQueryResponse:
    """Run a cheap scalar count of trace spans matching the given filters."""
    return _run_count_query(
        team=team,
        date_range=date_range,
        service_names=service_names,
        status_codes=status_codes,
        filter_group=filter_group,
    )


def run_aggregation_query(
    *,
    team: "Team",
    date_range: DateRange,
    compare_filter: CompareFilter | None = None,
    filter_group: PropertyGroupFilter | None = None,
    service_names: list[str] | None = None,
) -> TraceSpansAggregationQueryResponse | CachedTraceSpansAggregationQueryResponse:
    """Run a span aggregation query (grouped metrics, optional compare period)."""
    return _logic.run_aggregation_query(
        team=team,
        date_range=date_range,
        compare_filter=compare_filter,
        filter_group=filter_group,
        service_names=service_names,
    )


def run_tree_query(
    *,
    team: "Team",
    date_range: DateRange,
    span_name: str,
    service_name: str,
    compare_filter: CompareFilter | None = None,
    filter_group: PropertyGroupFilter | None = None,
    service_names: list[str] | None = None,
) -> TraceSpansTreeQueryResponse | CachedTraceSpansTreeQueryResponse:
    """Run a span tree aggregation rooted at a given span/service."""
    return _logic.run_tree_query(
        team=team,
        date_range=date_range,
        span_name=span_name,
        service_name=service_name,
        compare_filter=compare_filter,
        filter_group=filter_group,
        service_names=service_names,
    )


def run_service_names_query(
    *,
    team: "Team",
    date_range: DateRange,
    search: str = "",
) -> list[dict]:
    """List distinct service names in the window, optionally filtered by search."""
    return _logic.run_service_names_query(team=team, date_range=date_range, search=search)


def run_attribute_names_query(
    *,
    team: "Team",
    date_range: DateRange,
    attribute_type: str = "span_attribute",
    search: str = "",
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """List span attribute keys (with a total count) for the given attribute type."""
    return _logic.run_attribute_names_query(
        team=team,
        date_range=date_range,
        attribute_type=attribute_type,
        search=search,
        limit=limit,
        offset=offset,
    )


def run_attribute_values_query(
    *,
    team: "Team",
    date_range: DateRange,
    attribute_type: str = "span_attribute",
    attribute_key: str = "",
    search: str = "",
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """List values for a given span attribute key."""
    return _logic.run_attribute_values_query(
        team=team,
        date_range=date_range,
        attribute_type=attribute_type,
        attribute_key=attribute_key,
        search=search,
        limit=limit,
        offset=offset,
    )


def team_has_spans(*, team: "Team") -> bool:
    """Whether the team has ingested any trace spans."""
    return _team_has_spans(team)
