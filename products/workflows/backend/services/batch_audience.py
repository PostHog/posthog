import math
import time
from itertools import pairwise
from typing import Optional

from django.conf import settings

from rest_framework import exceptions

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.errors import ClickHouseQueryTimeOut
from posthog.models.property import GroupTypeIndex, PropertyGroup
from posthog.models.property.parse import expand_cohort_properties, parse_property_group_data
from posthog.models.team.team import Team

from products.feature_flags.backend.user_blast_radius import (
    PERSON_BATCH_SIZE as GROUP_AUDIENCE_PAGE_SIZE,
    get_user_blast_radius_persons,
    replace_proxy_properties,
    unevaluable_filters_as_validation_errors,
)

EMAIL_DEDUPE_KEY = "email"
SUPPORTED_DEDUPE_KEYS = (EMAIL_DEDUPE_KEY,)
AUDIENCE_CHUNK_SAMPLE_SIZE = 100_000


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


def reject_flag_conditions_in_audience(team: Team, filters: dict) -> None:
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
    The whole person audience, in person id order, for a run that resolves its audience once up front
    instead of rescanning the person table per page. Applies the same email dedupe.

    A big team's audience runs as several queries over consecutive person id ranges, so no single query
    has to hold the whole team in memory. No range starts after `settings.max_execution_time` has passed.
    """
    reject_flag_conditions_in_audience(team, filters)
    deadline = time.monotonic() + (settings.max_execution_time or 0)
    with unevaluable_filters_as_validation_errors():
        cleaned_filter = replace_proxy_properties(team, filters)
        boundaries = _person_id_chunk_boundaries(team, _remaining_budget(settings, deadline))
        # Keyed by dedupe group, first seen wins. The ranges run in ClickHouse's UUID order and each query
        # returns its rows in that order, so the first person seen for a group has the smallest id.
        audience: dict[str, str] = {}
        for id_from, id_to in pairwise([None, *boundaries, None]):
            if len(audience) >= limit:
                break
            # A range repeats at most len(audience) groups that an earlier range already holds, so this many
            # rows always cover the new groups still needed. Without dedupe no two ranges share a person.
            chunk_limit = limit if dedupe_key == EMAIL_DEDUPE_KEY else limit - len(audience)
            select_query = _build_snapshot_chunk_query(team, cleaned_filter, dedupe_key, id_from, id_to, chunk_limit)
            tag_queries(product=Product.WORKFLOWS, feature=Feature.QUERY)
            response = execute_hogql_query(
                query=select_query,
                team=team,
                settings=_remaining_budget(settings, deadline),
                workload=Workload.OFFLINE,
                # The cohort limit context lets the explicit LIMIT above exceed the interactive row cap.
                limit_context=LimitContext.COHORT_CALCULATION,
            )
            for row in response.results or []:
                person_id = str(row[0])
                audience.setdefault(str(row[1]) if dedupe_key == EMAIL_DEDUPE_KEY else person_id, person_id)
                if len(audience) >= limit:
                    break

    return list(audience.values())


def _remaining_budget(query_settings: HogQLGlobalSettings, deadline: float) -> HogQLGlobalSettings:
    remaining = math.floor(deadline - time.monotonic())
    if remaining < 1:
        raise ClickHouseQueryTimeOut("The audience used up its query budget")
    # The cohort limit context raises a lower cap to this floor anyway, so a range that starts close to the
    # deadline can run past it by up to the floor. Stating it here keeps that ceiling visible.
    return query_settings.model_copy(
        update={"max_execution_time": max(remaining, settings.HOGQL_INCREASED_MAX_EXECUTION_TIME)}
    )


def _person_id_chunk_boundaries(team: Team, query_settings: HogQLGlobalSettings) -> list[str]:
    rows_per_chunk = settings.WORKFLOWS_BATCH_AUDIENCE_SNAPSHOT_ROWS_PER_CHUNK
    max_chunks = settings.WORKFLOWS_BATCH_AUDIENCE_SNAPSHOT_MAX_CHUNKS
    tag_queries(product=Product.WORKFLOWS, feature=Feature.QUERY)
    # Sorted in ClickHouse, because ClickHouse orders UUIDs differently from their string form.
    [(row_count, sample)] = sync_execute(
        """
        SELECT count(), arraySort(groupArraySample(%(sample_size)s)(id))
        FROM person
        WHERE team_id = %(team_id)s
        """,
        {"team_id": team.pk, "sample_size": AUDIENCE_CHUNK_SAMPLE_SIZE},
        settings={"max_execution_time": query_settings.max_execution_time},
        workload=Workload.OFFLINE,
        team_id=team.pk,
    )
    chunks = min(max_chunks, math.ceil(row_count / rows_per_chunk), len(sample))
    if chunks <= 1:
        return []
    boundaries: list[str] = []
    for index in range(1, chunks):
        boundary = str(sample[index * len(sample) // chunks])
        if not boundaries or boundaries[-1] != boundary:
            boundaries.append(boundary)
    return boundaries


def _build_snapshot_chunk_query(
    team: Team,
    prop_group: PropertyGroup,
    dedupe_key: Optional[str],
    id_from: Optional[str],
    id_to: Optional[str],
    limit: int,
) -> ast.SelectQuery:
    where_exprs: list[ast.Expr] = [
        ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["persons", "team_id"]),
            right=ast.Constant(value=team.pk),
        ),
        property_to_expr(prop_group, team, scope="person"),
    ]
    if id_from is not None:
        where_exprs.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["persons", "id"]),
                right=ast.Constant(value=id_from),
            )
        )
    if id_to is not None:
        where_exprs.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.Lt,
                left=ast.Field(chain=["persons", "id"]),
                right=ast.Constant(value=id_to),
            )
        )

    if dedupe_key == EMAIL_DEDUPE_KEY:
        # The range filter can sit inside the aggregation here, unlike the paged query's cursor, because the
        # caller merges ranges in id order and keeps the first person it sees for each email.
        return ast.SelectQuery(
            select=[
                ast.Alias(alias="person_id", expr=ast.Call(name="min", args=[ast.Field(chain=["persons", "id"])])),
                ast.Alias(alias="dedupe_group", expr=email_dedupe_group_expr()),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
            where=ast.And(exprs=where_exprs),
            group_by=[email_dedupe_group_expr()],
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["person_id"]), order="ASC")],
            limit=ast.Constant(value=limit),
        )

    return ast.SelectQuery(
        select=[ast.Field(chain=["persons", "id"])],
        select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
        distinct=True,
        where=ast.And(exprs=where_exprs),
        order_by=[ast.OrderExpr(expr=ast.Field(chain=["persons", "id"]), order="ASC")],
        limit=ast.Constant(value=limit),
    )


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
) -> ast.SelectQuery:
    where_exprs: list[ast.Expr] = [
        ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["persons", "team_id"]),
            right=ast.Constant(value=team.pk),
        ),
        property_to_expr(prop_group, team, scope="person"),
    ]

    if dedupe_key == EMAIL_DEDUPE_KEY:
        return _wrap_with_email_dedupe(where_exprs, cursor)

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
        limit=ast.Constant(value=person_audience_page_size()),
    )


def _wrap_with_email_dedupe(where_exprs: list[ast.Expr], cursor: Optional[str]) -> ast.SelectQuery:
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
        limit=ast.Constant(value=person_audience_page_size()),
    )
