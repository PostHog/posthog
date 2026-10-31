from collections.abc import Callable
from typing import Any

from products.metrics.backend.temporal.activities import (
    analyze_team_activity,
    check_preview_activity,
    draft_template_activity,
    find_teams_to_analyze_activity,
    finish_generation_activity,
    render_preview_activity,
    start_generation_activity,
)
from products.metrics.backend.temporal.workflows import (
    MetricsDashboardDiscoveryWorkflow,
    MetricsDashboardGenerateWorkflow,
    MetricsDashboardSuggestWorkflow,
)

WORKFLOWS = [MetricsDashboardDiscoveryWorkflow, MetricsDashboardSuggestWorkflow, MetricsDashboardGenerateWorkflow]
ACTIVITIES: list[Callable[..., Any]] = [
    find_teams_to_analyze_activity,
    analyze_team_activity,
    start_generation_activity,
    draft_template_activity,
    render_preview_activity,
    check_preview_activity,
    finish_generation_activity,
]
