from typing import Optional

import posthoganalytics

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models.filters import Filter
from posthog.models.team.team import Team

from products.feature_flags.backend.person_sampling import (
    count_matching_persons,
    count_settings,
    sample_predicate,
    sampled_or_exact_count,
)
from products.feature_flags.backend.user_blast_radius import (
    BlastRadiusResult,
    replace_proxy_properties,
    sampled_person_blast_radius,
    unevaluable_filters_as_validation_errors,
)
from products.workflows.backend.services.batch_audience import (
    EMAIL_DEDUPE_KEY,
    SUPPORTED_DEDUPE_KEYS,
    email_dedupe_group_expr,
)

AUDIENCE_QUERY_V2_FLAG = "workflows-audience-query-v2"

QUERY_TYPE = "workflows_audience_count_v2"


def use_audience_query_v2(team: Team) -> bool:
    return bool(
        posthoganalytics.feature_enabled(
            AUDIENCE_QUERY_V2_FLAG,
            str(team.uuid),
            send_feature_flag_events=False,
        )
    )


def get_person_audience_count_v2(team: Team, filters: dict) -> BlastRadiusResult:
    """
    Person-audience blast radius sized from a sample of the person keyspace.

    Counts run on a sample of the persons and extrapolate, so cost is bounded on teams
    where the exact dedup count exceeds the query memory limit.
    """
    with unevaluable_filters_as_validation_errors():
        cleaned_filter = replace_proxy_properties(team, filters)

        tag_queries(product=Product.WORKFLOWS, feature=Feature.QUERY)
        return sampled_person_blast_radius(team, cleaned_filter, query_type=QUERY_TYPE)


def get_dedupe_audience_count_v2(team: Team, filters: dict, dedupe_key: str) -> BlastRadiusResult:
    """
    Send count for a dedupe-enabled batch workflow, sized from a sample of the dedupe groups.

    Sampling keys on the dedupe group (the normalized email, or the person id when there is
    no email), not on the person: a group with several persons would otherwise be that many
    times more likely to land in the sample, and the estimate would drift back toward a
    person count. Hashing the group gives every group the same chance.
    """
    # Defence-in-depth mirror of get_batch_audience_count: a new supported key must be
    # taught to this function too, instead of silently getting the email grouping.
    if dedupe_key != EMAIL_DEDUPE_KEY:
        raise ValueError(f"Unsupported dedupe_key: {dedupe_key!r} (supported: {SUPPORTED_DEDUPE_KEYS})")

    with unevaluable_filters_as_validation_errors():
        cleaned_filter = replace_proxy_properties(team, filters)

        tag_queries(product=Product.WORKFLOWS, feature=Feature.QUERY)
        database = Database.create_for(team=team)

        total = count_matching_persons(team, None, database, query_type=QUERY_TYPE)
        affected = sampled_or_exact_count(
            lambda sample_modulus: _run_dedupe_count(team, cleaned_filter, database, sample_modulus)
        )
        return BlastRadiusResult(affected=min(affected, total), total=total)


def _run_dedupe_count(team: Team, filter: Filter, database: Database, sample_modulus: Optional[int]) -> int:
    query = build_dedupe_count_query(team, filter, sample_modulus=sample_modulus)
    response = execute_hogql_query(
        query=query,
        team=team,
        query_type=QUERY_TYPE,
        context=HogQLContext(team_id=team.pk, database=database),
        settings=count_settings(sample_modulus),
    )
    return response.results[0][0] if response.results else 0


def build_dedupe_count_query(team: Team, filter: Filter, sample_modulus: Optional[int]) -> ast.SelectQuery:
    where_exprs: list[ast.Expr] = [
        ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["persons", "team_id"]),
            right=ast.Constant(value=team.pk),
        )
    ]
    if sample_modulus is not None:
        # A fresh group expr per use: the resolver annotates AST nodes in place, so the
        # WHERE and SELECT must not share one instance.
        where_exprs.append(sample_predicate(email_dedupe_group_expr(), sample_modulus))
    if len(filter.property_groups.flat) > 0:
        where_exprs.append(property_to_expr(filter.property_groups, team, scope="person"))

    return ast.SelectQuery(
        select=[ast.Call(name="count", distinct=True, args=[email_dedupe_group_expr()])],
        select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
        where=ast.And(exprs=where_exprs),
    )
