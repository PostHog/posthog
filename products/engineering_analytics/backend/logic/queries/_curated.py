"""Shared helpers for the curated query modules.

The ``pull_requests`` / ``workflow_runs`` builders return a curated ``SELECT``
over the raw ``github_*`` warehouse tables. Query modules embed those as
parenthesised subqueries (``FROM {pr_source()} AS pr``) and run them with
``run_query`` — the product reads its data privately rather than registering a
global HogQL view, keeping it off the per-query catalog hot path.

Every fragment here is built from trusted constants. User-supplied values must
always flow through ``ast.Constant`` placeholders in the calling query, never be
string-substituted into these fragments.
"""

from posthog.schema import HogQLQueryResponse

from posthog.hogql import ast
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models.team import Team

from products.engineering_analytics.backend.facade.contracts import GitHubSourceNotConnectedError
from products.engineering_analytics.backend.logic.views import pull_requests, workflow_runs

# The curated builders are the only place a warehouse table is named; reuse their
# constants so "which tables mean a GitHub source is connected" is defined once.
_SOURCE_TABLES = (pull_requests.SOURCE_TABLE, workflow_runs.SOURCE_TABLE)


def pr_source() -> str:
    """Curated pull-requests ``SELECT``, parenthesised for use as a subquery."""
    return f"({pull_requests.build_query()})"


def run_source() -> str:
    """Curated workflow-runs ``SELECT``, parenthesised for use as a subquery."""
    return f"({workflow_runs.build_query()})"


def ci_rollup_cte() -> str:
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
                FROM {run_source()} AS r
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
    placeholders: dict[str, ast.Expr] | None = None,
) -> HogQLQueryResponse:
    """Parse + execute a curated HogQL query.

    Raises ``GitHubSourceNotConnectedError`` when the team has no GitHub warehouse
    source: the curated subqueries reference the ``github_*`` tables, which aren't in
    the catalog, so the resolver raises ``Unknown table``. The presentation layer
    turns that into a clear 4xx. Any other query error is a real bug and propagates.
    """
    try:
        return execute_hogql_query(
            query=parse_select(sql, placeholders=placeholders),
            team=team,
            query_type=query_type,
        )
    except QueryError as err:
        message = str(err)
        # HogQL raises ``Unknown table `<name>`.`` for any table missing from the
        # catalog. Only the absence of OUR source tables means "no GitHub source";
        # any other unknown table is a real bug (e.g. a typo in a curated builder)
        # and must surface unchanged rather than masquerade as a missing-source 4xx.
        if any(f"Unknown table `{table}`" in message for table in _SOURCE_TABLES):
            raise GitHubSourceNotConnectedError() from err
        raise
