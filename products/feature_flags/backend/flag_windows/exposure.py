"""The exposure curve of a flag edit: in each time bucket, how many people carry the flag, and how many of them get the
value that the edit started serving.

Flag rollback suggestions read the curve as the clock of an observation window. The new value reaches people only when
their app reloads flags, so the share of people with the new value rises over time and then stabilizes. The window
compares errors against this curve, not against the edit time.

- Only people whose events carry `$feature/<key>` count, because the value of the others is unknown. An edit that
  enables the flag counts the people whose events carry `$active_feature_flags` instead: a disabled flag is not in the
  `/flags` response, so no event carried `$feature/<key>` before the edit. The new events schema keeps the active flags
  as a map, which is empty both when an app loaded no active flag and when it loaded no flags at all, so there the
  count holds only the people with at least one active flag.
- A group flag counts groups, because it assigns whole groups at once. One large customer would otherwise meet the
  minimum volume by itself.
- `$feature/<key>` holds the variant key on a multivariate flag, so the exposed people there are the people with any
  value other than false.

One query per team reads every watched edit, because `$feature/<key>` is on every event: a query per edit would read
the same events again.
"""

import math
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS, HogQLGlobalSettings
from posthog.hogql.parser import parse_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.models import Team

QUERY_TIMEOUT_SECONDS = 30
QUERY_MAX_THREADS = 2


@frozen
class WatchedEdit:
    """A flag edit that raised exposure, as the exposure query reads it."""

    # Names the edit in the result, for example the observation window or the activity log entry.
    id: str
    flag_key: str
    # The group type that the flag aggregates by, or None for a person flag.
    group_type_index: int | None
    # The variants that the flag serves after the edit (`ExposureChange.served_variants`). Empty for a boolean flag.
    variants: tuple[str, ...]
    # The edit enabled the flag, so no event carried the flag before it.
    enables: bool


@frozen
class ExposureBucket:
    start: datetime
    # The people (or groups) whose events carry the flag, or that loaded flags when the edit enables the flag.
    with_flag: int
    # The people (or groups) with a value other than false.
    exposed: int
    # The people (or groups) with each variant that the flag serves. Empty for a boolean flag.
    by_variant: Mapping[str, int]


def exposure_by_bucket(
    team: Team, edits: Sequence[WatchedEdit], start: datetime, end: datetime, bucket: timedelta
) -> dict[str, list[ExposureBucket]]:
    """The exposure of each edit in each bucket of `[start, end)`, by edit id, oldest bucket first. A bucket in which
    nobody carried the flag has no entry. Each count holds a person once per bucket, so a person whose value changed
    inside a bucket counts under both values."""
    seconds = bucket.total_seconds()
    if seconds < 1 or seconds != int(seconds):
        raise ValueError(f"A bucket must be a whole number of seconds, got {bucket}")
    if end <= start:
        raise ValueError(f"The range must end after it starts, got {start} to {end}")
    buckets = math.ceil((end - start) / bucket)
    # HogQL caps the rows of a query, and a capped result would drop the newest buckets without an error.
    if buckets > MAX_SELECT_RETURNED_ROWS:
        raise ValueError(f"The range holds {buckets} buckets, more than {MAX_SELECT_RETURNED_ROWS}")
    if not edits:
        return {}
    # Buckets start at `start`, not at a multiple of the bucket since the epoch, so a range that starts at an edit
    # time does not begin with a partial bucket.
    bucket_start = parse_expr(
        "toStartOfInterval(timestamp, toIntervalSecond({seconds}), {start})",
        placeholders={"seconds": ast.Constant(value=int(seconds)), "start": ast.Constant(value=start)},
    )
    columns = [_edit_columns(index, edit) for index, edit in enumerate(edits)]
    query = ast.SelectQuery(
        select=[
            ast.Alias(alias="bucket", expr=bucket_start),
            *[column for edit_columns in columns for column in edit_columns],
        ],
        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        where=parse_expr(
            "timestamp >= {start} AND timestamp < {end}",
            placeholders={"start": ast.Constant(value=start), "end": ast.Constant(value=end)},
        ),
        group_by=[ast.Field(chain=["bucket"])],
        order_by=[ast.OrderExpr(expr=ast.Field(chain=["bucket"]), order="ASC")],
        # One row per bucket. HogQL adds LIMIT 100 to a query without one.
        limit=ast.Constant(value=buckets),
    )
    with tags_context(
        product=Product.FEATURE_FLAGS, feature=Feature.HEALTH_CHECK, team_id=team.pk, org_id=team.organization_id
    ):
        response = execute_hogql_query(
            query,
            team=team,
            workload=Workload.OFFLINE,
            # The join that applies person merges costs seconds on large teams and moves the counts by a tiny
            # fraction, because a merge moves few people.
            modifiers=HogQLQueryModifiers(
                personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS
            ),
            # A query that breaks on timeout returns partial counts, which would read as a lower exposure.
            settings=HogQLGlobalSettings(
                max_execution_time=QUERY_TIMEOUT_SECONDS,
                max_threads=QUERY_MAX_THREADS,
                timeout_overflow_mode="throw",
            ),
        )

    result: dict[str, list[ExposureBucket]] = {edit.id: [] for edit in edits}
    for row in response.results or []:
        values = iter(row[1:])
        for edit in edits:
            with_flag, exposed = int(next(values)), int(next(values))
            by_variant = {variant: int(next(values)) for variant in edit.variants}
            if with_flag:
                result[edit.id].append(
                    ExposureBucket(start=row[0], with_flag=with_flag, exposed=exposed, by_variant=by_variant)
                )
    return result


