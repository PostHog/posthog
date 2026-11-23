from typing import TYPE_CHECKING

from products.error_tracking.backend.temporal.built_in_filters_refresh.activities import (
    refresh_built_in_filter_rules_activity,
)
from products.error_tracking.backend.temporal.built_in_filters_refresh.workflow import (
    ErrorTrackingBuiltInFiltersRefreshWorkflow,
)

if TYPE_CHECKING:
    from posthog.temporal.common.registration import ActivityDefinition

WORKFLOWS = [ErrorTrackingBuiltInFiltersRefreshWorkflow]
ACTIVITIES: list[ActivityDefinition] = [refresh_built_in_filter_rules_activity]

__all__ = [
    "ACTIVITIES",
    "WORKFLOWS",
    "ErrorTrackingBuiltInFiltersRefreshWorkflow",
    "refresh_built_in_filter_rules_activity",
]
