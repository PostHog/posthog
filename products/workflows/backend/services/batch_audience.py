from typing import Any, Optional

from rest_framework.exceptions import ValidationError

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.cdp.filters import collect_property_cohort_ids
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models.filters import Filter
from posthog.models.property import GroupTypeIndex
from posthog.models.team.team import Team

from products.cohorts.backend.models.cohort import Cohort, CohortType
from products.feature_flags.backend.user_blast_radius import (
    get_user_blast_radius_persons,
    replace_proxy_properties,
    unevaluable_filters_as_validation_errors,
)

PERSON_BATCH_SIZE = 500

EMAIL_DEDUPE_KEY = "email"
SUPPORTED_DEDUPE_KEYS = (EMAIL_DEDUPE_KEY,)

_MEMBERSHIP_SUBQUERY = (
    "(SELECT person_id FROM cohort_membership WHERE cohort_id = {cohort_id} "
    "GROUP BY person_id HAVING argMax(status, last_updated) = 'entered')"
)


def lower_realtime_cohorts_to_membership(team: Team, filters: dict) -> dict:
    """
    Rewrite realtime-cohort references in an audience's property tree to read the
    cohort_membership table.

    The default cohort lowering (`IN COHORT`) evaluates a realtime cohort's behavioral filters
    inline or reads stale precalculated membership — both wrong for a cohort whose membership
    is maintained by the realtime pipeline. Applied at query time only, so stored trigger
    filters keep their plain cohort references.

    Raises ValidationError when a referenced behavioral realtime cohort has lost eligibility
    since the workflow was saved (filters edited, backfill stamps reset): answering with the
    wrong membership would batch-send to the wrong people, so the enumeration fails loudly
    instead. Person-property-only realtime cohorts that aren't backfilled stay on the inline
    path, which evaluates them correctly, so pre-existing audiences keep working.
    """
    properties = filters.get("properties") if isinstance(filters, dict) else None
    if not properties:
        return filters

    cohort_ids = collect_property_cohort_ids(properties)
    if not cohort_ids:
        return filters

    realtime_cohorts = {}
    for cohort in Cohort.objects.filter(
        pk__in=cohort_ids,
        team__project_id=team.project_id,
        deleted=False,
        cohort_type=CohortType.REALTIME,
    ):
        if cohort.is_flag_compatible:
            realtime_cohorts[cohort.pk] = cohort
        elif any(p.type == "behavioral" for p in cohort.properties.flat):
            raise ValidationError(
                {
                    "filters": (
                        f"Cohort '{cohort.name}' isn't ready for realtime evaluation. "
                        "Audiences can only use realtime cohorts that have finished calculating."
                    )
                }
            )

    if not realtime_cohorts:
        return filters

    def _cohort_pk(node: dict) -> Optional[int]:
        value = node.get("value")
        if isinstance(value, bool) or not isinstance(value, str | int):
            return None
        try:
            return int(value)
        except ValueError:
            return None

    def _lower(node: Any) -> Any:
        if isinstance(node, list):
            return [_lower(item) for item in node]
        if not isinstance(node, dict):
            return node
        if node.get("type") in ("AND", "OR"):
            return {**node, "values": _lower(node.get("values") or [])}
        if node.get("type") == "cohort":
            pk = _cohort_pk(node)
            if pk in realtime_cohorts:
                membership = _MEMBERSHIP_SUBQUERY.format(cohort_id=pk)
                negated = node.get("operator") == "not_in"
                return {"type": "hogql", "key": f"persons.id {'NOT IN' if negated else 'IN'} {membership}"}
        return node

    return {**filters, "properties": _lower(properties)}


def get_batch_audience_person_ids(
    team: Team,
    filters: dict,
    group_type_index: Optional[GroupTypeIndex] = None,
    cursor: Optional[str] = None,
    dedupe_key: Optional[str] = None,
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
        cleaned_filter = replace_proxy_properties(team, lower_realtime_cohorts_to_membership(team, filters))
        select_query = _build_audience_person_query(team, cleaned_filter, cursor=cursor, dedupe_key=dedupe_key)

        tag_queries(product=Product.WORKFLOWS, feature=Feature.QUERY)
        response = execute_hogql_query(query=select_query, team=team)

    return [str(row[0]) for row in response.results] if response.results else []


def get_batch_audience_count(
    team: Team,
    filters: dict,
    dedupe_key: str,
) -> int:
    """
    Count how many sends a batch workflow would produce with dedup applied — i.e. the
    number of dedupe groups (unique emails, plus one group per email-less person).
    Mirrors get_batch_audience_person_ids so the preview matches the actual audience.
    """
    # Defence-in-depth against a new dedupe key slipping past the endpoint's allowlist:
    # if we ever add another supported key, this raise forces the caller to teach this
    # function about it too, rather than silently returning the email-deduped count.
    if dedupe_key == EMAIL_DEDUPE_KEY:
        group_expr = _email_dedupe_group_expr()
    else:
        raise ValueError(f"Unsupported dedupe_key: {dedupe_key!r} (supported: {SUPPORTED_DEDUPE_KEYS})")

    with unevaluable_filters_as_validation_errors():
        cleaned_filter = replace_proxy_properties(team, lower_realtime_cohorts_to_membership(team, filters))

        where_exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["persons", "team_id"]),
                right=ast.Constant(value=team.pk),
            ),
            property_to_expr(cleaned_filter.property_groups, team, scope="person"),
        ]

        select_query = ast.SelectQuery(
            select=[ast.Call(name="count", distinct=True, args=[group_expr])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
            where=ast.And(exprs=where_exprs),
        )

        tag_queries(product=Product.WORKFLOWS, feature=Feature.QUERY)
        response = execute_hogql_query(query=select_query, team=team)

    return response.results[0][0] if response.results else 0


def _email_dedupe_group_expr() -> ast.Expr:
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
    filter: Filter,
    cursor: Optional[str] = None,
    dedupe_key: Optional[str] = None,
) -> ast.SelectQuery:
    where_exprs: list[ast.Expr] = [
        ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["persons", "team_id"]),
            right=ast.Constant(value=team.pk),
        ),
        property_to_expr(filter.property_groups, team, scope="person"),
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
        limit=ast.Constant(value=PERSON_BATCH_SIZE),
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
        group_by=[_email_dedupe_group_expr()],
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
        limit=ast.Constant(value=PERSON_BATCH_SIZE),
    )
