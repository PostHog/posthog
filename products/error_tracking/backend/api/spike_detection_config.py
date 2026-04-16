"""Compatibility shim for spike detection config API classes.

The canonical location is now `products.error_tracking.backend.presentation`.
"""

from products.error_tracking.backend.presentation.serializers import ErrorTrackingSpikeDetectionConfigSerializer
from products.error_tracking.backend.presentation.views import ErrorTrackingSpikeDetectionConfigViewSet

__all__ = [
    "ErrorTrackingSpikeDetectionConfigSerializer",
    "ErrorTrackingSpikeDetectionConfigViewSet",
]
