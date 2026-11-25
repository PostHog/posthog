"""MCP Wrapped, registered against ``settings.MCPA_TASK_QUEUE`` through ``backend/facade/temporal.py``."""

from posthog.temporal.common.registration import ActivityDefinition

from products.mcp_analytics.backend.temporal.wrapped.activities import (
    discover_wrapped_team_ids_activity,
    generate_wrapped_activity,
)
from products.mcp_analytics.backend.temporal.wrapped.coordinator import MCPWrappedCoordinatorWorkflow

MCP_ANALYTICS_WRAPPED_WORKFLOWS = [MCPWrappedCoordinatorWorkflow]

MCP_ANALYTICS_WRAPPED_ACTIVITIES: list[ActivityDefinition] = [
    discover_wrapped_team_ids_activity,
    generate_wrapped_activity,
]

__all__ = [
    "MCP_ANALYTICS_WRAPPED_ACTIVITIES",
    "MCP_ANALYTICS_WRAPPED_WORKFLOWS",
    "MCPWrappedCoordinatorWorkflow",
    "discover_wrapped_team_ids_activity",
    "generate_wrapped_activity",
]
