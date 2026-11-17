"""The errors after a flag edit: in each time bucket, how many people hit an error, and how the people whose error event
carries the flag split between the value that the edit started serving and the other values.

Flag rollback suggestions attribute errors to an edit from this split and from the exposure curve:

- Level 1 compares the error rate of the exposed people with the rest of the people with the flag. Only an error event
  that carries `$feature/<key>` tells which value its person had, and client SDKs attach the flags to `$exception`,
  but server SDKs mostly don't.
- Level 2 makes the same split by the last value: an error event without the flag takes the value of its person's last event
  with the flag at or before it, so server errors count too.
- Levels 4 and 5 follow all errors over time. An error of an issue first seen after the edit is stronger evidence than
  an older error that became more frequent.

One query reads the `$exception` events, and the flag calls of the watched flags for the counts in the watched
conditions. Level 2 is a second query, because it also reads the other events of the people with an error. When it runs
out of time or memory, the counts by last value are left out and the other counts stay. `flag_windows/query.py` holds the
counting rules.
"""

from collections.abc import Mapping, Sequence
from dataclasses import field, replace
from datetime import datetime, timedelta

import structlog

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.visitor import clone_expr

from posthog.dataclasses import frozen
from posthog.exceptions import (
    ClickHouseEstimatedQueryExecutionTimeTooLong,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQueryTimeOut,
)
from posthog.models import Team

from products.feature_flags.backend.flag_windows.query import (
    ConditionMatch,
    EditCounts,
    FlagRead,
    LastValue,
    WatchedEdit,
    counts_by_bucket,
    in_condition_columns,
    last_values,
    read_in_condition,
)

logger = structlog.get_logger(__name__)


@frozen
class ConditionErrors:
    exposed_with_errors: int
    unexposed_with_errors: int


@frozen
class ErrorsByLastValue:
    # An error without a known value counts in neither.
    exposed_with_errors: int
    unexposed_with_errors: int


@frozen
class ErrorCounts:
    # The people (or groups) with an error, whether or not the error event carries the flag.
    with_errors: int
    # The people (or groups) with an error of an issue first seen after the edit.
    with_new_errors: int
    # The people (or groups) whose error event carries a value other than false.
    exposed_with_errors: int
    # The people (or groups) whose error event carries the flag with the value false, or no value when the edit
    # enables the flag.
    unexposed_with_errors: int
    # The people (or groups) whose error event carries each variant that the flag serves. Empty for a boolean flag.
    by_variant: Mapping[str, int]
    # The exposed and unexposed counts, only for the people (or groups) in the watched conditions. Empty without
    # watched conditions.
    in_condition: Mapping[ConditionMatch, ConditionErrors] = field(default_factory=dict)
    # The same split by the value that the person (or group) had at the error, from their last event with the flag.
    # None when the level 2 query runs out of time or memory.
    by_last_value: ErrorsByLastValue | None = None


@frozen
class ErrorBucket:
    start: datetime
    in_bucket: ErrorCounts
    # From the edit, or from the range start when it is later, to the end of this bucket. Each person counts once.
    since_edit: ErrorCounts


def errors_by_bucket(
    team: Team, edits: Sequence[WatchedEdit], start: datetime, end: datetime, bucket: timedelta
) -> dict[str, list[ErrorBucket]]:
    """The errors after each edit in each bucket of `[start, end)`, by edit id, oldest bucket first. A bucket without
    errors after the edit has no entry."""
    counts = counts_by_bucket(
        team,
        edits,
        _counts,
        start,
        end,
        bucket,
        query_type="flag_errors_by_bucket",
        event="$exception",
        joins=[_issue_first_seen_join()],
    )
    by_last_value = _errors_by_last_value(team, edits, start, end, bucket)
    return {edit.id: _buckets(edit, counts[edit.id], by_last_value.get(edit.id)) for edit in edits}


def _errors_by_last_value(
    team: Team, edits: Sequence[WatchedEdit], start: datetime, end: datetime, bucket: timedelta
) -> dict[str, EditCounts]:
    """The level 2 counts of each edit, or no entry when the query runs out of time or memory."""
    # The counts by last value don't use the watched conditions, so the query leaves out the joins that read them.
    edits = [replace(edit, conditions=()) for edit in edits]
    before_error = last_values(team, edits, start, end, counted_event="$exception")
    try:
        return counts_by_bucket(
            team,
            edits,
            lambda edit, read: _counts_by_last_value(read, before_error.by_edit[edit.id]),
            start,
            end,
            bucket,
            query_type="flag_errors_by_last_value_by_bucket",
            event="$exception",
            joins=before_error.joins,
        )
    except (
        ClickHouseQueryTimeOut,
        ClickHouseQueryMemoryLimitExceeded,
        ClickHouseEstimatedQueryExecutionTimeTooLong,
    ) as error:
        logger.warning("flag_window_errors_by_last_value_failed", team_id=team.pk, error_type=type(error).__name__)
        return {}


