from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from posthog.utils import relative_date_parse

if TYPE_CHECKING:
    from posthog.models import Team


def metric_check_window_start(query: dict[str, Any], team: Team, now: datetime) -> datetime:
    from posthog.schema import DateRange, IntervalType  # noqa: PLC0415 — keeps the generated schema off startup

    from posthog.hogql_queries.utils.query_date_range import (
        QueryDateRange,  # noqa: PLC0415 — keeps query runners off startup
    )

    return (
        QueryDateRange(
            date_range=DateRange.model_validate(query["source"]["dateRange"]),
            team=team,
            interval=IntervalType.DAY,
            now=now,
            exact_timerange=bool(query["source"]["dateRange"].get("explicitDate")),
        )
        .date_from()
        .astimezone(UTC)
    )


def metric_check_ready_at(query: dict[str, Any], team: Team, start_at: datetime) -> datetime:
    date_range = query["source"]["dateRange"]
    date_from = date_range["date_from"]
    candidate = relative_date_parse(date_from, team.timezone_info, now=start_at, increase=True)
    step = timedelta(hours=1) if date_from.endswith("h") else timedelta(days=1)
    if not date_range.get("explicitDate"):
        rounded = candidate.replace(minute=0, second=0, microsecond=0)
        if not date_from.endswith("h"):
            rounded = rounded.replace(hour=0)
        candidate = rounded if rounded == candidate else rounded + step
    # Calendar month subtraction can reach before the anchor even after adding one month.
    while metric_check_window_start(query, team, candidate) < start_at.astimezone(UTC):
        candidate += step
    return candidate.astimezone(UTC)
