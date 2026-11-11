import json
from typing import Any, Optional

from django.conf import settings

from rest_framework import exceptions

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models.property import GroupTypeIndex, PropertyGroup
from posthog.models.property.parse import expand_cohort_properties, parse_property_group_data
from posthog.models.property.property import Property, PropertyValidationError
from posthog.models.team.team import Team

from products.feature_flags.backend.user_blast_radius import (
    PERSON_BATCH_SIZE as GROUP_AUDIENCE_PAGE_SIZE,
    get_user_blast_radius_persons,
    replace_proxy_properties,
    unevaluable_filters_as_validation_errors,
)
from products.workflows.backend.services.batch_audience_cohorts import reject_excluded_cohort_without_members

EMAIL_DEDUPE_KEY = "email"
SUPPORTED_DEDUPE_KEYS = (EMAIL_DEDUPE_KEY,)


def person_audience_page_size() -> int:
    return settings.WORKFLOWS_PERSON_BATCH_SIZE


def audience_page_size(group_type_index: Optional[GroupTypeIndex]) -> int:
    """
    Page size the resolver must compare a page length against to decide `has_more`.

    Group audiences page through the flags-owned group query, which keeps its own fixed limit.
    """
    if group_type_index is not None:
        return GROUP_AUDIENCE_PAGE_SIZE
    return person_audience_page_size()


# A batch audience is a one-time snapshot of everyone matching the conditions at run time, so each
# condition must resolve to a concrete set of persons/groups. Feature flag evaluation is dynamic
# (rollout %, distinct_id hashing, super-conditions, holdouts) and has no such fixed membership, so a
# flag condition can't be turned into an audience query — it falls through to a NotImplementedError
# deeper in HogQL property compilation. Reject it up front with a clear 400 instead.
BATCH_FLAG_CONDITION_REJECTION = (
    "Feature flags can't be used as a batch audience condition. Use person properties or cohorts instead."
)


INCOMPLETE_AUDIENCE_CONDITION = "An audience filter is incomplete. Finish it or remove it."


def _is_condition_group(condition: Any) -> bool:
    return isinstance(condition, dict) and "type" in condition and "values" in condition


VALUELESS_OPERATORS = ("is_set", "is_not_set")


def _is_finished_condition(condition: Any) -> bool:
    try:
        Property(**condition)
    except (PropertyValidationError, exceptions.ValidationError, TypeError):
        return False
    if condition.get("type") == "cohort" and not str(condition.get("value")).isdigit():
        return False
    return (
        condition.get("value") != []
        or condition.get("operator") in VALUELESS_OPERATORS
        or condition.get("type") == "hogql"
    )


def _has_unfinished_condition(conditions: Any) -> bool:
    if _is_condition_group(conditions):
        if not isinstance(conditions["values"], list):
            return True
        conditions = conditions["values"]
    if not isinstance(conditions, list):
        return False
    return any(
        _has_unfinished_condition(condition)
        if _is_condition_group(condition)
        else not _is_finished_condition(condition)
        for condition in conditions
    )


def reject_unusable_audience_conditions(team: Team, filters: dict) -> None:
    properties = (filters or {}).get("properties")
    if isinstance(properties, str) and properties.strip():
        try:
            properties = json.loads(properties)
        except json.JSONDecodeError:
            properties = None
    if _has_unfinished_condition(properties):
        raise exceptions.ValidationError(INCOMPLETE_AUDIENCE_CONDITION)
    # Cohorts are expanded so a flag condition nested inside one is still caught.
    property_groups = expand_cohort_properties(parse_property_group_data((filters or {}).get("properties")), team)
    if any(prop.type == "flag" for prop in property_groups.flat):
        raise exceptions.ValidationError(BATCH_FLAG_CONDITION_REJECTION)


def get_batch_audience_person_ids(
    team: Team,
    filters: dict,
    group_type_index: Optional[GroupTypeIndex] = None,
    cursor: Optional[str] = None,
    dedupe_key: Optional[str] = None,
    settings: Optional[HogQLGlobalSettings] = None,
) -> list[str]:
    """
    Enumerate one page of a batch workflow's audience (person UUIDs, cursor-paginated).

    With dedupe_key="email", persons sharing a normalized email collapse to the one with
    the smallest UUID, so an email address receives a given batch send only once. Persons
    without an email are never collapsed.
    """
    if group_type_index is not None:
        # Group keys are already unique; the flags-owned group query needs no dedup.
        return get_user_blast_radius_persons(team, filters, group_type_index, cursor)

    with unevaluable_filters_as_validation_errors():
        cleaned_filter = replace_proxy_properties(team, filters)
        reject_excluded_cohort_without_members(team.project_id, cleaned_filter)
        select_query = _build_audience_person_query(team, cleaned_filter, cursor=cursor, dedupe_key=dedupe_key)

        tag_queries(product=Product.WORKFLOWS, feature=Feature.QUERY)
        # Background traffic: the only caller is the internal batch-send resolver, so route to
        # the offline pool like the group branch does, away from interactive product queries.
        response = execute_hogql_query(query=select_query, team=team, settings=settings, workload=Workload.OFFLINE)

    return [str(row[0]) for row in response.results] if response.results else []


