"""The exposure and the errors after a flag edit by the last value that each person (or group) had, so that people whose
events don't carry the flag count too.

Most server SDKs send no `$feature/<key>` on their events, only a flag call when the value changes. With minimal flag
calls on, even the call doesn't carry it. The counts of `flag_windows/exposure.py` and `flag_windows/errors.py` read
only what each event carries, so they leave out the people of a flag that only a backend evaluates.

A person has, at any event, the value of their latest `$feature/<key>` or flag call at or before it. The exposure and
the errors use that same rule in one query, so that a person with an error under a value always counts in the exposure
under it, and the two counts fail together when the query runs out of time or memory.

- A flag call is read from `LOOKBACK` before the range, also from before the edit, because an SDK sends no new call
  while the value stays the same. A call of the flag counts as an event of the person, so that a service that sends
  only calls and errors has exposure. `$feature/<key>` is read only from the range start and the edit on, because
  reading it for days means reading every event of those days.
- An edit that enables the flag ignores a true from before it, because the flag was disabled since then.
- An event that loaded flags without this one, which an edit that enables the flag reads as unexposed, gives a value
  only to a person without another one. A flag that only a backend evaluates is in no client's flags, so the next
  pageview would otherwise replace the value of the flag call.
- A person counts in a bucket under every value that they had at one of their events in it. The errors that carry no
  value count under the values at the first and at the last of them in the bucket.
- The query keeps the first and the last time of each value per person and bucket, not each event. A value that changes
  back and forth within a bucket can give an error in between the other value.
- Most server SDKs remember the values they sent for a person and don't send one again. A person whose value goes from
  true to false and back to true, without a restart of the SDK, has the value false.
- A person without a value in the lookback counts under no value.
- When the calls are not in the events table, a call of another flag is no event of the person, and a call from before
  the range counts only for a person with an event in the events table.
- A call's response is text, so when the flag serves a variant named "false" the calls give no value.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

import structlog

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.dataclasses import frozen
from posthog.exceptions import (
    ClickHouseEstimatedQueryExecutionTimeTooLong,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQueryTimeOut,
)
from posthog.models import Team

from products.feature_flags.backend.facade.flag_calls import FlagCalls
from products.feature_flags.backend.flag_windows.query import (
    Actor,
    BucketCounts,
    BucketRange,
    FlagRead,
    WatchedEdit,
    actor_of,
    check_edit_ids,
    constants,
    edits_by_actor,
    read_flag,
    run_bucket_query,
)

logger = structlog.get_logger(__name__)

# A server process keeps a value without a new call for as long as it runs.
LOOKBACK = timedelta(days=7)

IN_EARLIER_BUCKETS = "OVER (PARTITION BY actor ORDER BY bucket ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)"
IN_BUCKETS_SO_FAR = "OVER (PARTITION BY actor ORDER BY bucket ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)"


@frozen
class LastValueCounts:
    # The people (or groups) with an event and a value.
    with_flag: int
    # A person whose value changed counts in both, here and in the errors.
    exposed: int
    unexposed: int
    exposed_with_errors: int
    unexposed_with_errors: int


@frozen
class LastValueBucket:
    start: datetime
    in_bucket: LastValueCounts
    # From the edit, or from the range start when it is later, to the end of this bucket. Each person counts once.
    since_edit: LastValueCounts


def last_values_by_bucket(
    team: Team, edits: Sequence[WatchedEdit], start: datetime, end: datetime, bucket: timedelta
) -> dict[str, list[LastValueBucket]]:
    """The counts of each edit in each bucket of `[start, end)`, by edit id, oldest bucket first. A bucket in which
    nobody had a value after the edit has no entry. An edit has no entry when its query runs out of time or memory."""
    bucket_range = BucketRange(start=start, end=end, bucket=bucket)
    check_edit_ids(edits)
    counts: dict[str, list[LastValueBucket]] = {}
    for group_type_index, watched in edits_by_actor(edits).items():
        query = _LastValueQuery(
            team=team,
            group_type_index=group_type_index,
            watched=[_EditColumns(index=index, edit=edit, bucket_range=bucket_range) for index, edit in watched],
            bucket_range=bucket_range,
        )
        try:
            rows = query.run()
        except (
            ClickHouseQueryTimeOut,
            ClickHouseQueryMemoryLimitExceeded,
            ClickHouseEstimatedQueryExecutionTimeTooLong,
        ) as error:
            logger.warning("flag_window_last_values_failed", team_id=team.pk, error_type=type(error).__name__)
            continue
        for edit_id, buckets in rows.items():
            counts[edit_id] = _buckets(buckets)
    return counts


def _buckets(rows: Sequence[BucketCounts]) -> list[LastValueBucket]:
    buckets = [
        LastValueBucket(start=row.start, in_bucket=_counts(row.in_bucket), since_edit=_counts(row.since_edit))
        for row in rows
    ]
    return [bucket for bucket in buckets if bucket.in_bucket.with_flag]


def _counts(values: Sequence[int]) -> LastValueCounts:
    with_flag, exposed, unexposed, exposed_with_errors, unexposed_with_errors = values
    return LastValueCounts(
        with_flag=with_flag,
        exposed=exposed,
        unexposed=unexposed,
        exposed_with_errors=exposed_with_errors,
        unexposed_with_errors=unexposed_with_errors,
    )


@frozen
class _EditColumns:
    """The columns of one edit. A time column has a sentinel where no row matches: `never`, which is before every row,
    for a latest time, and the range end, which is after every row, for an earliest time."""

    index: int
    edit: WatchedEdit
    bucket_range: BucketRange

    @property
    def counts_from(self) -> datetime:
        return max(self.edit.edited_at, self.bucket_range.start)

    @property
    def never(self) -> datetime:
        return self.bucket_range.start - LOOKBACK - timedelta(seconds=1)

    def field(self, column: str) -> ast.Field:
        return ast.Field(chain=[f"{column}{self.index}"])

    def expr(self, template: str, values: Mapping[str, ast.Expr]) -> ast.Expr:
        return parse_expr(
            template,
            placeholders={
                "edited_at": ast.Constant(value=self.edit.edited_at),
                "counts_from": ast.Constant(value=self.counts_from),
                "never": ast.Constant(value=self.never),
                "end": ast.Constant(value=self.bucket_range.end),
                **values,
            },
        )

    def columns(self, templates: Mapping[str, str], values: Mapping[str, ast.Expr]) -> list[ast.Expr]:
        return [
            ast.Alias(alias=f"{column}{self.index}", expr=self.expr(template, values))
            for column, template in templates.items()
        ]

    def of_event(self, read: FlagRead) -> list[ast.Expr]:
        templates = {
            "active": "timestamp >= {counts_from}",
            "exposed": "{carries} AND {exposed} AND timestamp >= {counts_from}",
            "unexposed": "{carries} AND NOT {exposed} AND timestamp >= {counts_from}",
        }
        if self.edit.enables:
            templates["loaded"] = "{with_flag} AND NOT {carries} AND timestamp >= {counts_from}"
        return self.columns(
            templates, {"carries": read.carries_flag, "exposed": read.exposed, "with_flag": read.with_flag}
        )

    def of_call(self, calls: FlagCalls) -> list[ast.Expr]:
        tells_value = "{flag_key} = {key} AND isNotNull({response})"
        if "false" in self.edit.variants:
            tells_value = "false"
        exposed = "{response} != 'false'" if self.edit.variants else "{response} = 'true'"
        templates = {
            "active": "{flag_key} = {key} AND timestamp >= {counts_from}",
            "exposed": f"{tells_value} AND {exposed}",
            "unexposed": f"{tells_value} AND NOT ({exposed})",
        }
        if self.edit.enables:
            # The flag was disabled since a true from before the edit.
            templates["exposed"] += " AND timestamp >= {edited_at}"
            templates["loaded"] = "false"
        return self.columns(
            templates,
            {
                "flag_key": calls.flag_key,
                "key": ast.Constant(value=self.edit.flag_key),
                "response": calls.response,
            },
        )

    def per_bucket(self) -> list[ast.Expr]:
        carries_no_value = "error AND NOT {exposed} AND NOT {unexposed}"
        templates = {
            "first": "min(if({active}, timestamp, {end}))",
            "first_error": f"min(if({carries_no_value} AND timestamp >= {{counts_from}}, timestamp, {{end}}))",
            "last_error": f"max(if({carries_no_value} AND timestamp >= {{counts_from}}, timestamp, {{never}}))",
        }
        for value in ("exposed", "unexposed"):
            templates |= {
                f"first_{value}": f"min(if({{{value}}} AND timestamp >= {{counts_from}}, timestamp, {{end}}))",
                f"last_{value}": f"max(if({{{value}}} AND timestamp >= {{counts_from}}, timestamp, {{never}}))",
                f"before_{value}": f"max(if({{{value}}} AND timestamp < {{counts_from}}, timestamp, {{never}}))",
                f"{value}_error": f"max(error AND {{{value}}})",
            }
        values: dict[str, ast.Expr] = {column: self.field(column) for column in ("active", "exposed", "unexposed")}
        if self.edit.enables:
            templates["first_loaded"] = "min(if({loaded}, timestamp, {end}))"
            values["loaded"] = self.field("loaded")
        return self.columns(templates, values)

    def from_earlier_buckets(self) -> list[ast.Expr]:
        """The latest time of each value before the bucket or the edit, and the earliest time that the actor loaded
        flags."""
        templates: dict[str, str] = {}
        values: dict[str, ast.Expr] = {}
        for value in ("exposed", "unexposed"):
            before, last = f"before_{value}", f"last_{value}"
            templates[f"earlier_{value}"] = (
                f"greatest({{{before}}}, max(greatest({{{before}}}, {{{last}}})) {IN_EARLIER_BUCKETS})"
            )
            values |= {before: self.field(before), last: self.field(last)}
        if self.edit.enables:
            templates["loaded"] = f"min({{first_loaded}}) {IN_BUCKETS_SO_FAR}"
            values["first_loaded"] = self.field("first_loaded")
        return self.columns(templates, values)

    def _latest_at(self, value: str, moment: str) -> ast.Expr:
        return self.expr(
            "greatest({earlier}, if({first} <= {moment}, {first}, {never}), if({last} <= {moment}, {last}, {never}))",
            {
                "earlier": self.field(f"earlier_{value}"),
                "first": self.field(f"first_{value}"),
                "last": self.field(f"last_{value}"),
                "moment": self.field(moment),
            },
        )

    def _had_at(self, value: str, moment: str) -> ast.Expr:
        """The actor had `value` at the time in the column `moment`. Of two values with the same time, exposed wins."""
        template = "{exposed} > {never} AND {exposed} >= {unexposed}"
        if value == "unexposed":
            template = "{unexposed} > {exposed}"
            if self.edit.enables:
                template += (
                    " OR ({exposed} = {never} AND {unexposed} = {never} AND {loaded} < {end} AND {loaded} <= {moment})"
                )
        return self.expr(
            f"{{moment}} > {{never}} AND {{moment}} < {{end}} AND ({template})",
            {
                "exposed": self._latest_at("exposed", moment),
                "unexposed": self._latest_at("unexposed", moment),
                "moment": self.field(moment),
                "loaded": self.field("loaded"),
            },
        )

    def states(self) -> list[ast.Alias]:
        counts = {}
        for value in ("exposed", "unexposed"):
            moments = ["first"]
            if value == "unexposed" and self.edit.enables:
                moments.append("first_loaded")
            counts[value] = ast.Or(
                exprs=[
                    self.expr("{first} < {end}", {"first": self.field(f"first_{value}")}),
                    *[self._had_at(value, moment) for moment in moments],
                ]
            )
            counts[f"{value}_with_errors"] = ast.Or(
                exprs=[
                    self.field(f"{value}_error"),
                    *[self._had_at(value, moment) for moment in ("first_error", "last_error")],
                ]
            )
        return [
            ast.Alias(
                alias=f"{name}{self.index}",
                expr=parse_expr("uniqState(if({count}, actor, NULL))", placeholders={"count": count}),
            )
            for name, count in (
                ("people_with_flag", ast.Or(exprs=[counts["exposed"], counts["unexposed"]])),
                ("people_exposed", counts["exposed"]),
                ("people_unexposed", counts["unexposed"]),
                ("people_exposed_with_errors", counts["exposed_with_errors"]),
                ("people_unexposed_with_errors", counts["unexposed_with_errors"]),
            )
        ]


@frozen
class _LastValueQuery:
    team: Team
    group_type_index: int | None
    watched: Sequence[_EditColumns]
    bucket_range: BucketRange

    def run(self) -> dict[str, tuple[BucketCounts, ...]]:
        states_by_edit = {columns.edit.id: columns.states() for columns in self.watched}
        per_bucket = ast.SelectQuery(
            select=[ast.Field(chain=["bucket"]), *[state for states in states_by_edit.values() for state in states]],
            select_from=ast.JoinExpr(table=self._with_earlier_buckets()),
            group_by=[ast.Field(chain=["bucket"])],
        )
        return run_bucket_query(
            self.team, per_bucket, states_by_edit, self.bucket_range.buckets, "flag_last_values_by_bucket"
        )

    def _with_earlier_buckets(self) -> ast.SelectQuery:
        return ast.SelectQuery(
            select=[
                ast.Field(chain=["*"]),
                *[column for columns in self.watched for column in columns.from_earlier_buckets()],
            ],
            select_from=ast.JoinExpr(table=self._per_actor_and_bucket()),
        )

    def _per_actor_and_bucket(self) -> ast.SelectQuery:
        # The first bucket holds the calls from before the range.
        bucket = self.bucket_range.bucket_of(
            parse_expr(
                "greatest(timestamp, {start})", placeholders={"start": ast.Constant(value=self.bucket_range.start)}
            )
        )
        return ast.SelectQuery(
            select=[
                ast.Field(chain=["actor"]),
                ast.Alias(alias="bucket", expr=bucket),
                *[column for columns in self.watched for column in columns.per_bucket()],
            ],
            select_from=ast.JoinExpr(
                table=ast.SelectSetQuery.create_from_queries([self._events(), self._calls()], "UNION ALL")
            ),
            group_by=[ast.Field(chain=["actor"]), ast.Field(chain=["bucket"])],
        )

    def _events(self) -> ast.SelectQuery:
        actor = actor_of(self.group_type_index)
        return ast.SelectQuery(
            select=[
                ast.Alias(alias="actor", expr=actor.expr),
                ast.Field(chain=["timestamp"]),
                ast.Alias(alias="error", expr=parse_expr("event = '$exception'")),
                *[
                    column
                    for columns in self.watched
                    for column in columns.of_event(read_flag(columns.edit, in_condition={}))
                ],
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=self._has_event_in_range(actor),
        )

    def _calls(self) -> ast.SelectQuery:
        calls = FlagCalls.of(self.team)
        actor = calls.actor_column(self.group_type_index)
        present = actor_of(self.group_type_index).present
        return ast.SelectQuery(
            select=[
                ast.Alias(alias="actor", expr=actor),
                ast.Field(chain=["timestamp"]),
                ast.Alias(alias="error", expr=ast.Constant(value=False)),
                *[column for columns in self.watched for column in columns.of_call(calls)],
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=list(calls.table))),
            # Most people with a call in the lookback have no event in the range, and no bucket counts them. Without
            # them the GROUP BY holds only the active people.
            where=parse_expr(
                """
                {only_calls}
                    AND timestamp >= {since}
                    AND timestamp < {end}
                    AND {flag_key} IN {flag_keys}
                    AND {present}
                    AND (timestamp >= {start} OR {actor} IN {active_actors})
                """,
                placeholders={
                    "only_calls": calls.only_calls,
                    "since": ast.Constant(value=self.bucket_range.start - LOOKBACK),
                    "end": ast.Constant(value=self.bucket_range.end),
                    "flag_key": calls.flag_key,
                    "flag_keys": constants(columns.edit.flag_key for columns in self.watched),
                    "present": present,
                    "start": ast.Constant(value=self.bucket_range.start),
                    "actor": actor,
                    "active_actors": self._active_actors(),
                },
            ),
        )

    def _active_actors(self) -> ast.SelectQuery:
        actor = actor_of(self.group_type_index)
        return ast.SelectQuery(
            select=[actor.expr],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=self._has_event_in_range(actor),
        )

    def _has_event_in_range(self, actor: Actor) -> ast.Expr:
        return parse_expr(
            "timestamp >= {start} AND timestamp < {end} AND {present}",
            placeholders={
                "start": ast.Constant(value=self.bucket_range.start),
                "end": ast.Constant(value=self.bucket_range.end),
                "present": actor.present,
            },
        )
