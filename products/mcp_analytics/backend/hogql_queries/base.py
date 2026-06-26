"""Shared wiring for the MCP analytics HogQL query runners.

The access gate and date-range construction are identical across every MCP
analytics runner; keeping them here means a runner is just its query shape plus
its harness-label SQL.
"""

from datetime import datetime
from typing import TYPE_CHECKING

import posthoganalytics

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.rbac.user_access_control import UserAccessControlError

if TYPE_CHECKING:
    from posthog.schema import DateRange

    from posthog.models.team import Team
    from posthog.models.user import User

# Gates these runners behind the same flag the product's DRF endpoints require, so the
# generic /query/ endpoint can't bypass it (see PostHogFeatureFlagPermission).
MCP_ANALYTICS_FEATURE_FLAG = "mcp-analytics"


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
