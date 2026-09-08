from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Optional

from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

import structlog
from rest_framework.exceptions import ValidationError

from posthog.schema import PropertyOperator

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import (
    ExposedHogQLError,
    NotImplementedError as HogQLNotImplementedError,
)
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.errors import ExposedCHQueryError, InternalCHQueryError
from posthog.models.filters import Filter
from posthog.models.property import GroupTypeIndex, Property, PropertyGroup, PropertyValidationError
from posthog.models.team.team import Team
from posthog.ph_client import feature_enabled_or_false
from posthog.queries.base import relative_date_parse_for_feature_flag_matching

from products.cohorts.backend.models.cohort import Cohort

logger = structlog.get_logger(__name__)


@frozen
class BlastRadiusResult:
    affected: int
    total: int


# Window for the blast-radius denominator. An all-time person count is inflated by anonymous,
# one-shot persons that never return; a recent-activity window drops them and is defensible.
RECENTLY_ACTIVE_DAYS = 60

RECENTLY_ACTIVE_SIZING_FLAG = "flags-size-by-active-persons"

# The recently-active count depends on the team alone, and the flag editor asks for it once per
# empty-properties condition group on every mount, so a short TTL collapses those into one scan.
_RECENTLY_ACTIVE_COUNT_CACHE_TTL = 300

# A personless event carries a synthetic person_id derived from its distinct id, and no persons row
# is ever written for it. Counting it would put anonymous traffic in a denominator that the
# matched-persons subquery can never return, and would raise the total for projects on posthog-js's
# identified_only default, which is the opposite of what the window is for.
_IDENTIFIED_PERSONS_ONLY = "person_mode != 'propertyless'"


# ClickHouse codes for "this literal can't be parsed as the column's type": 6 CANNOT_PARSE_TEXT,
# 72 CANNOT_PARSE_NUMBER — e.g. a numeric operator (gt/lt) against a null or non-numeric filter
# value casts 'None' to Float64 and fails deterministically. Both are classified USER_ERROR in
# posthog/errors.py but not user_safe, so they wrap to InternalCHQueryError, not Exposed.
_VALUE_PARSE_CH_ERROR_CODES = frozenset({6, 72})


@contextmanager
def unevaluable_filters_as_validation_errors() -> Iterator[None]:
    # Sizing runs caller-supplied condition filters through HogQL and ClickHouse. Shapes those
    # layers reject - behavioral or event filters in person scope, deleted cohort references,
    # malformed regexes, values that don't cast to the property's type - fail deterministically
    # on every request, so they're the caller's input, not a server fault: surface them as a 400
    # carrying the layer's own message instead of an opaque 500. Only deliberately-exposed error
    # types are converted across query build and execution - plus ObjectDoesNotExist from cohort
    # lookups, PropertyValidationError from Property construction during query build (its message
    # already names the offending property), and the ClickHouse cannot-parse-value codes above.
    # Caller-shaped ValueError is converted separately in the parse phase
    # (replace_proxy_properties), so a bare ValueError from HogQL internals or team config
    # during build/execution still surfaces as a server fault, as does any other
    # InternalCHQueryError.
    try:
        yield
    except (
        ExposedHogQLError,
        HogQLNotImplementedError,
        ExposedCHQueryError,
        ObjectDoesNotExist,
        PropertyValidationError,
    ) as e:
        raise ValidationError({"filters": str(e) or "These filters cannot be evaluated."}) from e
    except InternalCHQueryError as e:
        if e.code not in _VALUE_PARSE_CH_ERROR_CODES:
            raise
        # Unlike ExposedCHQueryError, InternalCHQueryError's str() keeps the raw server message.
        # Rewrap so ExposedCHQueryError.__str__ strips the DB::Exception framing and any stack
        # trace tail before the message is echoed back to the caller.
        sanitized = str(ExposedCHQueryError(e.message, code=e.code, code_name=e.code_name))
        raise ValidationError({"filters": sanitized or "These filters cannot be evaluated."}) from e


def _normalize_property_value(prop: Property) -> None:
    """
    Normalize property values to strings to match JSON-stored properties in ClickHouse.
    Skip special properties like $group_key which refer to columns, not JSON properties.
    """
    if prop.key == "$group_key":
        return  # Don't normalize $group_key - it's a column reference

    if prop.type in ("person", "group"):
        if isinstance(prop.value, list):
            prop.value = [str(v) for v in prop.value]
        elif not isinstance(prop.value, str | list | dict | type(None)):
            prop.value = str(prop.value)