def _edit_columns(index: int, edit: WatchedEdit) -> list[ast.Expr]:
    """The edit's counts: with the flag, exposed, then one per variant in the order of `edit.variants`."""
    actor = ast.Field(chain=[f"$group_{edit.group_type_index}" if edit.group_type_index is not None else "person_id"])
    # The key is a field name, not a value, so it goes in as an AST field: a flag key can hold any character.
    value = ast.Call(name="toString", args=[ast.Field(chain=["properties", f"$feature/{edit.flag_key}"])])
    has_actor = (
        parse_expr("notEmpty({actor})", placeholders={"actor": actor})
        if edit.group_type_index is not None
        else ast.Constant(value=True)
    )
    if edit.enables:
        # JSONHas is the presence check that both events schemas translate. See the module docstring for the difference.
        with_flag = parse_expr("JSONHas(properties, '$active_feature_flags')")
    else:
        with_flag = parse_expr("isNotNull({value})", placeholders={"value": value})
    # A variant may be named "false", and the plain property read gives it the same 'false' as a flag that evaluated to
    # false. The JSON functions keep the type on both events schemas, so a variant is a JSON string.
    key = ast.Constant(value=f"$feature/{edit.flag_key}")
    variant_value = parse_expr(
        "if(JSONType(properties, {key}) = 'String', JSONExtractString(properties, {key}), '')",
        placeholders={"key": key},
    )
    if edit.variants:
        exposed = parse_expr("{variant_value} != ''", placeholders={"variant_value": variant_value})
    else:
        exposed = parse_expr("{value} = 'true'", placeholders={"value": value})

    def count(alias: str, condition: ast.Expr) -> ast.Expr:
        return ast.Alias(
            alias=f"e{index}_{alias}",
            expr=parse_expr(
                "uniqIf({actor}, {has_actor} AND {condition})",
                placeholders={"actor": actor, "has_actor": has_actor, "condition": condition},
            ),
        )

    return [
        count("with_flag", with_flag),
        count("exposed", exposed),
        *[
            count(
                f"variant_{position}",
                parse_expr(
                    "{variant_value} = {variant}",
                    placeholders={"variant_value": variant_value, "variant": ast.Constant(value=variant)},
                ),
            )
            for position, variant in enumerate(edit.variants)
        ],
    ]
