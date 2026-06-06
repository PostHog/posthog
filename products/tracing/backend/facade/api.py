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

from posthog.schema import CachedTraceSpansQueryResponse, DateRange, PropertyGroupFilter, TraceSpansQueryResponse

from products.tracing.backend.count_query_runner import run_count_query as _run_count_query

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
