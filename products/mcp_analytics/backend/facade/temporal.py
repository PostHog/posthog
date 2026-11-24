"""MCP Analytics Temporal code that core's worker hosts. Core finds `TEMPORAL` through the product registry."""

from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from products.mcp_analytics.backend.temporal.wrapped import (
    MCP_ANALYTICS_WRAPPED_ACTIVITIES,
    MCP_ANALYTICS_WRAPPED_WORKFLOWS,
)

TEMPORAL = TemporalRegistration(
    queues=(
        QueueBinding(
            queue_setting="MCPA_TASK_QUEUE",
            workflows=tuple(MCP_ANALYTICS_WRAPPED_WORKFLOWS),
            activities=tuple(MCP_ANALYTICS_WRAPPED_ACTIVITIES),
        ),
    ),
)
