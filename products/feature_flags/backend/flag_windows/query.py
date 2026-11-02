"""What the observation window queries share: the watched edit, how an event reads its flag, and the query that counts
people per bucket and since the edit.

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
  on a large flag a count of a subset can come out a little above the count of the whole, for example `exposed` above
  `with_flag`. `uniqExact` would keep every person id of every count of every bucket in memory, in a query that reads
  every event of the team.
- An edit moves the people of some conditions only, and the people that match no condition get false before and after
  it. The counts in the watched conditions leave the others out, in two ways that the backtest compares:
  - By `$feature_flag_reason`, which the SDKs put on `$feature_flag_called` from the `/flags` response. The reason names
    the condition that matched, but not the condition whose rollout left the person out, so on a flag with many
    conditions the people outside the rollout of any condition count. A server SDK that evaluates the flag locally
    sends no condition, so its people don't count. The SDKs send `$feature_flag_called` once per value of the flag, so a
    person whose value the edit kept sends none after it and doesn't count either. One scan of `$feature_flag_called`
    per kind of actor finds the reasons of every edit, and joins them to the events by the actor.
  - By the properties of each event against the property filters of the conditions. Person properties come from the
    event, so an event without person processing does not match a person filter. A filter on another flag always
    matches, because the query can't evaluate a flag. A relative date such as "-7d" counts back from the range end,
    so a rerun of the same range gives the same counts. A condition on a cohort that the query can't read, such as a
    deleted static cohort, has no expression, so its edit gets no counts by properties.

One query per team reads every watched edit: a query per edit would read the same events again.
"""

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

import structlog

from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS, HogQLGlobalSettings
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.models import Team

from products.feature_flags.backend.user_blast_radius import replace_proxy_properties

logger = structlog.get_logger(__name__)

# The health check query settings (posthog/temporal/health_checks/query.py). Nobody waits for the result, so the scan of
# every event of a team leaves CPU to the queries people wait for.
QUERY_TIMEOUT_SECONDS = 30
QUERY_MAX_THREADS = 2

IN_BUCKET = "_finalizeAggregation({state})"
SINCE_EDIT = "uniqMerge({state}) OVER (ORDER BY bucket ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)"


class ConditionMatch(StrEnum):
    REASON = "reason"
    PROPERTIES = "properties"


@frozen
class WatchedCondition:
    # The position of the condition in the flag after the edit. `$feature_flag_reason` counts from 1.
    position: int
    # The property filters of the condition, as `filters.groups` stores them.
    properties: tuple[Mapping[str, Any], ...]


@frozen
class WatchedEdit:
    """A flag edit that raised exposure, as the window queries read it."""

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
    # The conditions whose people the edit can move. Without them, the counts in the watched conditions are left out.
    conditions: tuple[WatchedCondition, ...] = ()


@frozen
class FlagRead:
    """How an event reads the flag of a watched edit, as HogQL expressions."""

    # The person, or the group for a group flag.
    actor: ast.Expr
    # A group flag needs the group on the event.
    has_actor: ast.Expr
    # The event carries the flag, or loaded flags when the edit enables the flag.
    with_flag: ast.Expr
    # The event carries a value other than false.
    exposed: ast.Expr
    # The variant key on the event. Compare it with a served variant.
    variant_key: ast.Expr
    # The person (or group) is in a watched condition, by each way of matching. Empty without watched conditions.
    in_condition: Mapping[ConditionMatch, ast.Expr] = field(default_factory=dict)

    def has_variant(self, variant: str) -> ast.Expr:
        return parse_expr(
            "{variant_key} = {variant}",
            placeholders={"variant_key": self.variant_key, "variant": ast.Constant(value=variant)},
        )


@frozen
class BucketCounts:
    start: datetime
    # One value per condition, in the order the caller gave them.
    in_bucket: tuple[int, ...]
    # From the edit, or from the range start when it is later, to the end of this bucket. Each person counts once.
    since_edit: tuple[int, ...]


@frozen
class EditCounts:
    # The ways of matching that the edit has counts for, in the order of `ConditionMatch`.
    in_condition: tuple[ConditionMatch, ...]
    buckets: tuple[BucketCounts, ...]


@frozen
class _Actor:
    # The person, or the group that a group flag aggregates by.
    expr: ast.Expr
    # The event has the actor. A group flag needs the group on the event.
    present: ast.Expr


def _actor(group_type_index: int | None) -> _Actor:
    if group_type_index is None:
        return _Actor(expr=ast.Field(chain=["person_id"]), present=ast.Constant(value=True))
    actor = ast.Field(chain=[f"$group_{group_type_index}"])
    return _Actor(expr=actor, present=parse_expr("notEmpty({actor})", placeholders={"actor": actor}))