def _buckets(edit: WatchedEdit, counts: EditCounts, by_last_value: EditCounts | None) -> list[ErrorBucket]:
    last_value_rows = {row.start: row for row in by_last_value.buckets} if by_last_value is not None else {}

    def errors(values: tuple[int, ...], split_values: tuple[int, ...] | None) -> ErrorCounts:
        split = (
            ErrorsByLastValue(exposed_with_errors=split_values[0], unexposed_with_errors=split_values[1])
            if split_values is not None
            else None
        )
        return replace(_errors(edit, counts.matches, values), by_last_value=split)

    buckets = []
    for row in counts.buckets:
        last_value_row = last_value_rows.get(row.start)
        in_bucket = errors(row.in_bucket, last_value_row.in_bucket if last_value_row else None)
        if not in_bucket.with_errors:
            continue
        since_edit = errors(row.since_edit, last_value_row.since_edit if last_value_row else None)
        buckets.append(ErrorBucket(start=row.start, in_bucket=in_bucket, since_edit=since_edit))
    return buckets


def _issue_first_seen_join() -> ast.JoinExpr:
    # Error tracking stores the first seen time per fingerprint, and a merged issue has many fingerprints. The join
    # keeps the earliest one, so a new fingerprint does not make an old issue look new. One join serves every edit,
    # because a subquery per edit would read all fingerprints of the team again for each edit.
    return ast.JoinExpr(
        join_type="LEFT JOIN",
        table=parse_select(
            """
            SELECT issue_id, min(first_seen) AS first_seen
            FROM posthog.error_tracking_fingerprint_issue_state
            GROUP BY issue_id
            """
        ),
        alias="earliest_issue_seen",
        constraint=ast.JoinConstraint(
            expr=parse_expr("earliest_issue_seen.issue_id = events.issue_id"), constraint_type="ON"
        ),
    )


def _counts_by_last_value(read: FlagRead, last: LastValue) -> list[ast.Expr]:
    # Each run of the query resolves its own tree, so the expressions shared across runs are copied.
    known = parse_expr(
        "{with_flag} OR {known}", placeholders={"with_flag": read.with_flag, "known": clone_expr(last.known)}
    )
    exposed = parse_expr(
        "if({with_flag}, {exposed}, {last_exposed})",
        placeholders={"with_flag": read.with_flag, "exposed": read.exposed, "last_exposed": clone_expr(last.exposed)},
    )
    return [ast.And(exprs=[known, exposed]), ast.And(exprs=[known, ast.Not(expr=exposed)])]


def _counts(edit: WatchedEdit, read: FlagRead) -> list[ast.Expr]:
    unexposed = parse_expr(
        "{with_flag} AND NOT {exposed}",
        placeholders={"with_flag": read.with_flag, "exposed": read.exposed},
    )
    return [
        ast.Constant(value=True),
        # A fingerprint that isn't synced to ClickHouse yet has no issue, and counts as new. An event without a
        # fingerprint has no issue either, for example when cymbal can't process the exception, so it doesn't count.
        parse_expr(
            """
            (isNull(events.issue_id) AND isNotNull(properties.$exception_fingerprint))
            OR earliest_issue_seen.first_seen >= {edited_at}
            """,
            placeholders={"edited_at": ast.Constant(value=edit.edited_at)},
        ),
        read.exposed,
        unexposed,
        *[read.has_variant(variant) for variant in edit.variants],
        *in_condition_columns(read, [read.exposed, unexposed]),
    ]


def _errors(edit: WatchedEdit, matches: Sequence[ConditionMatch], values: tuple[int, ...]) -> ErrorCounts:
    with_errors, with_new_errors, exposed_with_errors, unexposed_with_errors, *rest = values
    by_variant, in_condition_values = rest[: len(edit.variants)], rest[len(edit.variants) :]
    return ErrorCounts(
        with_errors=with_errors,
        with_new_errors=with_new_errors,
        exposed_with_errors=exposed_with_errors,
        unexposed_with_errors=unexposed_with_errors,
        by_variant=dict(zip(edit.variants, by_variant, strict=True)),
        in_condition={
            match: ConditionErrors(exposed_with_errors=counts[0], unexposed_with_errors=counts[1])
            for match, counts in read_in_condition(matches, in_condition_values).items()
        },
    )
