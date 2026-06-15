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
    CachedTraceSpansAttributeBreakdownQueryResponse,
    CachedTraceSpansQueryResponse,
    CompareFilter,
    DateRange,
    PropertyGroupFilter,
    TraceSpanBreakdownOrderBy,
    TraceSpanBreakdownType,
    TraceSpansAttributeBreakdownQueryResponse,
    TraceSpansQueryResponse,
)

from products.tracing.backend.attribute_breakdown_query_runner import (
    run_attribute_breakdown_query as _run_attribute_breakdown_query,
)
from products.tracing.backend.count_query_runner import run_count_query as _run_count_query
from products.tracing.backend.duration_histogram_query_runner import (
    run_duration_histogram_query as _run_duration_histogram_query,
)

if TYPE_CHECKING:
    from posthog.models import Team


# --- Converters (model -> frozen dataclass) ---
#
# These look repetitive when fields align 1:1. The value is having ONE place
# where "internal" becomes "external contract". When models and contracts drift,
# the mapper absorbs the change instead of it leaking everywhere.


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


def run_attribute_breakdown_query(
    *,
    team: "Team",
    date_range: DateRange,
    breakdown_key: str,
    breakdown_type: TraceSpanBreakdownType,
    order_by: TraceSpanBreakdownOrderBy | None = None,
    compare_filter: CompareFilter | None = None,
    filter_group: PropertyGroupFilter | None = None,
    service_names: list[str] | None = None,
) -> TraceSpansAttributeBreakdownQueryResponse | CachedTraceSpansAttributeBreakdownQueryResponse:
    """Run a span breakdown grouped by one attribute's value within a filtered span set."""
    return _run_attribute_breakdown_query(
        team=team,
        date_range=date_range,
        breakdown_key=breakdown_key,
        breakdown_type=breakdown_type,
        order_by=order_by,
        compare_filter=compare_filter,
        filter_group=filter_group,
        service_names=service_names,
    )


def run_duration_histogram_query(
    *,
    team: "Team",
    date_range: DateRange,
    service_names: list[str] | None = None,
    status_codes: list[int] | None = None,
    filter_group: PropertyGroupFilter | None = None,
) -> TraceSpansQueryResponse | CachedTraceSpansQueryResponse:
    """Run the per-bucket trace-duration histogram (root spans, stacked by service)."""
    return _run_duration_histogram_query(
        team=team,
        date_range=date_range,
        service_names=service_names,
        status_codes=status_codes,
        filter_group=filter_group,
    )