def replace_proxy_properties(team: Team, feature_flag_condition: dict):
    # Parse phase: everything here derives directly from the caller's filter JSON, so a
    # ValueError is caller input (malformed property shape, non-numeric cohort id) and becomes
    # a 400. Cohort ids are cast eagerly so a bad id fails here instead of surfacing as a bare
    # ValueError from deep inside query building.
    try:
        prop_groups = Filter(data=feature_flag_condition, team=team).property_groups

        for prop in prop_groups.flat:
            if prop.type in ("cohort", "static-cohort", "precalculated-cohort"):
                Cohort._meta.pk.get_prep_value(prop.value)
            if prop.operator in ("is_date_before", "is_date_after"):
                relative_date = relative_date_parse_for_feature_flag_matching(str(prop.value))
                if relative_date:
                    prop.value = relative_date.strftime("%Y-%m-%d %H:%M:%S")
            else:
                _normalize_property_value(prop)

        return Filter(data={"properties": prop_groups.to_dict()}, team=team)
    except ValueError as e:
        raise ValidationError({"filters": str(e) or "These filters cannot be evaluated."}) from e


def recently_active_sizing_enabled(team: Team) -> bool:
    """Kill switch for the activity window on the flags sizing endpoint.

    False restores the all-time count the window replaced, which is still the behavior the
    workflows audience preview depends on, so a disable costs accuracy and never correctness.
    Evaluation is local-only, so a sizing request never waits on a flag fetch.
    """
    try:
        return feature_enabled_or_false(
            RECENTLY_ACTIVE_SIZING_FLAG,
            f"team-{team.pk}",
            groups={"project": str(team.pk)},
            group_properties={"project": {"id": str(team.pk)}},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    except Exception:
        # Log so a fleet-wide silent disable shows up in Sentry rather than as a number that
        # quietly went back to its old value.
        logger.warning(
            "flag_blast_radius_sizing_flag_evaluation_failed",
            team_id=team.pk,
            flag=RECENTLY_ACTIVE_SIZING_FLAG,
            exc_info=True,
        )
        return False


def get_user_blast_radius(
    team: Team,
    feature_flag_condition: dict,
    group_type_index: Optional[GroupTypeIndex] = None,
    *,
    recently_active_only: bool = False,
) -> BlastRadiusResult:
    # No rollout % calculations here, since it makes more sense to compute that on the frontend
    # recently_active_only stays off by default: the workflows audience preview shares this
    # function, and its count must match the unwindowed send enumeration in batch_audience.py.
    with unevaluable_filters_as_validation_errors():
        cleaned_filter = replace_proxy_properties(team, feature_flag_condition)

        if group_type_index is not None:
            return _get_group_blast_radius(team, cleaned_filter, group_type_index)
        if recently_active_only:
            return _get_person_blast_radius_recently_active(team, cleaned_filter)
        return _get_person_blast_radius(team, cleaned_filter)


def get_user_blast_radius_persons(
    team: Team,
    feature_flag_condition: dict,
    group_type_index: Optional[GroupTypeIndex] = None,
    cursor: Optional[str] = None,
):
    # No rollout % calculations here, since it makes more sense to compute that on the frontend
    with unevaluable_filters_as_validation_errors():
        cleaned_filter = replace_proxy_properties(team, feature_flag_condition)

        if group_type_index is not None:
            return _get_group_blast_radius_persons(team, cleaned_filter, group_type_index, cursor=cursor)
        else:
            return _get_person_blast_radius_persons(team, cleaned_filter, cursor=cursor)


def _recently_active_window() -> tuple[datetime, datetime]:
    """Bounds of the blast-radius activity window, computed in Python so they respect freeze_time in
    tests and do not depend on ClickHouse server time. The upper bound allows a day of clock skew
    but stops a far-future event timestamp from keeping a person "active" for years."""
    now = timezone.now()
    return now - timedelta(days=RECENTLY_ACTIVE_DAYS), now + timedelta(days=1)


def _recently_active_persons_count(team: Team) -> int:
    """Count distinct persons active in the last RECENTLY_ACTIVE_DAYS days.

    This is the blast-radius denominator. It replaces an all-time person count so anonymous churn
    does not inflate the audience shown to a flag author (see RECENTLY_ACTIVE_DAYS). `uniq` is an
    estimate, which matches the "~" the release conditions panel already renders.
    """
    cache_key = f"flag_blast_radius:recently_active_persons:{team.pk}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    cutoff, upper = _recently_active_window()
    query = parse_select(
        "SELECT uniq(person_id) FROM events "
        f"WHERE timestamp >= {{cutoff}} AND timestamp < {{upper}} AND {_IDENTIFIED_PERSONS_ONLY}",
        placeholders={"cutoff": ast.Constant(value=cutoff), "upper": ast.Constant(value=upper)},
    )

    tag_queries(product=Product.FEATURE_FLAGS, feature=Feature.QUERY)
    response = execute_hogql_query(
        query=query,
        team=team,
        workload=Workload.OFFLINE,
        settings=HogQLGlobalSettings(timeout_overflow_mode="throw"),
    )

    count = response.results[0][0] if response.results else 0
    cache.set(cache_key, count, timeout=_RECENTLY_ACTIVE_COUNT_CACHE_TTL)
    return count


def _matched_persons_query(team: Team, filter: Filter) -> ast.SelectQuery:
    """Subquery of the person ids matching the condition. Reuses property_to_expr in person scope,
    so it resolves cohorts, static cohorts, and group properties exactly like _build_person_query."""
    return ast.SelectQuery(
        select=[ast.Field(chain=["persons", "id"])],
        select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
        where=ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["persons", "team_id"]),
                    right=ast.Constant(value=team.pk),
                ),
                property_to_expr(filter.property_groups, team, scope="person"),
            ]
        ),
    )


