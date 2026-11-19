from collections.abc import Callable

from products.error_tracking.backend.temporal.built_in_filters_refresh.activities import (
    refresh_built_in_filter_rules_activity,
)
from products.error_tracking.backend.temporal.built_in_filters_refresh.workflow import (
    ErrorTrackingBuiltInFiltersRefreshWorkflow,
)

WORKFLOWS = [ErrorTrackingBuiltInFiltersRefreshWorkflow]
ACTIVITIES: list[Callable[..., object]] = [refresh_built_in_filter_rules_activity]

__all__ = [
    "ACTIVITIES",
    "WORKFLOWS",
    "ErrorTrackingBuiltInFiltersRefreshWorkflow",
    "refresh_built_in_filter_rules_activity",
]
