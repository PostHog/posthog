"""How much Depot CI time each synced Depot source recorded, read from its raw job attempts.

The curated CI reads hide hand-off jobs and re-run copies, so they cannot add up to what Depot bills.
This read sums the raw source rows instead, one row per Depot source, and stands outside
``CuratedGitHubSource`` because it needs no GitHub tables.
"""

from typing import TYPE_CHECKING

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team import Team

from products.engineering_analytics.backend.facade.contracts import DepotCIRepoUsage
from products.engineering_analytics.backend.logic._shared import _parse_window
from products.engineering_analytics.backend.logic.cost import estimate_depot_ci_cost_usd
from products.engineering_analytics.backend.logic.sources import depot_job_attempts_by_repo

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl

_DEFAULT_WINDOW = "-7d"


def build_depot_ci_usage(
    *,
    team: Team,
    date_from: str | None = None,
    date_to: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> list[DepotCIRepoUsage]:
    window_from, window_to = _parse_window(team, date_from, date_to, default=_DEFAULT_WINDOW)
    usage: list[DepotCIRepoUsage] = []
    for repository, synced in depot_job_attempts_by_repo(team, user_access_control).items():
        sql = f"""
            SELECT count(), sum(dateDiff('millisecond', started_at, finished_at)) / 1000
            FROM (
                SELECT
                    parseDateTimeBestEffort(a.attempt_started_at) AS started_at,
                    parseDateTimeBestEffort(a.attempt_finished_at) AS finished_at
                FROM {synced.attempts.table} AS a
                WHERE lower(ifNull(a.repo, '')) = {{repository}}
                    AND ifNull(a.attempt_started_at, '') != ''
                    AND ifNull(a.attempt_finished_at, '') != ''
            )
            WHERE started_at >= {{window_from}} AND started_at < {{window_to}} AND finished_at >= started_at
        """
        placeholders: dict[str, ast.Expr] = {
            "repository": ast.Constant(value=synced.attempts.repository.lower()),
            "window_from": ast.Constant(value=window_from),
            "window_to": ast.Constant(value=window_to) if window_to else ast.Call(name="now", args=[]),
        }
        with tags_context(product=Product.ENGINEERING_ANALYTICS, feature=Feature.QUERY, team_id=team.pk):
            response = execute_hogql_query(
                query=parse_select(sql, placeholders=placeholders),
                team=team,
                query_type="engineering_analytics.depot_ci_usage",
                # Same two paths as ``CuratedGitHubSource.run``: the real user lets HogQL honor the per-table
                # warehouse ACL, and the userless caller must bypass it or fail closed on every such table.
                user=user_access_control.user if user_access_control is not None else None,
                user_access_control=user_access_control,
                bypass_warehouse_access_control=user_access_control is None,
            )
        attempts, elapsed_seconds = (response.results or [(0, 0)])[0]
        elapsed = float(elapsed_seconds or 0)
        usage.append(
            DepotCIRepoUsage(
                repo=repository,
                attempts=int(attempts or 0),
                elapsed_seconds=elapsed,
                estimated_cost_usd=estimate_depot_ci_cost_usd(elapsed),
                synced_at=synced.synced_at,
            )
        )
    return usage