def _get_person_blast_radius_recently_active(team: Team, filter: Filter) -> BlastRadiusResult:
    """Calculate blast radius for person-based feature flags over the recent activity window.

    Both counts are of persons active in the same recent window, so the matched count is never a
    different population from the total it is shown against.
    """
    properties = filter.property_groups.flat

    if len(properties) == 0:
        # No filters means every recently active person is affected.
        total_users = _recently_active_persons_count(team)
        return BlastRadiusResult(affected=total_users, total=total_users)

    cutoff, upper = _recently_active_window()
    # One pass over the recent event window yields both the active total and the matched subset, so
    # the denominator is never a second scan and both numbers come from the same rows.
    query = parse_select(
        "SELECT uniq(person_id), uniqIf(person_id, person_id IN {matched}) "
        f"FROM events WHERE timestamp >= {{cutoff}} AND timestamp < {{upper}} AND {_IDENTIFIED_PERSONS_ONLY}",
        placeholders={
            "matched": _matched_persons_query(team, filter),
            "cutoff": ast.Constant(value=cutoff),
            "upper": ast.Constant(value=upper),
        },
    )

    tag_queries(product=Product.FEATURE_FLAGS, feature=Feature.QUERY)
    # OFFLINE for the same reason as _get_group_blast_radius below: a 60-day events scan is too
    # heavy for the pool that serves interactive analytics. A partial result on timeout would be a
    # confidently wrong audience number, so overflow throws instead.
    response = execute_hogql_query(
        query=query,
        team=team,
        workload=Workload.OFFLINE,
        settings=HogQLGlobalSettings(timeout_overflow_mode="throw"),
    )

    total_users, affected = (response.results[0][0], response.results[0][1]) if response.results else (0, 0)
    # affected is a strict subset of total_users, but both are uniq() estimates, so clamp to keep
    # the frontend percentage coherent.
    return BlastRadiusResult(affected=min(affected, total_users), total=total_users)


def _get_person_blast_radius(team: Team, filter: Filter) -> BlastRadiusResult:
    """Calculate all-time blast radius for person-based feature flags using HogQL."""

    properties = filter.property_groups.flat

    if len(properties) == 0:
        # No filters means all persons are affected
        total_users = team.persons_seen_so_far
        return BlastRadiusResult(affected=total_users, total=total_users)

    # Build the SELECT query - property_to_expr handles all properties including cohorts
    select_query = _build_person_query(team, filter, return_count=True)

    # Execute the query
    tag_queries(product=Product.FEATURE_FLAGS, feature=Feature.QUERY)
    # Build the team's HogQL database once and share it between the two counts below.
    # Each execute_hogql_query call would otherwise build its own, and the build cost
    # scales with the team's warehouse size.
    database = Database.create_for(team=team)
    response = execute_hogql_query(
        query=select_query,
        team=team,
        context=HogQLContext(team_id=team.pk, database=database),
    )

    total_count = response.results[0][0] if response.results else 0
    total_users = team.count_persons_seen_so_far(database=database)
    blast_radius = min(total_count, total_users)

    return BlastRadiusResult(affected=blast_radius, total=total_users)


