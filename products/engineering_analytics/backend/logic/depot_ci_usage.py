"""Depot CI run time and cost per synced Depot source. It needs no GitHub tables, so it reads outside
``CuratedGitHubSource``."""

from typing import TYPE_CHECKING

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team import Team

from products.engineering_analytics.backend.facade.contracts import DepotCIRepoUsage
from products.engineering_analytics.backend.logic._shared import _parse_window
from products.engineering_analytics.backend.logic.cost import estimate_depot_ci_cost_usd
from products.engineering_analytics.backend.logic.sources import resolve_depot_job_attempts_tables
from products.engineering_analytics.backend.logic.views.depot_ci import build_billed_seconds_query

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl


def build_depot_ci_usage(
    *,
    team: Team,
    date_from: str | None = None,
    date_to: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> list[DepotCIRepoUsage]:
    window_from, window_to = _parse_window(team, date_from, date_to, default="-7d")
    placeholders: dict[str, ast.Expr] = {
        "window_from": ast.Constant(value=window_from),
        "window_to": ast.Constant(value=window_to) if window_to else ast.Call(name="now", args=[]),
    }
    usage: list[DepotCIRepoUsage] = []
    for repo, attempts in resolve_depot_job_attempts_tables(team, user_access_control).items():
        with tags_context(product=Product.ENGINEERING_ANALYTICS, feature=Feature.QUERY, team_id=team.pk):
            response = execute_hogql_query(
                query=parse_select(build_billed_seconds_query(attempts), placeholders=placeholders),
                team=team,
                query_type="engineering_analytics.depot_ci_usage",
                user=user_access_control.user if user_access_control is not None else None,
                user_access_control=user_access_control,
                # A userless caller has no ACL to honor, and HogQL would otherwise deny every warehouse table.
                bypass_warehouse_access_control=user_access_control is None,
            )
        seconds = float((response.results or [[0]])[0][0] or 0)
        usage.append(
            DepotCIRepoUsage(repo=repo, elapsed_seconds=seconds, estimated_cost_usd=estimate_depot_ci_cost_usd(seconds))
        )
    return usage
