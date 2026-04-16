"""Compatibility shim for release API classes.

The canonical location is now `products.error_tracking.backend.presentation`.
"""

from products.error_tracking.backend.presentation.serializers import ErrorTrackingReleaseSerializer
from products.error_tracking.backend.presentation.views import ErrorTrackingReleaseViewSet

__all__ = [
    "ErrorTrackingReleaseSerializer",
    "ErrorTrackingReleaseViewSet",
]
