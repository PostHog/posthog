"""Cross-team aggregation of MCP Analytics signal into the registry index.

For every project with recent $mcp_tool_call traffic, roll each advertised server up
to one stats row (volume, reliability, intent coverage) plus per-tool usage, then
attach it to a registry server row via linking. Tool grouping goes through the
mcp_analytics facade's EFFECTIVE_TOOL_SQL so single-exec servers don't collapse into
one `exec` bucket.
"""

from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.utils import timezone

import structlog

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team.team import Team

from products.mcp_analytics.backend.facade.sql import EFFECTIVE_DESCRIPTION_SQL, EFFECTIVE_TOOL_SQL, NEW_SDK_SOURCE
from products.mcp_registry.backend.constants import MEASURED_TEAM_LIMIT, MEASURED_TOOL_LIMIT, MEASURED_WINDOW_DAYS
from products.mcp_registry.backend.linking import resolve_measured_server
from products.mcp_registry.backend.models import MCPMeasuredStats, MCPRegistryServer, MCPRegistryTool

logger = structlog.get_logger(__name__)

_SERVER_STATS_SELECT = """
    SELECT
        toString(properties.$mcp_server_name) AS server_name,
        count() AS calls,
        uniq(toString(properties.$mcp_session_id)) AS sessions,
        countIf(toString(properties.$mcp_is_error) IN ('true', '1')) AS errors,
        countIf(notEmpty(toString(properties.$mcp_intent))) AS calls_with_intent,
        uniq({effective_tool}) AS distinct_tools,
        uniq(toString(properties.$mcp_client_name)) AS client_names
    FROM events
    WHERE event = '$mcp_tool_call'
        AND timestamp >= {date_from}
        AND properties.$mcp_source = {source}
        AND notEmpty(toString(properties.$mcp_server_name))
    GROUP BY server_name
    ORDER BY calls DESC
"""

_TOOL_STATS_SELECT = """
    SELECT
        {effective_tool} AS tool_name,
        any({effective_description}) AS description,
        count() AS calls,
        countIf(toString(properties.$mcp_is_error) IN ('true', '1')) AS errors
    FROM events
    WHERE event = '$mcp_tool_call'
        AND timestamp >= {date_from}
        AND properties.$mcp_source = {source}
        AND toString(properties.$mcp_server_name) = {server_name}
        AND notEmpty({effective_tool})
    GROUP BY tool_name
    ORDER BY calls DESC
    LIMIT {tool_limit}
"""


def discover_measured_teams(window_days: int = MEASURED_WINDOW_DAYS, limit: int = MEASURED_TEAM_LIMIT) -> list[int]:
    """Projects with recent MCP Analytics traffic: the measured-server universe.

    Raw ClickHouse rather than HogQL because HogQL execution is scoped to one team and
    this is the one cross-team question the pipeline asks. The table is qualified
    because the connection's default database is not the posthog database in every
    environment.
    """
    rows = sync_execute(
        f"""
        SELECT DISTINCT team_id
        FROM {settings.CLICKHOUSE_DATABASE}.events
        WHERE event = '$mcp_tool_call'
            AND timestamp >= now() - INTERVAL %(window_days)s DAY
            AND JSONExtractString(properties, '$mcp_source') = %(source)s
        ORDER BY team_id
        LIMIT %(limit)s
        """,
        {"window_days": window_days, "source": NEW_SDK_SOURCE, "limit": limit},
    )
    return [row[0] for row in rows or []]


def _query_placeholders(date_from: datetime) -> dict[str, ast.Expr]:
    return {
        "effective_tool": parse_expr(EFFECTIVE_TOOL_SQL),
        "effective_description": parse_expr(EFFECTIVE_DESCRIPTION_SQL),
        "date_from": ast.Constant(value=date_from),
        "source": ast.Constant(value=NEW_SDK_SOURCE),
    }


