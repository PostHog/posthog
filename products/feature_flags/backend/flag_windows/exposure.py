"""The exposure curve of a flag edit: in each time bucket, how many people carry the flag, and how many of them get the
value that the edit started serving.

Flag rollback suggestions read the curve as the clock of an observation window. The new value reaches people only when
their app reloads flags, so the share of people with the new value rises over time and then stabilizes. The window
compares errors against this curve, not against the edit time.

- Only people whose events carry `$feature/<key>` count, because the value of the others is unknown. An edit that
  enables the flag also counts the people whose events carry `$active_feature_flags`: a disabled flag is not in the
  `/flags` response, so no event carried `$feature/<key>` before the edit. The new events schema drops
  `$active_feature_flags` and checks for any `$feature/*` key instead, false values included, so there an app that
  loaded no flags at all does not count. The legacy events table counts it when the app sent an empty
  `$active_feature_flags`.
- A group flag counts groups, because it assigns whole groups at once. One large customer would otherwise meet the
  minimum volume by itself.
- `$feature/<key>` holds the variant key on a multivariate flag, so the exposed people there are the people with any
  value other than false.
- Each bucket also holds the counts since the edit. Per-bucket counts can't be added up, because a person can be in many
  buckets. The query keeps a `uniqState` per bucket and merges the states of the buckets so far, in the same scan.
- `uniq` is exact up to about 65,536 people per count and estimates above that. Each count is a separate estimate, so
  on a large flag `exposed` can be a little above `with_flag`. `uniqExact` would keep every person id of every count of
  every bucket in memory, in a query that reads every event of the team.

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

# The health check query settings (posthog/temporal/health_checks/query.py). Nobody waits for the result, so the scan of
# every event of a team leaves CPU to the queries people wait for.
QUERY_TIMEOUT_SECONDS = 30
QUERY_MAX_THREADS = 2

IN_BUCKET = "_finalizeAggregation({state})"
SINCE_EDIT = "uniqMerge({state}) OVER (ORDER BY bucket ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)"


@frozen
class WatchedEdit:
    """A flag edit that raised exposure, as the exposure query reads it."""

    # Names the edit in the result, for example the observation window or the activity log entry.
    id: str
    flag_key: str
    # Counts start here, because events before the edit carry the old value.
    edited_at: datetime
    # The group type that the flag aggregates by, or None for a person flag.
    group_type_index: int | None
    # The variants that the flag serves after the edit (`ExposureChange.served_variants`). Empty for a boolean flag.
    variants: tuple[str, ...]
    # The edit enabled the flag, so no event carried the flag before it.
    enables: bool


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
    seconds = bucket.total_seconds()
    if seconds < 1 or seconds != int(seconds):
        raise ValueError(f"A bucket must be a whole number of seconds, got {bucket}")
    if end <= start:
        raise ValueError(f"The range must end after it starts, got {start} to {end}")
    buckets = math.ceil((end - start) / bucket)
    # HogQL caps the rows of a query, and a capped result would drop the newest buckets without an error.
    if buckets > MAX_SELECT_RETURNED_ROWS:
        raise ValueError(f"The range holds {buckets} buckets, more than {MAX_SELECT_RETURNED_ROWS}")
    if len({edit.id for edit in edits}) != len(edits):
        raise ValueError("Each watched edit needs its own id")
    if not edits:
        return {}
    # Buckets start at `start`, not at a multiple of the bucket since the epoch, so a range that starts at an edit
    # time does not begin with a partial bucket.
    bucket_start = parse_expr(
        "toStartOfInterval(timestamp, toIntervalSecond({seconds}), {start})",
        placeholders={"seconds": ast.Constant(value=int(seconds)), "start": ast.Constant(value=start)},
    )
    states_by_edit = [_edit_states(index, edit) for index, edit in enumerate(edits)]
    states = [state for edit_states in states_by_edit for state in edit_states]
    per_bucket = ast.SelectQuery(
        select=[ast.Alias(alias="bucket", expr=bucket_start), *states],
        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        where=parse_expr(
            "timestamp >= {start} AND timestamp < {end}",
            placeholders={"start": ast.Constant(value=start), "end": ast.Constant(value=end)},
        ),
        group_by=[ast.Field(chain=["bucket"])],
    )
    query = ast.SelectQuery(
        select=[
            ast.Field(chain=["bucket"]),
            *[
                parse_expr(template, placeholders={"state": ast.Field(chain=[state.alias])})
                for state in states
                for template in (IN_BUCKET, SINCE_EDIT)
            ],
        ],
        select_from=ast.JoinExpr(table=per_bucket),
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
        for edit, edit_states in zip(edits, states_by_edit):
            # Each count gives the bucket's own value, then the value since the edit.
            pairs = [(int(next(values)), int(next(values))) for _ in edit_states]
            in_bucket = _counts(edit, [pair[0] for pair in pairs])
            since_edit = _counts(edit, [pair[1] for pair in pairs])
            if in_bucket.with_flag:
                result[edit.id].append(ExposureBucket(start=row[0], in_bucket=in_bucket, since_edit=since_edit))
    return result


def _counts(edit: WatchedEdit, values: list[int]) -> ExposureCounts:
    with_flag, exposed, *by_variant = values
    return ExposureCounts(with_flag=with_flag, exposed=exposed, by_variant=dict(zip(edit.variants, by_variant)))


def _edit_states(index: int, edit: WatchedEdit) -> list[ast.Alias]:
    """The `uniqState` of each of the edit's counts: with the flag, exposed, then one per variant in the order of
    `edit.variants`."""
    if edit.group_type_index is None:
        actor = ast.Field(chain=["person_id"])
        has_actor: ast.Expr = ast.Constant(value=True)
    else:
        actor = ast.Field(chain=[f"$group_{edit.group_type_index}"])
        has_actor = parse_expr("notEmpty({actor})", placeholders={"actor": actor})
    # A flag key can hold any character, so it goes in as an AST node, never as HogQL text.
    property_name = f"$feature/{edit.flag_key}"
    flag_value = ast.Call(name="toString", args=[ast.Field(chain=["properties", property_name])])
    carries_flag = parse_expr("isNotNull({flag_value})", placeholders={"flag_value": flag_value})
    if edit.enables:
        # JSONHas is the presence check that both events schemas translate. Server SDKs send `$feature/<key>` without
        # `$active_feature_flags`, so the people who carry the flag count too.
        with_flag = parse_expr(
            "JSONHas(properties, '$active_feature_flags') OR {carries_flag}",
            placeholders={"carries_flag": carries_flag},
        )
    else:
        with_flag = carries_flag
    # A split under 100% serves true to a person who matches the condition but draws no variant, so on a multivariate
    # flag every value but false counts as exposed.
    variant_key: ast.Expr = flag_value
    if {"true", "false"} & set(edit.variants):
        # The plain property read gives a variant named "true" or "false" the same value as a boolean flag. The JSON
        # functions keep the type on both events schemas, so a variant is a JSON string. On the legacy events table
        # they parse the whole `properties` column, so only these edits pay for them.
        variant_key = parse_expr(
            "if(JSONType(properties, {name}) = 'String', JSONExtractString(properties, {name}), '')",
            placeholders={"name": ast.Constant(value=property_name)},
        )
        exposed = parse_expr(
            "{variant_key} != '' OR {flag_value} = 'true'",
            placeholders={"variant_key": variant_key, "flag_value": flag_value},
        )
    elif edit.variants:
        # isNotNull, because HogQL reads a missing flag as not equal to 'false'.
        exposed = parse_expr(
            "{carries_flag} AND {flag_value} != 'false'",
            placeholders={"carries_flag": carries_flag, "flag_value": flag_value},
        )
    else:
        exposed = parse_expr("{flag_value} = 'true'", placeholders={"flag_value": flag_value})

    def count(alias: str, condition: ast.Expr) -> ast.Alias:
        return ast.Alias(
            alias=f"e{index}_{alias}",
            expr=parse_expr(
                "uniqState(if({has_actor} AND timestamp >= {edited_at} AND {condition}, {actor}, NULL))",
                placeholders={
                    "actor": actor,
                    "has_actor": has_actor,
                    "edited_at": ast.Constant(value=edit.edited_at),
                    "condition": condition,
                },
            ),
        )

    return [
        count("with_flag", with_flag),
        count("exposed", exposed),
        *[
            count(
                f"variant_{position}",
                parse_expr(
                    "{variant_key} = {variant}",
                    placeholders={"variant_key": variant_key, "variant": ast.Constant(value=variant)},
                ),
            )
            for position, variant in enumerate(edit.variants)
        ],
    ]