def _build_person_query(team: Team, filter: Filter, return_count: bool = True, cursor: Optional[str] = None):
    """Build HogQL AST query to count or select distinct persons matching filters."""

    # Build the main SELECT with either count(DISTINCT persons.id) or DISTINCT persons.id
    if return_count:
        select_query = ast.SelectQuery(
            select=[ast.Call(name="count", distinct=True, args=[ast.Field(chain=["persons", "id"])])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
        )
    else:
        select_query = ast.SelectQuery(
            select=[ast.Field(chain=["persons", "id"])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
            distinct=True,
        )

    # Build WHERE clause with team_id and property filters
    # property_to_expr handles all property types including cohorts
    where_exprs: list[ast.Expr] = [
        ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["persons", "team_id"]),
            right=ast.Constant(value=team.pk),
        )
    ]

    # Add all property filters (including cohorts) via property_to_expr
    property_expr = property_to_expr(filter.property_groups, team, scope="person")
    where_exprs.append(property_expr)

    # Add cursor-based pagination when returning IDs
    if not return_count and cursor is not None:
        where_exprs.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.Gt,
                left=ast.Field(chain=["persons", "id"]),
                right=ast.Constant(value=cursor),
            )
        )

    # Combine all WHERE expressions with AND
    select_query.where = ast.And(exprs=where_exprs)

    # Add ORDER BY and LIMIT for pagination when returning IDs
    if not return_count:
        select_query.order_by = [ast.OrderExpr(expr=ast.Field(chain=["persons", "id"]), order="ASC")]
        select_query.limit = ast.Constant(value=500)

    return select_query


def _get_group_blast_radius(team: Team, filter: Filter, group_type_index: GroupTypeIndex) -> BlastRadiusResult:
    """Calculate blast radius for group-based feature flags using HogQL."""

    properties = filter.property_groups.flat

    # Validate all group properties have correct group_type_index
    for property in properties:
        if property.type == "flag":
            # Flag dependencies are evaluated at flag-matching time, not in the group query,
            # and carry no group_type_index — skip validation and let property_to_expr neutralize them.
            continue
        if property.key == "$group_key":
            # Special case: $group_key doesn't need a group_type_index as it refers to the key itself
            property.group_type_index = group_type_index
        elif property.group_type_index is None or property.group_type_index != group_type_index:
            raise ValidationError("Invalid group type index for feature flag condition.")

    if len(properties) == 0:
        # No filters means all groups of this type are affected
        total_groups = team.groups_seen_so_far(group_type_index)
        return BlastRadiusResult(affected=total_groups, total=total_groups)

    # Build the SELECT query for groups
    select_query = _build_group_query(team, filter, group_type_index, return_count=True)

    # Execute the query with OFFLINE workload (groups queries can be massive)
    tag_queries(product=Product.FEATURE_FLAGS, feature=Feature.QUERY)
    # One database build shared by both counts, as in _get_person_blast_radius above.
    database = Database.create_for(team=team)
    response = execute_hogql_query(
        query=select_query,
        team=team,
        workload=Workload.OFFLINE,
        context=HogQLContext(team_id=team.pk, database=database),
    )

    total_affected = response.results[0][0] if response.results else 0
    total_groups = team.count_groups_seen_so_far(group_type_index, database=database)

    return BlastRadiusResult(affected=total_affected, total=total_groups)


PERSON_BATCH_SIZE = 500