def aggregate_team(team: Team, window_days: int = MEASURED_WINDOW_DAYS) -> int:
    """Upsert measured stats + tool rows for every server seen in one team. Returns server count."""
    date_from = timezone.now() - timedelta(days=window_days)
    placeholders = _query_placeholders(date_from)
    with tags_context(product=Product.MCP, feature=Feature.QUERY, team_id=team.id):
        stats_response = execute_hogql_query(
            query=parse_select(_SERVER_STATS_SELECT, placeholders=placeholders),
            team=team,
            query_type="mcp_registry_server_stats",
        )

    computed_at = timezone.now()
    processed = 0
    for server_name, calls, sessions, errors, calls_with_intent, distinct_tools, client_names in (
        stats_response.results or []
    ):
        tool_placeholders = {**_query_placeholders(date_from)}
        tool_placeholders["server_name"] = ast.Constant(value=server_name)
        tool_placeholders["tool_limit"] = ast.Constant(value=MEASURED_TOOL_LIMIT)
        with tags_context(product=Product.MCP, feature=Feature.QUERY, team_id=team.id):
            tools_response = execute_hogql_query(
                query=parse_select(_TOOL_STATS_SELECT, placeholders=tool_placeholders),
                team=team,
                query_type="mcp_registry_tool_stats",
            )
        tool_rows = tools_response.results or []

        server, link_method, link_candidates = resolve_measured_server(server_name)
        MCPMeasuredStats.objects.update_or_create(
            team_id=team.id,
            server_name=server_name,
            defaults={
                "server": server,
                "window_days": window_days,
                "calls": calls,
                "sessions": sessions,
                "errors": errors,
                "error_rate_pct": round(100 * errors / calls, 2) if calls else 0.0,
                "intent_coverage_pct": round(100 * calls_with_intent / calls, 2) if calls else 0.0,
                "distinct_tools": distinct_tools,
                "harness_count": client_names,
                "tool_stats": [
                    {
                        "name": tool_name,
                        "calls": tool_calls,
                        "errors": tool_errors,
                        "error_rate_pct": round(100 * tool_errors / tool_calls, 2) if tool_calls else 0.0,
                    }
                    for tool_name, _description, tool_calls, tool_errors in tool_rows
                ],
                "link_method": link_method,
                "link_candidates": link_candidates,
                "computed_at": computed_at,
            },
        )
        _upsert_analytics_tools(server, tool_rows, computed_at)
        processed += 1

    logger.info("mcp_registry.aggregate.team_done", team_id=team.id, servers=processed)
    return processed


def _upsert_analytics_tools(server: MCPRegistryServer, tool_rows: list[Any], seen_at: datetime) -> None:
    """Record usage-observed tools. A probed tools/list row is authoritative for
    schema/description, so analytics only refreshes last_seen_at on those."""
    existing = {tool.name: tool for tool in server.tools.all()}
    for tool_name, description, _calls, _errors in tool_rows:
        tool = existing.get(tool_name)
        if tool is None:
            MCPRegistryTool.objects.create(
                server=server,
                name=tool_name,
                description=description or "",
                source="analytics",
                last_seen_at=seen_at,
            )
        elif tool.source == "analytics":
            tool.description = description or tool.description
            tool.last_seen_at = seen_at
            tool.save(update_fields=["description", "last_seen_at", "updated_at"])
        else:
            tool.last_seen_at = seen_at
            tool.save(update_fields=["last_seen_at", "updated_at"])


def aggregate_measured_servers(window_days: int = MEASURED_WINDOW_DAYS) -> int:
    """Aggregate every discovered team. Returns total measured (team, server) pairs."""
    total = 0
    for team_id in discover_measured_teams(window_days):
        try:
            team = Team.objects.get(pk=team_id)
        except Team.DoesNotExist:
            continue
        try:
            total += aggregate_team(team, window_days)
        except Exception:
            # One bad team must not sink the sweep; the next run retries it.
            logger.exception("mcp_registry.aggregate.team_failed", team_id=team_id)
    return total
