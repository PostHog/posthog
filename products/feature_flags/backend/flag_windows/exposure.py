"""The exposure curve of a flag edit: in each time bucket, how many people carry the flag, and how many of them get the
value that the edit started serving.

Flag rollback suggestions read the curve as the clock of an observation window. The new value reaches people only when
their app reloads flags, so the share of people with the new value rises over time and then stabilizes. The window
compares errors against this curve, not against the edit time.

The query reads every event, because `$feature/<key>` is on every event. `flag_windows/query.py` holds the counting
rules.
"""

from collections.abc import Mapping, Sequence
from dataclasses import field
from datetime import datetime, timedelta

from posthog.hogql import ast

from posthog.dataclasses import frozen
from posthog.models import Team

from products.feature_flags.backend.flag_windows.query import (
    ConditionMatch,
    EditCounts,
    FlagRead,
    WatchedEdit,
    counts_by_bucket,
    in_condition_columns,
    read_in_condition,
)


@frozen
class ConditionExposure:
    with_flag: int
    exposed: int


@frozen
class ExposureCounts:
    # The people (or groups) whose events carry the flag, or that loaded flags when the edit enables the flag.
    with_flag: int
    # The people (or groups) with a value other than false.
    exposed: int
    # The people (or groups) with each variant that the flag serves. Empty for a boolean flag.
    by_variant: Mapping[str, int]
    # The same counts, only for the people (or groups) in the watched conditions. Empty without watched conditions.
    in_condition: Mapping[ConditionMatch, ConditionExposure] = field(default_factory=dict)


@frozen
class ExposureBucket:
    start: datetime
    in_bucket: ExposureCounts
    # From the edit, or from the range start when it is later, to the end of this bucket. Each person counts once.
    since_edit: ExposureCounts


def exposure_by_bucket(
    team: Team, edits: Sequence[WatchedEdit], start: datetime, end: datetime, bucket: timedelta
) -> dict[str, list[ExposureBucket]]:
    """The exposure of each edit in each bucket of `[start, end)`, by edit id, oldest bucket first. A bucket in which
    nobody carried the flag after the edit has no entry. A person whose value changed counts under both values."""
    counts = counts_by_bucket(team, edits, _counts, start, end, bucket, query_type="flag_exposure_by_bucket")
    return {edit.id: _buckets(edit, counts[edit.id]) for edit in edits}


def _buckets(edit: WatchedEdit, counts: EditCounts) -> list[ExposureBucket]:
    return [
        ExposureBucket(
            start=row.start,
            in_bucket=_exposure(edit, counts.matches, row.in_bucket),
            since_edit=_exposure(edit, counts.matches, row.since_edit),
        )
        for row in counts.buckets
        if _exposure(edit, counts.matches, row.in_bucket).with_flag
    ]


def _counts(edit: WatchedEdit, read: FlagRead) -> list[ast.Expr]:
    return [
        read.with_flag,
        read.exposed,
        *[read.has_variant(variant) for variant in edit.variants],
        *in_condition_columns(read, [read.with_flag, read.exposed]),
    ]


def _exposure(edit: WatchedEdit, matches: Sequence[ConditionMatch], values: tuple[int, ...]) -> ExposureCounts:
    with_flag, exposed, *rest = values
    by_variant, in_condition_values = rest[: len(edit.variants)], rest[len(edit.variants) :]
    return ExposureCounts(
        with_flag=with_flag,
        exposed=exposed,
        by_variant=dict(zip(edit.variants, by_variant, strict=True)),
        in_condition={
            match: ConditionExposure(with_flag=counts[0], exposed=counts[1])
            for match, counts in read_in_condition(matches, in_condition_values).items()
        },
    )