def _build_group_query(
    team: Team,
    filter: Filter,
    group_type_index: GroupTypeIndex,
    return_count: bool = True,
    cursor: Optional[str] = None,
):
    """Build HogQL AST query to count or select distinct groups matching filters."""

    # Build the main SELECT with either count(DISTINCT groups.key) or DISTINCT groups.key
    if return_count:
        select_query = ast.SelectQuery(
            select=[ast.Call(name="count", distinct=True, args=[ast.Field(chain=["groups", "key"])])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["groups"])),
        )
    else:
        select_query = ast.SelectQuery(
            select=[ast.Field(chain=["groups", "key"])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["groups"])),
            distinct=True,
        )

    # Build WHERE clauses
    where_exprs: list[ast.Expr] = [
        ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["groups", "team_id"]),
            right=ast.Constant(value=team.pk),
        ),
        ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["groups", "index"]),
            right=ast.Constant(value=group_type_index),
        ),
    ]

    # Handle $group_key properties specially - they reference the key column directly
    # Split properties into $group_key properties and regular properties
    group_key_properties = []
    regular_properties = []

    for prop in filter.property_groups.flat:
        if prop.key == "$group_key":
            group_key_properties.append(prop)
        else:
            regular_properties.append(prop)

    # Add $group_key filters directly as column comparisons
    for prop in group_key_properties:
        # Normalize operator to PropertyOperator enum for consistent comparisons
        operator = PropertyOperator(prop.operator) if prop.operator else PropertyOperator.EXACT
        value = prop.value

        # Convert values to strings for consistency (groups.key is a String column)
        # Handles both single values and lists, preserving None
        if isinstance(value, list):
            value = [str(v) if v is not None else None for v in value]
        elif value is not None:
            value = str(value)

        if operator == PropertyOperator.EXACT:
            if isinstance(value, list):
                # List values should use IN logic (match any value in the list)
                where_exprs.append(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.In,
                        left=ast.Field(chain=["groups", "key"]),
                        right=ast.Tuple(exprs=[ast.Constant(value=v) for v in value]),
                    )
                )
            else:
                # Single value uses equality
                where_exprs.append(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["groups", "key"]),
                        right=ast.Constant(value=value),
                    )
                )
        elif operator == PropertyOperator.IS_NOT:
            if isinstance(value, list):
                # List values should use NOT IN logic (doesn't match any value)
                where_exprs.append(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.NotIn,
                        left=ast.Field(chain=["groups", "key"]),
                        right=ast.Tuple(exprs=[ast.Constant(value=v) for v in value]),
                    )
                )
            else:
                # Single value uses inequality
                where_exprs.append(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.NotEq,
                        left=ast.Field(chain=["groups", "key"]),
                        right=ast.Constant(value=value),
                    )
                )
        elif operator == PropertyOperator.IN_:
            values_list = value if isinstance(value, list) else [value]
            where_exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["groups", "key"]),
                    right=ast.Tuple(exprs=[ast.Constant(value=v) for v in values_list]),
                )
            )
        elif operator == PropertyOperator.NOT_IN:
            values_list = value if isinstance(value, list) else [value]
            where_exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.NotIn,
                    left=ast.Field(chain=["groups", "key"]),
                    right=ast.Tuple(exprs=[ast.Constant(value=v) for v in values_list]),
                )
            )
        elif operator == PropertyOperator.ICONTAINS:
            if isinstance(value, list):
                raise ValidationError(
                    "Operator 'icontains' does not support list values for $group_key property. "
                    "Use a single value instead."
                )
            where_exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.ILike,
                    left=ast.Field(chain=["groups", "key"]),
                    right=ast.Constant(value=f"%{value}%"),
                )
            )
        elif operator == PropertyOperator.NOT_ICONTAINS:
            if isinstance(value, list):
                raise ValidationError(
                    "Operator 'not_icontains' does not support list values for $group_key property. "
                    "Use a single value instead."
                )
            where_exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.NotILike,
                    left=ast.Field(chain=["groups", "key"]),
                    right=ast.Constant(value=f"%{value}%"),
                )
            )
        elif operator in (
            PropertyOperator.STARTS_WITH,
            PropertyOperator.NOT_STARTS_WITH,
            PropertyOperator.ENDS_WITH,
            PropertyOperator.NOT_ENDS_WITH,
        ):
            if isinstance(value, list):
                raise ValidationError(
                    f"Operator '{operator}' does not support list values for $group_key property. "
                    "Use a single value instead."
                )
            is_starts = operator in (PropertyOperator.STARTS_WITH, PropertyOperator.NOT_STARTS_WITH)
            is_positive = operator in (PropertyOperator.STARTS_WITH, PropertyOperator.ENDS_WITH)
            where_exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.ILike if is_positive else ast.CompareOperationOp.NotILike,
                    left=ast.Field(chain=["groups", "key"]),
                    right=ast.Constant(value=f"{value}%" if is_starts else f"%{value}"),
                )
            )
        elif operator == PropertyOperator.REGEX:
            if isinstance(value, list):
                raise ValidationError(
                    "Operator 'regex' does not support list values for $group_key property. Use a single value instead."
                )
            where_exprs.append(
                ast.Call(
                    name="match",
                    args=[
                        ast.Field(chain=["groups", "key"]),
                        ast.Constant(value=value),
                    ],
                )
            )
        elif operator == PropertyOperator.NOT_REGEX:
            if isinstance(value, list):
                raise ValidationError(
                    "Operator 'not_regex' does not support list values for $group_key property. "
                    "Use a single value instead."
                )
            where_exprs.append(
                ast.Call(
                    name="not",
                    args=[
                        ast.Call(
                            name="match",
                            args=[
                                ast.Field(chain=["groups", "key"]),
                                ast.Constant(value=value),
                            ],
                        )
                    ],
                )
            )
        else:
            # Unsupported operator for $group_key
            raise ValidationError(
                f"Operator '{operator}' is not supported for $group_key property. "
                f"Supported operators: exact, is_not, in, not_in, icontains, not_icontains, "
                f"starts_with, not_starts_with, ends_with, not_ends_with, regex, not_regex"
            )

    # Add regular property filters using property_to_expr (only if there are any)
    if regular_properties:
        regular_filter = Filter(
            data={"properties": PropertyGroup(type=filter.property_groups.type, values=regular_properties).to_dict()},
            team=team,
        )
        property_expr = property_to_expr(regular_filter.property_groups, team, scope="group")
        where_exprs.append(property_expr)

    # Add cursor-based pagination when returning keys
    if not return_count and cursor is not None:
        where_exprs.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.Gt,
                left=ast.Field(chain=["groups", "key"]),
                right=ast.Constant(value=cursor),
            )
        )

    # Combine all WHERE expressions with AND
    select_query.where = ast.And(exprs=where_exprs)

    # Add ORDER BY and LIMIT for pagination when returning keys
    if not return_count:
        select_query.order_by = [ast.OrderExpr(expr=ast.Field(chain=["groups", "key"]), order="ASC")]
        select_query.limit = ast.Constant(value=PERSON_BATCH_SIZE)

    return select_query


