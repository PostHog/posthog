"""The error baseline of an observation window: for each UTC hour of a day, the errors in the same hour of each earlier
week.

The error rate is the share of people (or groups) with an event that have at least one `$exception`. A single value
can't be aligned by weekday and hour for a window that spans days, so the baseline keeps the counts of each hour and
week. The window computes the baseline of each UTC day it covers once, and the score compares each bucket after the edit
with the hour that the bucket starts in. `errors_by_hour` counts the day itself the same way, so that the window's error
rate and the baseline share a denominator.

Hours are UTC clock hours. In a timezone with daylight saving time, an earlier week is one hour off the local time of
day for part of the year.

The query reads every event of each day it counts, because the denominator is every person (or group) with an event.
People are counted per kind of actor of the watched flags: persons, or the groups of each group type.
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS
from posthog.hogql.parser import parse_expr

from posthog.dataclasses import frozen
from posthog.models import Team

from products.feature_flags.backend.flag_windows.query import actor_of, run_window_query

BASELINE_WEEKS = 4

HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
WEEK = timedelta(weeks=1)
HOURS_PER_DAY = DAY // HOUR
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
    day: date,
    weeks: int = BASELINE_WEEKS,
) -> dict[int | None, list[BaselineHour]]:
    """The baseline of each UTC hour of `day`, by kind of actor: None for persons, or the group type index."""
    if weeks < 1:
        raise ValueError(f"The baseline needs at least one earlier week, got {weeks}")
    # HogQL caps the rows of a query, and a capped result would drop the latest hours without an error.
    if HOURS_PER_DAY * weeks > MAX_SELECT_RETURNED_ROWS:
        raise ValueError(f"The baseline holds {HOURS_PER_DAY * weeks} hours, more than {MAX_SELECT_RETURNED_ROWS}")
    midnight = datetime.combine(day, time(), tzinfo=UTC)
    counts = _errors_by_hour_and_week(
        team, group_type_indexes, midnight - weeks * WEEK, weeks, "flag_error_baseline_by_hour"
    )
    return {
        actor_kind: [
            BaselineHour(start=midnight + hour * HOUR, weeks=tuple(by_week)) for hour, by_week in enumerate(by_hour)
        ]
        for actor_kind, by_hour in counts.items()
    }


def errors_by_hour(
    team: Team, group_type_indexes: Sequence[int | None], day: date
) -> dict[int | None, list[HourErrors]]:
    """The errors of each UTC hour of `day` itself, by kind of actor, counted like the baseline so that the score
    compares two rates with the same denominator. The list index is the UTC hour."""
    midnight = datetime.combine(day, time(), tzinfo=UTC)
    counts = _errors_by_hour_and_week(team, group_type_indexes, midnight, 1, "flag_errors_by_hour")
    return {actor_kind: [by_week[0] for by_week in by_hour] for actor_kind, by_hour in counts.items()}


def _errors_by_hour_and_week(
    team: Team, group_type_indexes: Sequence[int | None], origin: datetime, weeks: int, query_type: str
) -> dict[int | None, list[list[HourErrors]]]:
    """The errors of `weeks` days one week apart, starting with the day that begins at `origin`, a UTC midnight, by kind
    of actor. The outer index is the UTC hour, and the inner index is the week, latest first."""
    actor_kinds = list(dict.fromkeys(group_type_indexes))
    if not actor_kinds:
        return {}
    counts = {
        actor_kind: [[HourErrors(active=0, with_errors=0) for _ in range(weeks)] for _ in range(HOURS_PER_DAY)]
        for actor_kind in actor_kinds
    }
    for row in run_window_query(team, _query(actor_kinds, origin, weeks), query_type):
        week_from_origin, hour = divmod(int(row[0]), HOURS_PER_WEEK)
        values = iter(row[1:])
        for actor_kind in actor_kinds:
            counts[actor_kind][hour][weeks - week_from_origin - 1] = HourErrors(
                active=int(next(values)), with_errors=int(next(values))
            )
    return counts


def _query(actor_kinds: Sequence[int | None], origin: datetime, weeks: int) -> ast.SelectQuery:
    columns: list[ast.Expr] = []
    for actor_kind in actor_kinds:
        actor = actor_of(actor_kind)
        placeholders = {"actor": actor.expr, "present": actor.present}
        columns.append(parse_expr("uniqIf({actor}, {present})", placeholders=placeholders))
        columns.append(parse_expr("uniqIf({actor}, {present} AND event = '$exception')", placeholders=placeholders))
    # The events table sorts each team's events by day, so a query reads every whole day that it touches. One UTC day
    # per week keeps the query to one day of events per week.
    in_counted_days = ast.Or(
        exprs=[
            parse_expr(
                "timestamp >= {start} AND timestamp < {end}",
                placeholders={
                    "start": ast.Constant(value=origin + week * WEEK),
                    "end": ast.Constant(value=origin + week * WEEK + DAY),
                },
            )
            for week in range(weeks)
        ]
    )
    return ast.SelectQuery(
        select=[
            # The elapsed time from a UTC midnight keeps the hours in UTC, whatever the team's timezone.
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
        where=in_counted_days,
        group_by=[ast.Field(chain=["hour"])],
        order_by=[ast.OrderExpr(expr=ast.Field(chain=["hour"]), order="ASC")],
        # One row per hour and week. HogQL adds LIMIT 100 to a query without one.
        limit=ast.Constant(value=HOURS_PER_DAY * weeks),
    )
