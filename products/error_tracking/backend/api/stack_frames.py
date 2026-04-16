"""Compatibility shim for stack frame API classes/functions.

The canonical location is now `products.error_tracking.backend.presentation`.
"""

from products.error_tracking.backend.presentation.serializers import ErrorTrackingStackFrameSerializer
from products.error_tracking.backend.presentation.views import ErrorTrackingStackFrameViewSet, get_raw_id_part

__all__ = [
    "ErrorTrackingStackFrameSerializer",
    "ErrorTrackingStackFrameViewSet",
    "get_raw_id_part",
]
