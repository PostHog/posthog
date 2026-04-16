"""Compatibility shim for issue API classes/functions.

The canonical location is now `products.error_tracking.backend.presentation`.
"""

from products.error_tracking.backend.presentation.serializers import (
    ErrorTrackingIssueFullSerializer,
    ErrorTrackingIssueMergeRequestSerializer,
    ErrorTrackingIssueMergeResponseSerializer,
    ErrorTrackingIssuePreviewSerializer,
)
from products.error_tracking.backend.presentation.views import (
    DEFAULT_EMBEDDING_MODEL_NAME,
    DEFAULT_EMBEDDING_VERSION,
    DEFAULT_MIN_DISTANCE_THRESHOLD,
    ErrorTrackingIssueViewSet,
    assign_issue,
    get_status_from_string,
)

__all__ = [
    "DEFAULT_EMBEDDING_MODEL_NAME",
    "DEFAULT_EMBEDDING_VERSION",
    "DEFAULT_MIN_DISTANCE_THRESHOLD",
    "ErrorTrackingIssuePreviewSerializer",
    "ErrorTrackingIssueFullSerializer",
    "ErrorTrackingIssueMergeRequestSerializer",
    "ErrorTrackingIssueMergeResponseSerializer",
    "ErrorTrackingIssueViewSet",
    "assign_issue",
    "get_status_from_string",
]
