"""The error baseline of an observation window: for each hour of the window, the errors in the same hour of each earlier
week.

The error rate is the share of people (or groups) with an event that have at least one `$exception`. A single value
can't be aligned by weekday and hour for a window that spans days, so the baseline keeps the counts of each hour and
week. The window computes the baseline once, when it opens, and the score compares the errors after the edit with it.

A week is 168 hours from the window start. Across a daylight saving change, an earlier week is one hour off the local
time of day.

The query reads every event of each earlier week in the window's hours, because the denominator is every person (or
group) with an event. People are counted per kind of actor of the watched flags: persons, or the groups of each group
type.
"""

import math
from collections.abc import Sequence
from datetime import datetime, timedelta

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS
from posthog.hogql.parser import parse_expr

from posthog.dataclasses import frozen
from posthog.models import Team

from products.feature_flags.backend.flag_windows.query import actor_of, run_window_query

BASELINE_WEEKS = 4

HOUR = timedelta(hours=1)
WEEK = timedelta(weeks=1)
HOURS_PER_WEEK = WEEK // HOUR


@frozen
class HourErrors:
    # The people (or groups) with any event in the hour. Zero also means that the team sent no events, for example
    # before the team existed.
    active: int
    with_errors: int


@frozen
class BaselineHour:
    start: datetime
    # The same hour one week earlier, then two weeks earlier, and so on.
    weeks: tuple[HourErrors, ...]


def error_baseline(
    team: Team,
    group_type_indexes: Sequence[int | None],
    start: datetime,
    end: datetime,
    weeks: int = BASELINE_WEEKS,
) -> dict[int | None, list[BaselineHour]]:
    """The baseline of each hour of `[start, end)`, by kind of actor: None for persons, or the group type index. The
    hours start at `start`, and the last one is a full hour even when `end` cuts it."""
    if weeks < 1:
        raise ValueError(f"The baseline needs at least one earlier week, got {weeks}")
    if end <= start:
        raise ValueError(f"The range must end after it starts, got {start} to {end}")
    # Each earlier week must leave the range before the next week's copy of it starts, or one event would count twice.
    if end - start > WEEK:
        raise ValueError(f"The range must fit in one week, got {start} to {end}")
    hours = math.ceil((end - start) / HOUR)
    # HogQL caps the rows of a query, and a capped result would drop the latest hours without an error.
    if hours * weeks > MAX_SELECT_RETURNED_ROWS:
        raise ValueError(f"The baseline holds {hours * weeks} hours, more than {MAX_SELECT_RETURNED_ROWS}")
    actor_kinds = list(dict.fromkeys(group_type_indexes))
    if not actor_kinds:
        return {}

    origin = start - weeks * WEEK
    counts = {
        actor: [[HourErrors(active=0, with_errors=0) for _ in range(weeks)] for _ in range(hours)]
        for actor in actor_kinds
    }
    for row in run_window_query(team, _query(actor_kinds, origin, hours, weeks), "flag_error_baseline_by_hour"):
        week_from_origin, hour = divmod(int(row[0]), HOURS_PER_WEEK)
        values = iter(row[1:])
        for actor in actor_kinds:
            counts[actor][hour][weeks - week_from_origin - 1] = HourErrors(
                active=int(next(values)), with_errors=int(next(values))
            )
    return {
        actor: [
            BaselineHour(start=start + hour * HOUR, weeks=tuple(by_week)) for hour, by_week in enumerate(counts[actor])
        ]
        for actor in actor_kinds
    }


def _query(actor_kinds: Sequence[int | None], origin: datetime, hours: int, weeks: int) -> ast.SelectQuery:
    columns: list[ast.Expr] = []
    for actor_kind in actor_kinds:
        actor = actor_of(actor_kind)
        placeholders = {"actor": actor.expr, "present": actor.present}
        columns.append(parse_expr("uniqIf({actor}, {present})", placeholders=placeholders))
        columns.append(parse_expr("uniqIf({actor}, {present} AND event = '$exception')", placeholders=placeholders))
    in_earlier_weeks = ast.Or(
        exprs=[
            parse_expr(
                "timestamp >= {start} AND timestamp < {end}",
                placeholders={
                    "start": ast.Constant(value=origin + week * WEEK),
                    "end": ast.Constant(value=origin + week * WEEK + hours * HOUR),
                },
            )
            for week in range(weeks)
        ]
    )
    return ast.SelectQuery(
        select=[
            # Hours count from the origin, not from clock hours, so they line up with the window's buckets in any
            # timezone. Seconds would drop the fraction of the edit time and move events at an hour boundary.
            ast.Alias(
                alias="hour",
                expr=parse_expr(
                    "intDiv(dateDiff('microsecond', {origin}, timestamp), 3600000000)",
                    placeholders={"origin": ast.Constant(value=origin)},
                ),
            ),
            *columns,
        ],
        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        where=in_earlier_weeks,
        group_by=[ast.Field(chain=["hour"])],
        order_by=[ast.OrderExpr(expr=ast.Field(chain=["hour"]), order="ASC")],
        # One row per hour and week. HogQL adds LIMIT 100 to a query without one.
        limit=ast.Constant(value=hours * weeks),
    )
