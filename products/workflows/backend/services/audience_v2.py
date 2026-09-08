from typing import Optional

import posthoganalytics

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models.filters import Filter
from posthog.models.team.team import Team

from products.feature_flags.backend.user_blast_radius import (
    BlastRadiusResult,
    replace_proxy_properties,
    unevaluable_filters_as_validation_errors,
)

AUDIENCE_QUERY_V2_FLAG = "workflows-audience-query-v2"

# 1-in-64 sample of the person keyspace. Sampling keys on person id (the dedup key), so every
# version row of a sampled person lands in the sample and the argMax dedup stays exact within it.
SAMPLE_MODULUS = 64

# Below this many sampled matches the extrapolation is too noisy, so rerun exact. The relative
# error of the estimate is about sqrt(63 / matched_persons), so 10,000 sampled matches
# (~640k matched persons) keeps the worst case near 3%. The exact query is cheap in that
# regime: few matching persons means the id prefilter keeps the dedup aggregation small.
MIN_SAMPLED_MATCHES = 10_000


def use_audience_query_v2(team: Team) -> bool:
    return bool(
        posthoganalytics.feature_enabled(
            AUDIENCE_QUERY_V2_FLAG,
            str(team.uuid),
            send_feature_flag_events=False,
        )
    )


def bounded_memory_settings() -> HogQLGlobalSettings:
    """
    Execution settings that keep person-dedup aggregations memory-bounded on large teams.

    The person table sorts by (team_id, id), so with in-order aggregation the dedup
    GROUP BY id streams instead of holding every person in a hash table. The spill
    threshold is the backstop for aggregations where in-order cannot apply (for
    example cohort subqueries): degrade to disk instead of a memory-limit error.
    """
    return HogQLGlobalSettings(
        optimize_aggregation_in_order=True,
        max_bytes_before_external_group_by=4 * 1024**3,
    )


def get_person_audience_count_v2(team: Team, filters: dict) -> BlastRadiusResult:
    """
    Person-audience blast radius sized from a sample of the person keyspace.

    Counts run on 1 in SAMPLE_MODULUS persons and extrapolate, so cost is bounded on
    teams where the exact dedup count exceeds the query memory limit. When a sample
    holds too few matches for a stable extrapolation, the exact count runs instead.
    """
    with unevaluable_filters_as_validation_errors():
        cleaned_filter = replace_proxy_properties(team, filters)

        tag_queries(product=Product.WORKFLOWS, feature=Feature.QUERY)
        # One database build shared by all counts below; each execute_hogql_query call
        # would otherwise rebuild it, and the build cost scales with warehouse size.
        database = Database.create_for(team=team)

        total = _count_matching_persons(team, None, database)
        if len(cleaned_filter.property_groups.flat) == 0:
            return BlastRadiusResult(affected=total, total=total)

        affected = _count_matching_persons(team, cleaned_filter, database)
        return BlastRadiusResult(affected=min(affected, total), total=total)


def _count_matching_persons(team: Team, filter: Optional[Filter], database: Database) -> int:
    sampled = _run_person_count(team, filter, database, sample_modulus=SAMPLE_MODULUS)
    if sampled >= MIN_SAMPLED_MATCHES:
        return sampled * SAMPLE_MODULUS
    return _run_person_count(team, filter, database, sample_modulus=None)


def _run_person_count(team: Team, filter: Optional[Filter], database: Database, sample_modulus: Optional[int]) -> int:
    query = build_person_count_query(team, filter, sample_modulus=sample_modulus)
    response = execute_hogql_query(
        query=query,
        team=team,
        query_type="workflows_audience_count_v2",
        context=HogQLContext(team_id=team.pk, database=database),
        settings=bounded_memory_settings(),
    )
    return response.results[0][0] if response.results else 0


def build_person_count_query(team: Team, filter: Optional[Filter], sample_modulus: Optional[int]) -> ast.SelectQuery:
    where_exprs: list[ast.Expr] = [
        ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["persons", "team_id"]),
            right=ast.Constant(value=team.pk),
        )
    ]
    if sample_modulus is not None:
        where_exprs.append(_sample_predicate(sample_modulus))
    if filter is not None:
        where_exprs.append(property_to_expr(filter.property_groups, team, scope="person"))

    # Plain count(): the persons table is already one row per person after dedup,
    # so count(DISTINCT id) would only add a uniqExact state over every matched id.
    return ast.SelectQuery(
        select=[ast.Call(name="count", args=[])],
        select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
        where=ast.And(exprs=where_exprs),
    )


def _sample_predicate(modulus: int) -> ast.Expr:
    # Built as modulo(...) calls, not the % operator: WhereClauseExtractor fails safe to
    # "no prefilter" on ArithmeticOperation nodes, and the memory bound depends on this
    # predicate reaching the raw person scan inside the persons lazy table.
    return ast.CompareOperation(
        op=ast.CompareOperationOp.Eq,
        left=ast.Call(
            name="modulo",
            args=[
                ast.Call(name="cityHash64", args=[ast.Field(chain=["persons", "id"])]),
                ast.Constant(value=modulus),
            ],
        ),
        right=ast.Constant(value=0),
    )
