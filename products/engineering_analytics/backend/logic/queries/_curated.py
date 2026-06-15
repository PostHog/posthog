"""Shared helpers for the curated query modules.

The ``pull_requests`` / ``workflow_runs`` builders return a curated ``SELECT``
over a team's GitHub warehouse tables, whose real names are resolved per-team by
``logic.sources`` and passed in. Query modules embed those as parenthesised
subqueries (``FROM {pr_source(table)} AS pr``) and run them with ``run_query`` — the
product reads its data privately rather than registering a global HogQL view, keeping
it off the per-query catalog hot path.

Every fragment here is built from trusted constants and validated warehouse
identifiers. User-supplied values must always flow through ``ast.Constant``
placeholders in the calling query, never be string-substituted into these fragments.
"""

from posthog.schema import HogQLQueryResponse

from posthog.hogql import ast
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team import Team

from products.engineering_analytics.backend.facade.contracts import GitHubSourceNotConnectedError
from products.engineering_analytics.backend.logic.sources import GitHubTables
from products.engineering_analytics.backend.logic.views import pull_requests, workflow_runs


def pr_source(table_name: str) -> str:
    """Curated pull-requests ``SELECT`` over ``table_name``, parenthesised for use as a subquery."""
    return f"({pull_requests.build_query(table_name)})"


def run_source(table_name: str) -> str:
    """Curated workflow-runs ``SELECT`` over ``table_name``, parenthesised for use as a subquery."""
    return f"({workflow_runs.build_query(table_name)})"


def ci_rollup_cte(run_table: str) -> str:
    """CTE collapsing each head SHA's workflow runs into pass/fail/pending counts.

    Takes the latest run per ``(head_sha, workflow_name)`` via ``argMax`` (a PR's
    CI status is its newest run per workflow), then aggregates per SHA. The join
    target for the cards and pull-request-list queries; ``head_sha`` is the only
    link between a PR and its CI.
    """
    return f"""
        ci_rollup AS (
            SELECT
                head_sha,
                count() AS runs,
                countIf(s = 'completed' AND c = 'success') AS passing,
                countIf(s = 'completed' AND c IN ('failure', 'timed_out')) AS failing,
                countIf(s != 'completed') AS pending
            FROM (
                SELECT
                    head_sha,
                    workflow_name,
                    argMax(status, run_started_at) AS s,
                    argMax(conclusion, run_started_at) AS c
                FROM {run_source(run_table)} AS r
                GROUP BY head_sha, workflow_name
            )
            GROUP BY head_sha
        )
    """


def run_query(
    sql: str,
    *,
    team: Team,
    query_type: str,
    tables: GitHubTables,
    placeholders: dict[str, ast.Expr] | None = None,
) -> HogQLQueryResponse:
    """Parse + execute a curated HogQL query.

    ``tables`` are the per-team table names already resolved by ``logic.sources`` and
    embedded in ``sql``. The no-source case is detected up front by the resolver, but a
    ``Unknown table`` for one of those resolved names is kept as a backstop — it means the
    source vanished between resolve and execute — and is turned into
    ``GitHubSourceNotConnectedError`` so the presentation layer returns a clear 4xx. Any
    other query error is a real bug and propagates unchanged.
    """
    try:
        with tags_context(product=Product.ENGINEERING_ANALYTICS, feature=Feature.QUERY, team_id=team.pk):
            return execute_hogql_query(
                query=parse_select(sql, placeholders=placeholders),
                team=team,
                query_type=query_type,
            )
    except QueryError as err:
        message = str(err)
        # HogQL raises ``Unknown table `<name>`.`` for any table missing from the catalog.
        # Only the absence of one of THIS request's resolved source tables means "no GitHub
        # source"; any other unknown table is a real bug (e.g. a typo in a curated builder)
        # and must surface unchanged rather than masquerade as a missing-source 4xx.
        if any(f"Unknown table `{name}`" in message for name in (tables.pull_requests, tables.workflow_runs)):
            raise GitHubSourceNotConnectedError() from err
        raise
