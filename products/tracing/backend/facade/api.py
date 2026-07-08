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
    CachedTraceSpansSymbolStatsQueryResponse,
    CompareFilter,
    DateRange,
    PropertyGroupFilter,
    SourceSymbol,
    TraceSpanBreakdownOrderBy,
    TraceSpanBreakdownType,
    TraceSpansAttributeBreakdownQueryResponse,
    TraceSpansQueryResponse,
    TraceSpansSymbolStatsQueryResponse,
)

from products.tracing.backend.attribute_breakdown_query_runner import (
    FACET_COLUMNS as _FACET_COLUMNS,
    run_attribute_breakdown_query as _run_attribute_breakdown_query,
)
from products.tracing.backend.count_query_runner import run_count_query as _run_count_query
from products.tracing.backend.duration_histogram_query_runner import (
    run_duration_histogram_query as _run_duration_histogram_query,
)
from products.tracing.backend.self_time import annotate_self_time as _annotate_self_time
from products.tracing.backend.symbol_stats_query_runner import run_symbol_stats_query as _run_symbol_stats_query

if TYPE_CHECKING:
    from posthog.models import Team


# Allowlisted top-level span columns for the "span" breakdown type. Re-exported so the
# presentation layer can validate `breakdownKey` without reaching into the query runner.
FACET_COLUMNS = _FACET_COLUMNS


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
    exclude_breakdown_filter: bool = False,
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
        exclude_breakdown_filter=exclude_breakdown_filter,
    )


def run_symbol_stats_query(
    *,
    team: "Team",
    file_path: str,
    date_range: DateRange,
    symbols: list[SourceSymbol] | None = None,
) -> TraceSpansSymbolStatsQueryResponse | CachedTraceSpansSymbolStatsQueryResponse:
    """Run per-line (no symbols) or per-symbol latency stats for one source file, vs the prior period."""
    return _run_symbol_stats_query(
        team=team,
        file_path=file_path,
        date_range=date_range,
        symbols=symbols,
    )


def run_duration_histogram_query(
    *,
    team: "Team",
    date_range: DateRange,
    service_names: list[str] | None = None,
    status_codes: list[int] | None = None,
    filter_group: PropertyGroupFilter | None = None,
    root_spans: bool = True,
) -> TraceSpansQueryResponse | CachedTraceSpansQueryResponse:
    """Run the per-bucket duration histogram, stacked by service.

    Root spans by default (a distribution of traces); `root_spans=False` buckets every
    matching span — pair with a span name filter for operation-scoped distributions.
    """
    return _run_duration_histogram_query(
        team=team,
        date_range=date_range,
        service_names=service_names,
        status_codes=status_codes,
        filter_group=filter_group,
        root_spans=root_spans,
    )


def annotate_self_time(spans: list[dict]) -> None:
    """Set `self_time_nano` on every span dict of a full trace, in place."""
    _annotate_self_time(spans)
