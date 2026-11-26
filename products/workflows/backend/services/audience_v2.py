from typing import Optional
from uuid import UUID

from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.models.property import PropertyGroup
from posthog.models.team.team import Team
from posthog.schema_enums import PersonsArgMaxVersion

from products.feature_flags.backend.person_sampling import (
    MIN_SAMPLED_MATCHES,
    SAMPLE_MODULUS,
    build_person_count_query,
    count_matching_persons,
    count_settings,
    read_person_count,
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
from products.workflows.backend.services.batch_audience_cohorts import reject_excluded_cohort_without_members
from products.workflows.backend.services.batch_audience_test_accounts import with_person_test_account_filters

QUERY_TYPE = "workflows_audience_count_v2"

# ClickHouse orders UUIDs by their last 8 bytes first, and those bytes are random in every person id
# format ingestion writes (UUIDv4, v5, v7 and UUIDT). So a slice of that half of the keyspace is a random
# sample of the persons, and the (team_id, id) sort key reads only the granules inside it, where a hash
# sample still reads the whole team. Several slices instead of one keep the sample spread out when a
# team's ids are not random there. The measured share of rows in the slices sets the scale either way.
SAMPLE_RANGES = 16
_HALF_KEYSPACE = 2**64


def get_person_audience_count_v2(team: Team, filters: dict) -> BlastRadiusResult:
    """
    Person-audience blast radius sized from a sample of the person keyspace.

    Counts run on a sample of the persons and extrapolate, so cost is bounded on teams
    where the exact dedup count exceeds the query memory limit.
    """
    with unevaluable_filters_as_validation_errors():
        cleaned_filter = replace_proxy_properties(team, with_person_test_account_filters(team, filters))
        reject_excluded_cohort_without_members(team.project_id, cleaned_filter)

        tag_queries(product=Product.WORKFLOWS, feature=Feature.QUERY)
        if any(prop.type == "flag" for prop in cleaned_filter.flat):
            # Flag dependencies weight each person, which only the flags sampling path supports.
            return sampled_person_blast_radius(team, cleaned_filter, query_type=QUERY_TYPE)
        return _range_sampled_person_audience(team, cleaned_filter)


def get_dedupe_audience_count_v2(team: Team, filters: dict, dedupe_key: str) -> BlastRadiusResult:
    """
    Send count for a dedupe-enabled batch workflow, sized from a sample of the dedupe groups.

    Sampling keys on the dedupe group (the normalized email, or the person id when there is
    no email), not on the person: a group with several persons would otherwise be that many
    times more likely to land in the sample, and the estimate would drift back toward a
    person count. Hashing the group gives every group the same chance.
    """
    # Defence-in-depth against a new dedupe key slipping past the endpoint's allowlist: a new
    # supported key must be taught to this function too, instead of silently getting the email grouping.
    if dedupe_key != EMAIL_DEDUPE_KEY:
        raise ValueError(f"Unsupported dedupe_key: {dedupe_key!r} (supported: {SUPPORTED_DEDUPE_KEYS})")

    with unevaluable_filters_as_validation_errors():
        cleaned_filter = replace_proxy_properties(team, with_person_test_account_filters(team, filters))
        reject_excluded_cohort_without_members(team.project_id, cleaned_filter)

        tag_queries(product=Product.WORKFLOWS, feature=Feature.QUERY)
        database = Database.create_for(team=team)

        total = _sampled_or_exact_person_count(team, None, database, _measure_sample_share(team, database))
        # The groups keep the hash sample, because id slices sample persons and not groups.
        affected = sampled_or_exact_count(
            lambda sample_modulus: _run_dedupe_count(team, cleaned_filter, database, sample_modulus)
        )
        return BlastRadiusResult(affected=min(affected, total), total=total)


def _run_dedupe_count(team: Team, prop_group: PropertyGroup, database: Database, sample_modulus: Optional[int]) -> int:
    query = build_dedupe_count_query(team, prop_group, sample_modulus=sample_modulus)
    response = execute_hogql_query(
        query=query,
        team=team,
        query_type=QUERY_TYPE,
        context=HogQLContext(team_id=team.pk, database=database),
        settings=count_settings(sample_modulus),
    )
    # uniqCombined over a nullable expression returns NULL rather than 0 when no person matches.
    return (response.results[0][0] if response.results else None) or 0


def build_dedupe_count_query(team: Team, prop_group: PropertyGroup, sample_modulus: Optional[int]) -> ast.SelectQuery:
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
    if len(prop_group.flat) > 0:
        where_exprs.append(property_to_expr(prop_group, team, scope="person"))

    return ast.SelectQuery(
        select=[ast.Call(name="count", distinct=True, args=[email_dedupe_group_expr()])],
        select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
        where=ast.And(exprs=where_exprs),
    )


@frozen
class _SampleShare:
    rows: int
    sampled_rows: int

    @property
    def can_extrapolate(self) -> bool:
        # With random ids, the slices hold 1 in SAMPLE_MODULUS rows to within a few percent once they
        # hold MIN_SAMPLED_MATCHES rows. A share far from that means the team's ids are not random in
        # the half the slices cut, and the slices would overweight whichever ids crowd into them.
        expected = self.rows / SAMPLE_MODULUS
        return self.sampled_rows >= MIN_SAMPLED_MATCHES and expected / 2 <= self.sampled_rows <= expected * 2


def _range_sampled_person_audience(team: Team, prop_group: PropertyGroup) -> BlastRadiusResult:
    database = Database.create_for(team=team)
    share = _measure_sample_share(team, database)

    total = _sampled_or_exact_person_count(team, None, database, share)
    if len(prop_group.flat) == 0:
        return BlastRadiusResult(affected=total, total=total)
    affected = _sampled_or_exact_person_count(team, prop_group, database, share)
    return BlastRadiusResult(affected=min(affected, total), total=total)


def _measure_sample_share(team: Team, database: Database) -> _SampleShare:
    """
    Count the team's raw person rows, and the rows inside the sampled id slices.

    The share of rows stands in for the share of persons, because all version rows of a person share
    its id and land in a slice together. Counting rows needs no dedup, so the total reads only the sort
    key and the sampled count reads only the granules inside the slices.
    """
    query = parse_select(
        "SELECT (SELECT count() FROM raw_persons), (SELECT count() FROM raw_persons WHERE {sample})",
        placeholders={"sample": id_range_sample_predicate(["raw_persons", "id"])},
    )
    response = execute_hogql_query(
        query=query,
        team=team,
        query_type=QUERY_TYPE,
        context=HogQLContext(team_id=team.pk, database=database),
        settings=count_settings(SAMPLE_MODULUS),
    )
    rows, sampled_rows = response.results[0] if response.results else (0, 0)
    return _SampleShare(rows=rows, sampled_rows=sampled_rows)


def _sampled_or_exact_person_count(
    team: Team, prop_group: Optional[PropertyGroup], database: Database, share: _SampleShare
) -> int:
    """
    Count the persons in the id slices and scale by the measured share of rows, or count exactly when
    the slices hold too few matches for a stable extrapolation.

    A team whose slices can't stand for it (too few rows, or ids that are not random) keeps the hash
    sample, which reads the whole team but samples any id format evenly.
    """
    if not share.can_extrapolate:
        return count_matching_persons(team, prop_group, database, query_type=QUERY_TYPE)
    matched = _run_person_count(team, prop_group, database, sampled=True)
    if matched >= MIN_SAMPLED_MATCHES:
        return int(round(matched * share.rows / share.sampled_rows))
    return _run_person_count(team, prop_group, database, sampled=False)


def _run_person_count(team: Team, prop_group: Optional[PropertyGroup], database: Database, sampled: bool) -> int:
    query = build_person_count_query(team, prop_group, sample_modulus=None)
    if sampled and query.where is not None:
        query.where = ast.And(exprs=[query.where, id_range_sample_predicate(["persons", "id"])])
    response = execute_hogql_query(
        query=query,
        team=team,
        query_type=QUERY_TYPE,
        # Same v1 pin as count_matching_persons, because the v2 dedup caps a bare count() at the default LIMIT.
        modifiers=HogQLQueryModifiers(personsArgMaxVersion=PersonsArgMaxVersion.V1) if prop_group is None else None,
        context=HogQLContext(team_id=team.pk, database=database),
        settings=count_settings(SAMPLE_MODULUS if sampled else None),
    )
    return read_person_count(response.results, weighted=False)[0]


def id_range_sample_predicate(id_chain: list[str | int]) -> ast.Expr:
    """
    Keep the ids in SAMPLE_RANGES evenly spaced slices of ClickHouse's UUID order, which together
    cover 1 in SAMPLE_MODULUS of the keyspace.

    Plain comparisons against constants, so that WhereClauseExtractor pushes the predicate into the
    raw person scan inside the persons lazy table, where ClickHouse uses it as a primary key condition.
    """
    stride = _HALF_KEYSPACE // SAMPLE_RANGES
    width = stride // SAMPLE_MODULUS
    slices: list[ast.Expr] = []
    for start in range(0, _HALF_KEYSPACE, stride):
        bounds: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=id_chain),
                right=ast.Constant(value=UUID(int=start)),
            )
        ]
        # In ClickHouse's order, UUID(int=x) is the lowest UUID whose last 8 bytes are x, until x
        # overflows into the first 8 bytes. A slice that reaches the end of the keyspace has no upper bound.
        if start + width < _HALF_KEYSPACE:
            bounds.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Lt,
                    left=ast.Field(chain=id_chain),
                    right=ast.Constant(value=UUID(int=start + width)),
                )
            )
        slices.append(ast.And(exprs=bounds) if len(bounds) > 1 else bounds[0])
    return ast.Or(exprs=slices)
