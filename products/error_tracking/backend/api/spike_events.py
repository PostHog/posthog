"""Compatibility shim for spike event API classes.

The canonical location is now `products.error_tracking.backend.presentation`.
"""

from products.error_tracking.backend.presentation.serializers import (
    ErrorTrackingSpikeEventIssueSerializer,
    ErrorTrackingSpikeEventSerializer,
)
from products.error_tracking.backend.presentation.views import ErrorTrackingSpikeEventViewSet

__all__ = [
    "ErrorTrackingSpikeEventIssueSerializer",
    "ErrorTrackingSpikeEventSerializer",
    "ErrorTrackingSpikeEventViewSet",
]
