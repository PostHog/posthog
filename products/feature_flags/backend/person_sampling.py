from collections.abc import Callable
from typing import Optional

from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.models.filters import Filter
from posthog.models.team.team import Team
from posthog.schema_enums import PersonsArgMaxVersion

# 1-in-64 sample of the person keyspace. Sampling keys on person id (the dedup key), so every
# version row of a sampled person lands in the sample and the argMax dedup stays exact within it.
SAMPLE_MODULUS = 64

# Below this many sampled matches the extrapolation is too noisy, so rerun exact. The relative
# error of the estimate is about sqrt(63 / matched_persons), so 10,000 sampled matches
# (~640k matched persons) keeps the worst case near 3%.
#
# The threshold reads the match count, not the table size, so a large team whose condition
# matches few persons reruns exact. That rerun reads the whole table, but it does not rebuild
# the shape this sampling exists to avoid: the id prefilter holds the dedup to the matched
# candidate set, and count_settings adds in-order aggregation and a spill threshold. The cost
# is scan time instead of a memory-limit error.
# Caveat: the prefilter matches any historical row version, so a churny property (many persons
# matched once, few match now) can make the exact rerun carry a candidate set far larger than
# the current match count suggests.
MIN_SAMPLED_MATCHES = 10_000


def bounded_memory_settings() -> HogQLGlobalSettings:
    """
    Execution settings that keep person-dedup aggregations memory-bounded on large teams.

    The person table sorts by (team_id, id), so with in-order aggregation the dedup
    GROUP BY id streams instead of holding every person in a hash table. The spill
    threshold is the backstop for aggregations where in-order cannot apply (for
    example cohort subqueries): degrade to disk instead of a memory-limit error.
    """
    return HogQLGlobalSettings(
        # A partial result is worse than an error here: the counts get extrapolated and the
        # person pages get sent to, so a timed-out query must fail rather than come up short.
        # Left unset it inherits the cluster profile, which may accept partial results.
        timeout_overflow_mode="throw",
        optimize_aggregation_in_order=True,
        max_bytes_before_external_group_by=4 * 1024**3,
    )


def count_settings(sample_modulus: Optional[int]) -> HogQLGlobalSettings:
    # A sampled count keeps the fast parallel hash aggregation: the sample already bounds
    # the hash table, and in-order aggregation only makes it slower. The exact runs need
    # the streaming mode to stay memory-bounded on large teams. Both throw on timeout,
    # because the sampled count multiplies whatever it read by the modulus.
    if sample_modulus is not None:
        return HogQLGlobalSettings(
            timeout_overflow_mode="throw",
            max_bytes_before_external_group_by=4 * 1024**3,
        )
    return bounded_memory_settings()


def sampled_or_exact_count(run_count: Callable[[Optional[int]], int]) -> int:
    """
    Count from a 1-in-SAMPLE_MODULUS sample and extrapolate, or exactly when the sample holds
    too few matches for a stable extrapolation.

    `run_count` takes the sample modulus, or None for an exact run.
    """
    sampled = run_count(SAMPLE_MODULUS)
    if sampled >= MIN_SAMPLED_MATCHES:
        return sampled * SAMPLE_MODULUS
    return run_count(None)


def count_matching_persons(team: Team, filter: Optional[Filter], database: Database, query_type: str) -> int:
    """Count the persons a filter matches, or every person on the team when filter is None."""
    return sampled_or_exact_count(
        lambda sample_modulus: _run_person_count(team, filter, database, query_type, sample_modulus)
    )


def _run_person_count(
    team: Team, filter: Optional[Filter], database: Database, query_type: str, sample_modulus: Optional[int]
) -> int:
    query = build_person_count_query(team, filter, sample_modulus=sample_modulus)
    response = execute_hogql_query(
        query=query,
        team=team,
        query_type=query_type,
        # Pin v1 for the unfiltered count, as count_persons_seen_so_far does: the v2 persons
        # path pushes the executor's default LIMIT into its dedup subquery, which caps a bare
        # count() at ~101 for teams pinned to v2 (see #87323). The team_id condition already
        # sends these queries down the persons table's prefilter path, which emits the v1 dedup
        # whatever this says, so the pin is only load-bearing if that path is ever lost. A
        # filtered count reads person properties, where v2 is the faster shape, so it keeps the
        # automatic choice.
        modifiers=HogQLQueryModifiers(personsArgMaxVersion=PersonsArgMaxVersion.V1) if filter is None else None,
        context=HogQLContext(team_id=team.pk, database=database),
        settings=count_settings(sample_modulus),
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
        where_exprs.append(person_sample_predicate(sample_modulus))
    if filter is not None:
        where_exprs.append(property_to_expr(filter.property_groups, team, scope="person"))

    # A filter can add a one-to-many join: a `distinct_id` person property resolves through
    # persons.pdi, which gives a person one row per distinct id. So a filtered count dedups on
    # the person id. The unfiltered total joins nothing, so it keeps the plain count() and
    # avoids a uniqExact state over every person on the team.
    if filter is None:
        count_expr: ast.Expr = ast.Call(name="count", args=[])
    else:
        count_expr = ast.Call(name="count", distinct=True, args=[ast.Field(chain=["persons", "id"])])

    return ast.SelectQuery(
        select=[count_expr],
        select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
        where=ast.And(exprs=where_exprs),
    )


def person_sample_predicate(modulus: int) -> ast.Expr:
    # Built as modulo(...) calls, not the % operator: WhereClauseExtractor fails safe to
    # "no prefilter" on ArithmeticOperation nodes, and the memory bound depends on this
    # predicate reaching the raw person scan inside the persons lazy table.
    return sample_predicate(ast.Field(chain=["persons", "id"]), modulus)


def sample_predicate(key: ast.Expr, modulus: int) -> ast.Expr:
    """Keep 1 in `modulus` of the values `key` takes, spread evenly by a hash of the key."""
    return ast.CompareOperation(
        op=ast.CompareOperationOp.Eq,
        left=ast.Call(
            name="modulo",
            args=[
                ast.Call(name="cityHash64", args=[key]),
                ast.Constant(value=modulus),
            ],
        ),
        right=ast.Constant(value=0),
    )
