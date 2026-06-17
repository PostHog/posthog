"""The curated read layer over a team's GitHub warehouse tables.

``CuratedGitHubSource`` binds one team to its resolved ``pull_requests`` / ``workflow_runs``
table names (see ``logic.sources``) and is the single object the query modules use: it hands
out the curated ``SELECT`` subqueries and the CI rollup CTE, and runs the assembled HogQL.
The resolved table names live inside it, so the query layer never threads or re-derives them.
The product reads its data privately this way — nothing is registered as a global HogQL view,
keeping it off the per-query catalog hot path.

Every SQL fragment is built from trusted constants and the resolved table identifiers (which
the resolver has validated to ``[A-Za-z_][A-Za-z0-9_]*``). User-supplied values must always
flow through ``ast.Constant`` placeholders in the calling query, never be string-substituted
into these fragments.
"""

from typing import TYPE_CHECKING

from posthog.schema import HogQLQueryResponse

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team import Team

from products.engineering_analytics.backend.logic.sources import GitHubTables, resolve_github_tables
from products.engineering_analytics.backend.logic.views import pull_requests, workflow_runs

if TYPE_CHECKING:
    from posthog.rbac.user_access_control import UserAccessControl


class CuratedGitHubSource:
    """A team's curated GitHub read layer, bound to its resolved warehouse tables.

    Construct once per request with ``for_team`` — it resolves the table names and raises
    ``GitHubSourceNotConnectedError`` when the team has no connected GitHub source, so the
    "is a source connected" decision lives in exactly one place (the resolver). The query
    modules then ask the returned instance for the curated subqueries and run HogQL through it.
    """

    def __init__(self, *, team: Team, tables: GitHubTables) -> None:
        self._team = team
        self._tables = tables

    @property
    def team(self) -> Team:
        """The team this handle reads for — query builders need it for timezone-aware date parsing."""
        return self._team

    @classmethod
    def for_team(
        cls, team: Team, *, source_id: str | None = None, user_access_control: "UserAccessControl | None" = None
    ) -> "CuratedGitHubSource":
        return cls(
            team=team,
            tables=resolve_github_tables(team=team, source_id=source_id, user_access_control=user_access_control),
        )

    def pr_source(self) -> str:
        """Curated pull-requests ``SELECT``, parenthesised for use as a subquery."""
        return f"({pull_requests.build_query(self._tables.pull_requests)})"

    def run_source(self) -> str:
        """Curated workflow-runs ``SELECT``, parenthesised for use as a subquery."""
        return f"({workflow_runs.build_query(self._tables.workflow_runs)})"

    def ci_rollup_cte(self) -> str:
        """CTE collapsing each head SHA's workflow runs into pass/fail/pending counts.

        Takes the latest run per ``(head_sha, workflow_name)`` via ``argMax`` (a PR's CI status
        is its newest run per workflow), then aggregates per SHA. The join target for the cards
        and pull-request-list queries; ``head_sha`` is the only link between a PR and its CI.
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
                    FROM {self.run_source()} AS r
                    GROUP BY head_sha, workflow_name
                )
                GROUP BY head_sha
            )
        """

    def pr_rollup_query(self, select: str) -> str:
        """Compose a pull-requests query that reads ``FROM __PR_SOURCE__ AS pr LEFT JOIN ci_rollup``.

        Prefixes ``select`` with the CI rollup CTE and fills its ``__PR_SOURCE__`` placeholder
        with the curated pull-requests source — the two steps the cards and PR-list queries always
        do together.
        """
        return f"WITH {self.ci_rollup_cte()} {select}".replace("__PR_SOURCE__", self.pr_source())

    def run(
        self,
        sql: str,
        *,
        query_type: str,
        placeholders: dict[str, ast.Expr] | None = None,
    ) -> HogQLQueryResponse:
        """Parse + execute a curated HogQL query for this team."""
        with tags_context(product=Product.ENGINEERING_ANALYTICS, feature=Feature.QUERY, team_id=self._team.pk):
            return execute_hogql_query(
                query=parse_select(sql, placeholders=placeholders),
                team=self._team,
                query_type=query_type,
            )
