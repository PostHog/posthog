"""Compatibility shim for grouping rule API classes/functions.

The canonical location is now `products.error_tracking.backend.presentation`.
"""

from products.error_tracking.backend.presentation.serializers import ErrorTrackingGroupingRuleSerializer
from products.error_tracking.backend.presentation.views import ErrorTrackingGroupingRuleViewSet, _build_issue_map

__all__ = [
    "ErrorTrackingGroupingRuleSerializer",
    "ErrorTrackingGroupingRuleViewSet",
    "_build_issue_map",
]