def get_batch_audience_person_ids_snapshot(
    team: Team,
    filters: dict,
    *,
    dedupe_key: Optional[str],
    limit: int,
    settings: HogQLGlobalSettings,
) -> list[str]:
    """
    The whole person audience in one query, in person id order, for a run that resolves its audience
    once up front instead of rescanning the person table per page. Applies the same email dedupe.
    """
    reject_unusable_audience_conditions(team, filters)
    with unevaluable_filters_as_validation_errors():
        cleaned_filter = replace_proxy_properties(team, filters)
        select_query = _build_audience_person_query(team, cleaned_filter, dedupe_key=dedupe_key, limit=limit)

        tag_queries(product=Product.WORKFLOWS, feature=Feature.QUERY)
        response = execute_hogql_query(
            query=select_query,
            team=team,
            settings=settings,
            workload=Workload.OFFLINE,
            # The cohort limit context lets the explicit LIMIT above exceed the interactive row cap.
            limit_context=LimitContext.COHORT_CALCULATION,
        )

    return [str(row[0]) for row in response.results] if response.results else []


def email_dedupe_group_expr() -> ast.Expr:
    # Fields stay fully qualified so nothing resolves to an enclosing query's alias.
    return parse_expr(
        """
        if(
            isNull(persons.properties.email) OR trim(toString(persons.properties.email)) = '',
            toString(persons.id),
            lower(trim(toString(persons.properties.email)))
        )
        """
    )


def _build_audience_person_query(
    team: Team,
    prop_group: PropertyGroup,
    cursor: Optional[str] = None,
    dedupe_key: Optional[str] = None,
    limit: Optional[int] = None,
) -> ast.SelectQuery:
    if limit is None:
        limit = person_audience_page_size()
    where_exprs: list[ast.Expr] = [
        ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["persons", "team_id"]),
            right=ast.Constant(value=team.pk),
        ),
        property_to_expr(prop_group, team, scope="person"),
    ]

    if dedupe_key == EMAIL_DEDUPE_KEY:
        return _wrap_with_email_dedupe(where_exprs, cursor, limit)

    if cursor is not None:
        where_exprs.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.Gt,
                left=ast.Field(chain=["persons", "id"]),
                right=ast.Constant(value=cursor),
            )
        )

    return ast.SelectQuery(
        select=[ast.Field(chain=["persons", "id"])],
        select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
        distinct=True,
        where=ast.And(exprs=where_exprs),
        order_by=[ast.OrderExpr(expr=ast.Field(chain=["persons", "id"]), order="ASC")],
        limit=ast.Constant(value=limit),
    )


def _wrap_with_email_dedupe(where_exprs: list[ast.Expr], cursor: Optional[str], limit: int) -> ast.SelectQuery:
    """
    One person (min UUID) per normalized email; persons without an email keep their own group.

    The cursor filter MUST sit outside the aggregation: applying `id > cursor` before the
    GROUP BY would recompute min(id) over the remaining persons only, re-emitting an email
    whose persons straddle a page boundary.
    """
    inner_query = ast.SelectQuery(
        select=[ast.Alias(alias="person_id", expr=ast.Call(name="min", args=[ast.Field(chain=["persons", "id"])]))],
        select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
        where=ast.And(exprs=where_exprs),
        group_by=[email_dedupe_group_expr()],
    )

    outer_where: Optional[ast.Expr] = None
    if cursor is not None:
        outer_where = ast.CompareOperation(
            op=ast.CompareOperationOp.Gt,
            left=ast.Field(chain=["person_id"]),
            right=ast.Constant(value=cursor),
        )

    return ast.SelectQuery(
        select=[ast.Field(chain=["person_id"])],
        select_from=ast.JoinExpr(table=inner_query),
        where=outer_where,
        order_by=[ast.OrderExpr(expr=ast.Field(chain=["person_id"]), order="ASC")],
        limit=ast.Constant(value=limit),
    )
