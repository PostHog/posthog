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
    matches, because the query can't evaluate a flag. A person who matches an earlier condition at 100% rollout gets
    the flag from it, so they don't count. A relative date such as "-7d" counts back from the range end, so a rerun
    of the same range gives the same counts. A condition that the query can't express, such as one on a deleted
    static cohort, leaves its edit without counts by properties. A value that ClickHouse rejects when the query runs,
    such as text compared with a number, leaves every edit without them.

One query per team reads every watched edit: a query per edit would read the same events again.
"""

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

import structlog
from rest_framework.exceptions import ValidationError

from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS, HogQLGlobalSettings
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.visitor import clone_expr

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.errors import InternalCHQueryError
from posthog.models import Team

from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.facade.flags import get_flag_evaluations_read_mode
from products.feature_flags.backend.person_sampling import SPILL_GROUP_BY_AFTER_BYTES
from products.feature_flags.backend.user_blast_radius import (
    replace_proxy_properties,
    unevaluable_filters_as_validation_errors,
)

logger = structlog.get_logger(__name__)

# The health check query settings (posthog/temporal/health_checks/query.py). Nobody waits for the result, so the scan of
# every event of a team leaves CPU to the queries people wait for.
QUERY_TIMEOUT_SECONDS = 30
QUERY_MAX_THREADS = 2

# ClickHouse rejects these when a property filter compares a value it can't cast or compile: CANNOT_PARSE_TEXT,
# CANNOT_PARSE_DATETIME, TYPE_MISMATCH, CANNOT_PARSE_NUMBER and CANNOT_COMPILE_REGEXP.
PROPERTY_VALUE_ERROR_CODES = frozenset({6, 41, 53, 72, 427})

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
    # The property filters of each earlier condition with a 100% rollout. A person who matches one of them gets the
    # flag from that condition, so the edit can't move them.
    earlier_at_full_rollout: tuple[tuple[Mapping[str, Any], ...], ...] = ()


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
    # The ways of matching that the edit has counts in the watched conditions for, in the order of their columns.
    matches: tuple[ConditionMatch, ...]
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


def read_flag(edit: WatchedEdit, in_condition: Mapping[ConditionMatch, ast.Expr]) -> FlagRead:
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
        in_condition=in_condition,
    )


def _in_condition(
    team: Team, edit: WatchedEdit, by_reason: ast.Expr | None, end: datetime, with_properties: bool
) -> dict[ConditionMatch, ast.Expr]:
    """`by_reason` is the column of `_reason_joins` for the edit, or None without watched conditions."""
    if by_reason is None:
        return {}
    in_condition = {ConditionMatch.REASON: parse_expr("{by_reason} = 1", placeholders={"by_reason": by_reason})}
    if not with_properties:
        return in_condition
    try:
        # The context turns every error of a filter that the query can't express into a ValidationError: a cohort that
        # was deleted after the edit or no longer exists, a cohort id that isn't a number, a filter type HogQL can't
        # convert. `property_to_expr` raises an AssertionError for a date filter whose value isn't a string.
        with unevaluable_filters_as_validation_errors():
            in_condition[ConditionMatch.PROPERTIES] = ast.Or(
                exprs=[_matches_condition(team, condition, end) for condition in edit.conditions]
            )
    except (ValidationError, AssertionError) as error:
        # The edit gets no counts by properties, so that the query still counts the other edits of the team. The
        # message can quote a filter value, such as an email pattern, so only its type goes to the logs.
        logger.warning(
            "flag_window_condition_without_expression",
            team_id=team.pk,
            flag_key=edit.flag_key,
            error_type=type(error).__name__,
        )
    return in_condition


def _matches_condition(team: Team, condition: WatchedCondition, end: datetime) -> ast.Expr:
    def matches(properties: Sequence[Mapping[str, Any]]) -> ast.Expr:
        return property_to_expr(
            replace_proxy_properties(team, {"properties": list(properties)}, now=end), team, scope="event"
        )

    # The query reads a filter on another flag as always true, so leaving out the people of an earlier condition with
    # one would leave out everyone.
    earlier = [
        properties
        for properties in condition.earlier_at_full_rollout
        if not any(prop.get("type") == "flag" for prop in properties)
    ]
    if not earlier:
        return matches(condition.properties)
    return ast.And(
        exprs=[
            matches(condition.properties),
            ast.Not(expr=ast.Or(exprs=[matches(properties) for properties in earlier])),
        ]
    )


@frozen
class _FlagCalls:
    """Where the reason joins read the flag calls of a team."""

    table: tuple[str, ...]
    # Limits the rows to flag calls.
    only_calls: ast.Expr
    flag_key: ast.Expr
    # The stored person id. The events read it too, because the query doesn't apply person merges.
    person_id: ast.Expr

    @classmethod
    def of(cls, team: Team) -> "_FlagCalls":
        # Ingestion writes no flag calls to events for some teams of an organization on FLAG_EVALUATIONS_ONLY. The
        # flag_evaluations swap can't move this scan, because there `person_id` applies person merges. So the scan
        # reads `flag_evaluations` by name. In the other modes events holds every flag call, and flag_evaluations
        # only those of the teams that ingestion writes there.
        if get_flag_evaluations_read_mode(team.organization_id) != FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY:
            return cls(
                table=("events",),
                only_calls=parse_expr("event = '$feature_flag_called'"),
                flag_key=parse_expr("properties.$feature_flag"),
                person_id=ast.Field(chain=["person_id"]),
            )
        return cls(
            table=("posthog", "flag_evaluations"),
            only_calls=ast.Constant(value=True),
            flag_key=ast.Field(chain=["flag_key"]),
            person_id=ast.Field(chain=["flag_evaluation_person_id"]),
        )


def _reason_joins(
    team: Team, edits: Sequence[WatchedEdit], end: datetime
) -> tuple[list[ast.JoinExpr], dict[str, ast.Expr]]:
    """The joins that tell, for each edit with watched conditions, whether the actor of an event sent a flag call
    with a watched reason after the edit, and the column of each edit. One join per kind of actor, so the query reads
    the flag calls once for all the edits of that kind."""
    edits_by_actor: dict[int | None, list[tuple[int, WatchedEdit]]] = {}
    for index, edit in enumerate(edits):
        if edit.conditions:
            edits_by_actor.setdefault(edit.group_type_index, []).append((index, edit))
    if not edits_by_actor:
        return [], {}
    calls = _FlagCalls.of(team)
    joins: list[ast.JoinExpr] = []
    columns: dict[str, ast.Expr] = {}
    for group_type_index, watched in edits_by_actor.items():
        alias = "flag_reasons" if group_type_index is None else f"flag_reasons_{group_type_index}"
        actor = _actor(group_type_index)
        reasons_by_edit = {edit.id: _watched_reasons(edit) for _, edit in watched}
        subquery = ast.SelectQuery(
            select=[
                ast.Alias(alias="actor", expr=calls.person_id if group_type_index is None else actor.expr),
                *[
                    ast.Alias(
                        alias=f"e{index}",
                        expr=_called_with_watched_reason(edit, calls, reasons_by_edit[edit.id]),
                    )
                    for index, edit in watched
                ],
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=list(calls.table))),
            # The reasons of every watched edit keep only the calls that some column can count, and the HAVING keeps
            # only the actors that one does. That holds the join's table to the actors in a watched condition.
            where=parse_expr(
                """
                {only_calls}
                    AND timestamp >= {since}
                    AND timestamp < {end}
                    AND {flag_key} IN {flag_keys}
                    AND properties.$feature_flag_reason IN {reasons}
                    AND {has_actor}
                """,
                placeholders={
                    "only_calls": calls.only_calls,
                    "since": ast.Constant(value=min(edit.edited_at for _, edit in watched)),
                    "end": ast.Constant(value=end),
                    "flag_key": calls.flag_key,
                    "flag_keys": _constants(edit.flag_key for _, edit in watched),
                    "reasons": _constants(reason for reasons in reasons_by_edit.values() for reason in reasons),
                    "has_actor": actor.present,
                },
            ),
            group_by=[ast.Field(chain=["actor"])],
            having=ast.Or(
                exprs=[
                    parse_expr("{column} = 1", placeholders={"column": ast.Field(chain=[f"e{index}"])})
                    for index, _ in watched
                ]
            ),
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


def _watched_reasons(edit: WatchedEdit) -> list[str]:
    # The descriptions of `FeatureFlagMatchReason` in rust/feature-flags/src/api/types.rs. "Out of rollout bound" names
    # no condition, so it can come from a watched condition or from any other.
    reasons = [f"Matched condition set {condition.position + 1}" for condition in edit.conditions]
    reasons.append("Out of rollout bound")
    return reasons


def _called_with_watched_reason(edit: WatchedEdit, calls: _FlagCalls, reasons: Sequence[str]) -> ast.Expr:
    return parse_expr(
        """
        max(
            {flag_key} = {edit_flag_key}
                AND timestamp >= {edited_at}
                AND properties.$feature_flag_reason IN {reasons}
        )
        """,
        placeholders={
            "flag_key": calls.flag_key,
            "edit_flag_key": ast.Constant(value=edit.flag_key),
            "edited_at": ast.Constant(value=edit.edited_at),
            "reasons": _constants(reasons),
        },
    )


def _constants(values: Iterable[str]) -> ast.Tuple:
    return ast.Tuple(exprs=[ast.Constant(value=value) for value in sorted(set(values))])


def in_condition_columns(read: FlagRead, counts: Sequence[ast.Expr]) -> list[ast.Expr]:
    """Each of `counts`, only for the people in the watched conditions, for each way of matching that `read` has."""
    return [ast.And(exprs=[count, in_condition]) for in_condition in read.in_condition.values() for count in counts]


def read_in_condition(
    matches: Sequence[ConditionMatch], values: Sequence[int]
) -> dict[ConditionMatch, tuple[int, ...]]:
    """The values of the columns from `in_condition_columns`, split evenly between the ways of matching."""
    if not matches:
        return {}
    per_match = len(values) // len(matches)
    return {
        match: tuple(values[position * per_match : (position + 1) * per_match])
        for position, match in enumerate(matches)
    }


def _chain(joins: Sequence[ast.JoinExpr]) -> ast.JoinExpr | None:
    head: ast.JoinExpr | None = None
    for join in reversed(joins):
        head = replace(join, next_join=head)
    return head


def _states(index: int, edit: WatchedEdit, read: FlagRead, counts: Sequence[ast.Expr]) -> list[ast.Alias]:
    return [
        ast.Alias(
            alias=f"e{index}_{position}",
            expr=parse_expr(
                "uniqState(if({has_actor} AND timestamp >= {edited_at} AND {count}, {actor}, NULL))",
                placeholders={
                    "actor": read.actor,
                    "has_actor": read.has_actor,
                    "edited_at": ast.Constant(value=edit.edited_at),
                    "count": count,
                },
            ),
        )
        for position, count in enumerate(counts)
    ]


@frozen
class _BucketQuery:
    team: Team
    edits: Sequence[WatchedEdit]
    counts: Callable[[WatchedEdit, FlagRead], Sequence[ast.Expr]]
    start: datetime
    end: datetime
    seconds: int
    buckets: int
    query_type: str
    event: str | None
    joins: tuple[ast.JoinExpr, ...]

    def run(self, with_properties: bool) -> dict[str, EditCounts]:
        # Each run builds its own tree, because resolving a query can change the nodes in it.
        reason_joins, reason_columns = _reason_joins(self.team, self.edits, self.end)
        joins = [*(clone_expr(join) for join in self.joins), *reason_joins]
        reads = [
            read_flag(edit, _in_condition(self.team, edit, reason_columns.get(edit.id), self.end, with_properties))
            for edit in self.edits
        ]
        states_by_edit = [
            _states(index, edit, read, self.counts(edit, read))
            for index, (edit, read) in enumerate(zip(self.edits, reads))
        ]
        states = [state for edit_states in states_by_edit for state in edit_states]
        # Buckets start at `start`, not at a multiple of the bucket since the epoch, so a range that starts at an edit
        # time does not begin with a partial bucket.
        bucket_start = parse_expr(
            "toStartOfInterval(timestamp, toIntervalSecond({seconds}), {start})",
            placeholders={"seconds": ast.Constant(value=self.seconds), "start": ast.Constant(value=self.start)},
        )
        where = parse_expr(
            "timestamp >= {start} AND timestamp < {end}",
            placeholders={"start": ast.Constant(value=self.start), "end": ast.Constant(value=self.end)},
        )
        if self.event is not None:
            where = ast.And(
                exprs=[where, parse_expr("event = {event}", placeholders={"event": ast.Constant(value=self.event)})]
            )
        per_bucket = ast.SelectQuery(
            select=[ast.Alias(alias="bucket", expr=bucket_start), *states],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"]), next_join=_chain(joins)),
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
            limit=ast.Constant(value=self.buckets),
        )
        with tags_context(
            product=Product.FEATURE_FLAGS,
            feature=Feature.HEALTH_CHECK,
            team_id=self.team.pk,
            org_id=self.team.organization_id,
        ):
            response = execute_hogql_query(
                query,
                team=self.team,
                query_type=self.query_type,
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
                    # The reason joins group the flag calls by actor. On a large team the aggregation goes to disk
                    # instead of failing the counts of every edit.
                    max_bytes_before_external_group_by=SPILL_GROUP_BY_AFTER_BYTES,
                ),
            )

        rows_by_edit: dict[str, list[BucketCounts]] = {edit.id: [] for edit in self.edits}
        for row in response.results or []:
            values = iter(row[1:])
            for edit, edit_states in zip(self.edits, states_by_edit):
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
            edit.id: EditCounts(matches=tuple(read.in_condition), buckets=tuple(rows_by_edit[edit.id]))
            for edit, read in zip(self.edits, reads)
        }


def counts_by_bucket(
    team: Team,
    edits: Sequence[WatchedEdit],
    counts: Callable[[WatchedEdit, FlagRead], Sequence[ast.Expr]],
    start: datetime,
    end: datetime,
    bucket: timedelta,
    query_type: str,
    event: str | None = None,
    joins: Sequence[ast.JoinExpr] = (),
) -> dict[str, EditCounts]:
    """For each edit, the people (or groups) that each of its `counts` holds for after the edit, in each bucket of
    `[start, end)` that has events, oldest bucket first. `query_type` names the query in the query log. `event` limits
    the scan to one event name. `joins` join tables to the events, so that the counts of every edit can read them."""
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

    query = _BucketQuery(
        team=team,
        edits=edits,
        counts=counts,
        start=start,
        end=end,
        seconds=int(seconds),
        buckets=buckets,
        query_type=query_type,
        event=event,
        joins=tuple(joins),
    )
    try:
        return query.run(with_properties=True)
    except InternalCHQueryError as error:
        if error.code not in PROPERTY_VALUE_ERROR_CODES:
            raise
        # ClickHouse doesn't say which filter it rejected, so every edit loses its counts by properties. Its message
        # quotes the value it couldn't parse, so only the code goes to the logs.
        logger.warning("flag_window_properties_rejected", team_id=team.pk, code=error.code)
        return query.run(with_properties=False)