def read_flag(team: Team, edit: WatchedEdit, by_reason: ast.Expr | None, end: datetime) -> FlagRead:
    """`by_reason` is the column of `_reason_joins` for the edit, or None without watched conditions."""
    actor = _actor(edit.group_type_index)
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
    return FlagRead(
        actor=actor.expr,
        has_actor=actor.present,
        with_flag=with_flag,
        exposed=exposed,
        variant_key=variant_key,
        in_condition=_in_condition(team, edit, by_reason, end),
    )


def _in_condition(
    team: Team, edit: WatchedEdit, by_reason: ast.Expr | None, end: datetime
) -> dict[ConditionMatch, ast.Expr]:
    if by_reason is None:
        return {}
    in_condition = {ConditionMatch.REASON: parse_expr("{by_reason} = 1", placeholders={"by_reason": by_reason})}
    try:
        in_condition[ConditionMatch.PROPERTIES] = ast.Or(
            exprs=[
                property_to_expr(
                    replace_proxy_properties(team, {"properties": list(condition.properties)}, now=end),
                    team,
                    scope="event",
                )
                for condition in edit.conditions
            ]
        )
    except QueryError:
        # A condition on a static or precalculated cohort deleted after the edit, or on a cohort id that no longer
        # exists, has no expression. The edit gets no counts by properties, so that the query still counts the other
        # edits of the team.
        logger.warning(
            "flag_window_condition_without_expression", team_id=team.pk, flag_key=edit.flag_key, exc_info=True
        )
    return in_condition