def _get_person_blast_radius_persons(team: Team, filter: Filter, cursor: Optional[str] = None) -> list[str]:
    """Get distinct person IDs matching person-based feature flag filters."""

    # Build the SELECT query to get person IDs
    select_query = _build_person_query(team, filter, return_count=False, cursor=cursor)

    tag_queries(product=Product.FEATURE_FLAGS, feature=Feature.QUERY)
    response = execute_hogql_query(
        query=select_query,
        team=team,
    )

    # Extract person IDs from results
    person_ids = [str(row[0]) for row in response.results] if response.results else []
    return person_ids


def _get_group_blast_radius_persons(
    team: Team, filter: Filter, group_type_index: GroupTypeIndex, cursor: Optional[str] = None
) -> list[str]:
    """Get distinct group keys matching group-based feature flag filters."""

    properties = filter.property_groups.flat

    # Validate all group properties have correct group_type_index
    for property in properties:
        if property.type == "flag":
            # Flag dependencies are evaluated at flag-matching time, not in the group query,
            # and carry no group_type_index — skip validation and let property_to_expr neutralize them.
            continue
        if property.key == "$group_key":
            property.group_type_index = group_type_index
        elif property.group_type_index is None or property.group_type_index != group_type_index:
            raise ValidationError("Invalid group type index for feature flag condition.")

    # Build the SELECT query to get group keys
    select_query = _build_group_query(team, filter, group_type_index, return_count=False, cursor=cursor)

    tag_queries(product=Product.FEATURE_FLAGS, feature=Feature.QUERY)
    response = execute_hogql_query(
        query=select_query,
        team=team,
        workload=Workload.OFFLINE,
    )

    # Extract group keys from results
    group_keys = [str(row[0]) for row in response.results] if response.results else []
    return group_keys
