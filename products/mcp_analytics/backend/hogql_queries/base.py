"""Shared wiring for the MCP analytics HogQL query runners.

The access gate and date-range construction are identical across every MCP
analytics runner; keeping them here means a runner is just its query shape plus
its harness-label SQL.
"""

from datetime import datetime
from typing import TYPE_CHECKING

import posthoganalytics

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.rbac.user_access_control import UserAccessControlError

if TYPE_CHECKING:
    from posthog.schema import DateRange

    from posthog.models.team import Team
    from posthog.models.user import User

# Gates these runners behind the same flag the product's DRF endpoints require, so the
# generic /query/ endpoint can't bypass it (see PostHogFeatureFlagPermission).
MCP_ANALYTICS_FEATURE_FLAG = "mcp-analytics"

# The effective tool name for new-SDK events: the inner tool when the call went through the
# single-exec wrapper, else the directly-registered tool name. Shared by every runner that
# scopes to one tool, so the expression lives OnceAndOnlyOnce.
EFFECTIVE_TOOL_SQL = (
    "coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name))"
)
# Marker the posthog-node MCP analytics SDK stamps on the events it sends.
NEW_SDK_SOURCE = "posthog_mcp_analytics"


def tool_scope_exprs(tool: str) -> list[ast.Expr]:
    """Predicates scoping new-SDK $mcp_tool_call events to one effective tool.

    `tool` is bound as an ast.Constant, never string-interpolated.
    """
    return [
        parse_expr(
            "{EFFECTIVE_TOOL_SQL} = {tool}",
            placeholders={"EFFECTIVE_TOOL_SQL": parse_expr(EFFECTIVE_TOOL_SQL), "tool": ast.Constant(value=tool)},
        ),
        parse_expr("properties.$mcp_source = {source}", placeholders={"source": ast.Constant(value=NEW_SDK_SOURCE)}),
    ]


def validate_mcp_analytics_access(team: "Team", user: "User") -> bool:
    org_id = str(team.organization_id)
    enabled = posthoganalytics.feature_enabled(
        MCP_ANALYTICS_FEATURE_FLAG,
        str(user.distinct_id),
        groups={"organization": org_id, "project": str(team.id)},
        group_properties={"organization": {"id": org_id}, "project": {"id": str(team.id)}},
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    )
    if not enabled:
        raise UserAccessControlError("mcp_analytics", "viewer")
    return True


def mcp_query_date_range(team: "Team", date_range: "DateRange | None") -> QueryDateRange:
    return QueryDateRange(
        date_range=date_range,
        team=team,
        interval=None,
        now=datetime.now(team.timezone_info),
    )
