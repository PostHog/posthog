"""The exposure curve of a flag edit: in each time bucket, how many people carry the flag, and how many of them get the
value that the edit started serving.

Flag rollback suggestions read the curve as the clock of an observation window. The new value reaches people only when
their app reloads flags, so the share of people with the new value rises over time and then stabilizes. The window
compares errors against this curve, not against the edit time.

The query reads every event, because `$feature/<key>` is on every event. `flag_windows/query.py` holds the counting
rules.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

from posthog.hogql import ast

from posthog.dataclasses import frozen
from posthog.models import Team

from products.feature_flags.backend.flag_windows.query import FlagRead, WatchedEdit, counts_by_bucket


@frozen
class ExposureCounts:
    # The people (or groups) whose events carry the flag, or that loaded flags when the edit enables the flag.
    with_flag: int
    # The people (or groups) with a value other than false.
    exposed: int
    # The people (or groups) with each variant that the flag serves. Empty for a boolean flag.
    by_variant: Mapping[str, int]


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
    counts = counts_by_bucket(team, edits, _conditions, start, end, bucket, query_type="flag_exposure_by_bucket")
    return {
        edit.id: [
            ExposureBucket(
                start=row.start,
                in_bucket=_exposure(edit, row.in_bucket),
                since_edit=_exposure(edit, row.since_edit),
            )
            for row in counts[edit.id]
            if _exposure(edit, row.in_bucket).with_flag
        ]
        for edit in edits
    }


def _conditions(edit: WatchedEdit, read: FlagRead) -> list[ast.Expr]:
    return [read.with_flag, read.exposed, *[read.has_variant(variant) for variant in edit.variants]]


def _exposure(edit: WatchedEdit, values: tuple[int, ...]) -> ExposureCounts:
    with_flag, exposed, *by_variant = values
    return ExposureCounts(
        with_flag=with_flag, exposed=exposed, by_variant=dict(zip(edit.variants, by_variant, strict=True))
    )