def _reason_joins(edits: Sequence[WatchedEdit], end: datetime) -> tuple[list[ast.JoinExpr], dict[str, ast.Expr]]:
    """The joins that tell, for each edit with watched conditions, whether the actor of an event got a watched
    condition after the edit, and the column of each edit. One join per kind of actor, so the query reads
    `$feature_flag_called` once for all the edits of that kind."""
    edits_by_actor: dict[int | None, list[tuple[int, WatchedEdit]]] = {}
    for index, edit in enumerate(edits):
        if edit.conditions:
            edits_by_actor.setdefault(edit.group_type_index, []).append((index, edit))
    joins: list[ast.JoinExpr] = []
    columns: dict[str, ast.Expr] = {}
    for group_type_index, watched in edits_by_actor.items():
        alias = "flag_reasons" if group_type_index is None else f"flag_reasons_{group_type_index}"
        actor = _actor(group_type_index)
        # The top-level filters keep the shape that the flag_evaluations swap reads, so this scan also finds the
        # flag calls of a team whose calls ingestion writes only to `flag_evaluations`.
        subquery = ast.SelectQuery(
            select=[
                ast.Alias(alias="actor", expr=actor.expr),
                *[ast.Alias(alias=f"e{index}", expr=_got_watched_condition(edit)) for index, edit in watched],
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=parse_expr(
                """
                event = '$feature_flag_called'
                    AND timestamp >= {since}
                    AND timestamp < {end}
                    AND properties.$feature_flag IN {flag_keys}
                    AND {has_actor}
                """,
                placeholders={
                    "since": ast.Constant(value=min(edit.edited_at for _, edit in watched)),
                    "end": ast.Constant(value=end),
                    "flag_keys": ast.Tuple(
                        exprs=[ast.Constant(value=key) for key in sorted({edit.flag_key for _, edit in watched})]
                    ),
                    "has_actor": actor.present,
                },
            ),
            group_by=[ast.Field(chain=["actor"])],
        )
        joins.append(
            ast.JoinExpr(
                join_type="LEFT JOIN",
                table=subquery,
                alias=alias,
                constraint=ast.JoinConstraint(
                    expr=parse_expr(
                        "{reasons_actor} = {actor}",
                        placeholders={"reasons_actor": ast.Field(chain=[alias, "actor"]), "actor": actor.expr},
                    ),
                    constraint_type="ON",
                ),
            )
        )
        for index, edit in watched:
            columns[edit.id] = ast.Field(chain=[alias, f"e{index}"])
    return joins, columns


def _got_watched_condition(edit: WatchedEdit) -> ast.Expr:
    # The descriptions of `FeatureFlagMatchReason` in rust/feature-flags/src/api/types.rs.
    reasons = [f"Matched condition set {condition.position + 1}" for condition in edit.conditions]
    reasons.append("Out of rollout bound")
    return parse_expr(
        """
        max(
            properties.$feature_flag = {flag_key}
                AND timestamp >= {edited_at}
                AND properties.$feature_flag_reason IN {reasons}
        )
        """,
        placeholders={
            "flag_key": ast.Constant(value=edit.flag_key),
            "edited_at": ast.Constant(value=edit.edited_at),
            "reasons": ast.Tuple(exprs=[ast.Constant(value=reason) for reason in reasons]),
        },
    )


def in_condition_columns(read: FlagRead, counts: Sequence[ast.Expr]) -> list[ast.Expr]:
    """Each of `counts`, only for the people in the watched conditions, for each way of matching."""
    return [
        ast.And(exprs=[count, read.in_condition[match]])
        for match in ConditionMatch
        if match in read.in_condition
        for count in counts
    ]


def read_in_condition(
    matches: Sequence[ConditionMatch], values: Sequence[int], per_match: int
) -> dict[ConditionMatch, tuple[int, ...]]:
    """The values of the columns from `in_condition_columns`, `per_match` counts for each way of matching."""
    groups = [tuple(values[start : start + per_match]) for start in range(0, len(values), per_match)]
    return dict(zip(matches, groups, strict=True))


def counts_by_bucket(
    team: Team,
    edits: Sequence[WatchedEdit],
    conditions: Callable[[WatchedEdit, FlagRead], Sequence[ast.Expr]],
    start: datetime,
    end: datetime,
    bucket: timedelta,
    query_type: str,
    event: str | None = None,
    join: ast.JoinExpr | None = None,
) -> dict[str, EditCounts]:
    """For each edit, the people (or groups) that meet each of its conditions after the edit, in each bucket of
    `[start, end)` that has events, oldest bucket first. `query_type` names the query in the query log. `event` limits
    the scan to one event name. `join` joins a table to the events, so that the conditions of every edit can read it."""
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

    reason_joins, reason_columns = _reason_joins(edits, end)
    reads = [read_flag(team, edit, reason_columns.get(edit.id), end) for edit in edits]
    states_by_edit = [
        _states(index, edit, read, conditions(edit, read)) for index, (edit, read) in enumerate(zip(edits, reads))
    ]
    states = [state for edit_states in states_by_edit for state in edit_states]
    # Buckets start at `start`, not at a multiple of the bucket since the epoch, so a range that starts at an edit
    # time does not begin with a partial bucket.
    bucket_start = parse_expr(
        "toStartOfInterval(timestamp, toIntervalSecond({seconds}), {start})",
        placeholders={"seconds": ast.Constant(value=int(seconds)), "start": ast.Constant(value=start)},
    )
    where = parse_expr(
        "timestamp >= {start} AND timestamp < {end}",
        placeholders={"start": ast.Constant(value=start), "end": ast.Constant(value=end)},
    )
    if event is not None:
        where = ast.And(exprs=[where, parse_expr("event = {event}", placeholders={"event": ast.Constant(value=event)})])
    per_bucket = ast.SelectQuery(
        select=[ast.Alias(alias="bucket", expr=bucket_start), *states],
        select_from=ast.JoinExpr(
            table=ast.Field(chain=["events"]), next_join=_chain([*([join] if join else []), *reason_joins])
        ),
        where=where,
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
            query_type=query_type,
            workload=Workload.OFFLINE,
            # The join that applies person merges costs seconds on large teams and moves the counts by a tiny
            # fraction, because a merge moves few people.
            modifiers=HogQLQueryModifiers(
                personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS
            ),
            # A query that breaks on timeout returns partial counts, which would read as lower counts.
            settings=HogQLGlobalSettings(
                max_execution_time=QUERY_TIMEOUT_SECONDS,
                max_threads=QUERY_MAX_THREADS,
                timeout_overflow_mode="throw",
                # The reason joins group the flag calls by actor. On a large team the aggregation goes to disk instead
                # of failing the counts of every edit. The value follows `person_sampling.py`.
                max_bytes_before_external_group_by=4 * 1024**3,
            ),
        )

    rows_by_edit: dict[str, list[BucketCounts]] = {edit.id: [] for edit in edits}
    for row in response.results or []:
        values = iter(row[1:])
        for edit, edit_states in zip(edits, states_by_edit):
            # Each state gives the bucket's own value, then the value since the edit.
            pairs = [(int(next(values)), int(next(values))) for _ in edit_states]
            rows_by_edit[edit.id].append(
                BucketCounts(
                    start=row[0],
                    in_bucket=tuple(pair[0] for pair in pairs),
                    since_edit=tuple(pair[1] for pair in pairs),
                )
            )
    return {
        edit.id: EditCounts(
            in_condition=tuple(match for match in ConditionMatch if match in read.in_condition),
            buckets=tuple(rows_by_edit[edit.id]),
        )
        for edit, read in zip(edits, reads)
    }


def _chain(joins: Sequence[ast.JoinExpr]) -> ast.JoinExpr | None:
    head: ast.JoinExpr | None = None
    for join in reversed(joins):
        head = replace(join, next_join=head)
    return head


def _states(index: int, edit: WatchedEdit, read: FlagRead, conditions: Sequence[ast.Expr]) -> list[ast.Alias]:
    return [
        ast.Alias(
            alias=f"e{index}_{position}",
            expr=parse_expr(
                "uniqState(if({has_actor} AND timestamp >= {edited_at} AND {condition}, {actor}, NULL))",
                placeholders={
                    "actor": read.actor,
                    "has_actor": read.has_actor,
                    "edited_at": ast.Constant(value=edit.edited_at),
                    "condition": condition,
                },
            ),
        )
        for position, condition in enumerate(conditions)
    ]
