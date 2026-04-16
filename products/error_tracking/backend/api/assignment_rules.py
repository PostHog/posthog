"""Compatibility shim for assignment rule API classes.

The canonical location is now `products.error_tracking.backend.presentation`.
"""

from products.error_tracking.backend.presentation.serializers import ErrorTrackingAssignmentRuleSerializer
from products.error_tracking.backend.presentation.views import ErrorTrackingAssignmentRuleViewSet

__all__ = [
    "ErrorTrackingAssignmentRuleSerializer",
    "ErrorTrackingAssignmentRuleViewSet",
]
