"""Compatibility shim for suppression rule API classes/functions.

The canonical location is now `products.error_tracking.backend.presentation`.
"""

from products.error_tracking.backend.presentation.serializers import ErrorTrackingSuppressionRuleSerializer
from products.error_tracking.backend.presentation.views import (
    SERVER_ONLY_PROPERTIES,
    ErrorTrackingSuppressionRuleViewSet,
    _get_client_safe_filters,
    _has_filter_values,
    get_client_safe_suppression_rules,
)

__all__ = [
    "SERVER_ONLY_PROPERTIES",
    "ErrorTrackingSuppressionRuleSerializer",
    "ErrorTrackingSuppressionRuleViewSet",
    "_has_filter_values",
    "_get_client_safe_filters",
    "get_client_safe_suppression_rules",
]
