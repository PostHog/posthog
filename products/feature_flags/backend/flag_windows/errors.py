"""The errors after a flag edit: in each time bucket, how many people hit an error, whether or not the error event
carries the flag. An error of an issue first seen after the edit is stronger evidence than an older error that became
more frequent.

The errors of the exposed and of the unexposed people are in the counts of `flag_windows/exposure.py` and
`flag_windows/last_values.py`. One query reads the `$exception` events. `flag_windows/query.py` holds the counting rules.
"""

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timedelta

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select

from posthog.dataclasses import frozen
from posthog.models import Team

from products.feature_flags.backend.flag_windows.query import BucketCounts, FlagRead, WatchedEdit, counts_by_bucket


@frozen
class ErrorCounts:
    # The people (or groups) with an error, whether or not the error event carries the flag.
    with_errors: int
    # The people (or groups) with an error of an issue first seen after the edit.
    with_new_errors: int
    # The people (or groups) whose error event carries each variant that the flag serves. Empty for a boolean flag.
    by_variant: Mapping[str, int]


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
        # No count is limited to the watched conditions, so the query doesn't need the flag calls that find them.
        [replace(edit, conditions=()) for edit in edits],
        _counts,
        start,
        end,
        bucket,
        query_type="flag_errors_by_bucket",
        event="$exception",
        joins=[_issue_first_seen_join()],
    )
    return {edit.id: _buckets(edit, counts[edit.id].buckets) for edit in edits}


def _buckets(edit: WatchedEdit, rows: Sequence[BucketCounts]) -> list[ErrorBucket]:
    buckets = [
        ErrorBucket(start=row.start, in_bucket=_errors(edit, row.in_bucket), since_edit=_errors(edit, row.since_edit))
        for row in rows
    ]
    return [bucket for bucket in buckets if bucket.in_bucket.with_errors]


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


def _counts(edit: WatchedEdit, read: FlagRead) -> list[ast.Expr]:
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
        *[read.has_variant(variant) for variant in edit.variants],
    ]


def _errors(edit: WatchedEdit, values: tuple[int, ...]) -> ErrorCounts:
    with_errors, with_new_errors, *by_variant = values
    return ErrorCounts(
        with_errors=with_errors,
        with_new_errors=with_new_errors,
        by_variant=dict(zip(edit.variants, by_variant, strict=True)),
    )
