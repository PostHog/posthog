from collections.abc import Callable
from typing import Optional

import posthoganalytics

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.cdp.flag_gated_templates import gated_template_enabled
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models.property import PropertyGroup
from posthog.models.team.team import Team

from products.feature_flags.backend import person_sampling
from products.feature_flags.backend.person_sampling import count_matching_persons, count_settings, sample_predicate
from products.feature_flags.backend.user_blast_radius import (
    BlastRadiusResult,
    replace_proxy_properties,
    sampled_person_blast_radius,
    unevaluable_filters_as_validation_errors,
)
from products.workflows.backend.services.batch_audience import (
    EMAIL_DEDUPE_KEY,
    SUPPORTED_DEDUPE_KEYS,
    DedupeAudienceCount,
    DedupeAudienceSize,
    dedupe_audience_count_from_row,
    email_dedupe_group_expr,
    email_missing_expr,
)

AUDIENCE_QUERY_V2_FLAG = "workflows-audience-query-v2"

QUERY_TYPE = "workflows_audience_count_v2"

# Below this many sampled people without an email, count them exactly instead of extrapolating.
# The extrapolation's relative error is about 1/sqrt(sampled), so 1,000 keeps it near 3%. The
# exact count dedups only those people, so it stays below ~64k of them.
MIN_SAMPLED_WITHOUT_EMAIL = 1_000


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


def get_dedupe_audience_count_v2(team: Team, filters: dict, dedupe_key: str) -> DedupeAudienceSize:
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
        include_without_email = gated_template_enabled("workflows-missing-email-warning", team)
        count = _sampled_or_exact_dedupe_count(
            lambda sample_modulus: _run_dedupe_count(
                team, cleaned_filter, database, sample_modulus, include_without_email=include_without_email
            ),
            lambda: _run_without_email_count(team, cleaned_filter, database),
        )
        return DedupeAudienceSize.capped_at_total(count, total)


def _sampled_or_exact_dedupe_count(
    run_count: Callable[[Optional[int]], DedupeAudienceCount],
    count_without_email: Callable[[], int],
) -> DedupeAudienceCount:
    # Mirrors person_sampling.sampled_or_exact_count for a pair of counts from one query. The
    # sample keys on the dedupe group, so both counts scale by the same modulus. A large audience
    # can have few people without an email, and a handful of sampled ones misses or overstates them.
    sample = run_count(person_sampling.SAMPLE_MODULUS)
    if sample.sends < person_sampling.MIN_SAMPLED_MATCHES:
        return run_count(None)
    sends = sample.sends * person_sampling.SAMPLE_MODULUS
    if sample.without_email is None:
        return DedupeAudienceCount(sends=sends, without_email=None)
    if sample.without_email < MIN_SAMPLED_WITHOUT_EMAIL:
        return DedupeAudienceCount(sends=sends, without_email=count_without_email())
    return DedupeAudienceCount(sends=sends, without_email=sample.without_email * person_sampling.SAMPLE_MODULUS)


def _run_dedupe_count(
    team: Team,
    prop_group: PropertyGroup,
    database: Database,
    sample_modulus: Optional[int],
    *,
    include_without_email: bool,
) -> DedupeAudienceCount:
    query = build_dedupe_count_query(
        team, prop_group, sample_modulus=sample_modulus, include_without_email=include_without_email
    )
    response = execute_hogql_query(
        query=query,
        team=team,
        query_type=QUERY_TYPE,
        context=HogQLContext(team_id=team.pk, database=database),
        settings=count_settings(sample_modulus),
    )
    return dedupe_audience_count_from_row(response.results[0] if response.results else None)


def _run_without_email_count(team: Team, prop_group: PropertyGroup, database: Database) -> int:
    response = execute_hogql_query(
        query=build_without_email_count_query(team, prop_group),
        team=team,
        query_type=QUERY_TYPE,
        context=HogQLContext(team_id=team.pk, database=database),
        settings=count_settings(None),
    )
    return response.results[0][0] if response.results else 0


def build_without_email_count_query(team: Team, prop_group: PropertyGroup) -> ast.SelectQuery:
    # The missing-email predicate reaches the person prefilter, so the dedup holds only the
    # people without an email. That keeps this exact count cheap when they are few.
    return ast.SelectQuery(
        select=[ast.Call(name="count", distinct=True, args=[ast.Field(chain=["persons", "id"])])],
        select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
        where=ast.And(exprs=[*_audience_where_exprs(team, prop_group), email_missing_expr()]),
    )


def build_dedupe_count_query(
    team: Team, prop_group: PropertyGroup, sample_modulus: Optional[int], *, include_without_email: bool = True
) -> ast.SelectQuery:
    where_exprs = _audience_where_exprs(team, prop_group)
    if sample_modulus is not None:
        # A fresh group expr per use: the resolver annotates AST nodes in place, so the
        # WHERE and SELECT must not share one instance.
        where_exprs.append(sample_predicate(email_dedupe_group_expr(), sample_modulus))

    select = [ast.Call(name="count", distinct=True, args=[email_dedupe_group_expr()])]
    if include_without_email:
        select.append(ast.Call(name="countIf", args=[email_missing_expr()]))
    return ast.SelectQuery(
        select=select,
        select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
        where=ast.And(exprs=where_exprs),
    )


def _audience_where_exprs(team: Team, prop_group: PropertyGroup) -> list[ast.Expr]:
    where_exprs: list[ast.Expr] = [
        ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["persons", "team_id"]),
            right=ast.Constant(value=team.pk),
        )
    ]
    if len(prop_group.flat) > 0:
        where_exprs.append(property_to_expr(prop_group, team, scope="person"))
    return where_exprs
