"""Shared `QueryDateRange` construction for tracing HogQL (filter placeholders, attribute rollups)."""

import datetime as dt
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from posthog.schema import DateRange, IntervalType

from posthog.hogql_queries.utils.query_date_range import QueryDateRange

if TYPE_CHECKING:
    from posthog.models import Team


def tracing_qdr_minutely(team: "Team", date_range: DateRange) -> QueryDateRange:
    """Coarse minute buckets (interval_count=2) for filter `time_bucket` placeholders."""
    return QueryDateRange(
        date_range=date_range,
        team=team,
        interval=IntervalType.MINUTE,
        interval_count=2,
        now=dt.datetime.now(),
    )


def tracing_qdr_baseline(team: "Team", date_range: DateRange) -> QueryDateRange:
    """Wider minute grid for `trace_attributes` baseline queries (matches attribute picker)."""
    return QueryDateRange(
        date_range=date_range,
        team=team,
        interval=IntervalType.MINUTE,
        interval_count=10,
        now=dt.datetime.now(),
        timezone_info=ZoneInfo("UTC"),
    )
