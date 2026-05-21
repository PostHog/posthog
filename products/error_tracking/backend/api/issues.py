"""Compatibility shim for issue API classes.

The canonical location is now `products.error_tracking.backend.presentation`.
"""

from products.error_tracking.backend.presentation.issues import (
    ErrorTrackingIssueAssigneeReadSerializer,
    ErrorTrackingIssueCohortReadSerializer,
    ErrorTrackingIssueFullSerializer,
    ErrorTrackingIssueMergeRequestSerializer,
    ErrorTrackingIssueMergeResponseSerializer,
    ErrorTrackingIssuePreviewReadSerializer,
    ErrorTrackingIssuePreviewSerializer,
    ErrorTrackingIssueReadSerializer,
    ErrorTrackingIssueSplitFingerprintSerializer,
    ErrorTrackingIssueSplitRequestSerializer,
    ErrorTrackingIssueSplitResponseSerializer,
    ErrorTrackingIssueViewSet,
    IssueNotFoundError,
    assign_issue,
    get_status_from_string,
)

__all__ = [
    "ErrorTrackingIssueAssigneeReadSerializer",
    "ErrorTrackingIssueCohortReadSerializer",
    "ErrorTrackingIssueFullSerializer",
    "ErrorTrackingIssueMergeRequestSerializer",
    "ErrorTrackingIssueMergeResponseSerializer",
    "ErrorTrackingIssuePreviewReadSerializer",
    "ErrorTrackingIssuePreviewSerializer",
    "ErrorTrackingIssueReadSerializer",
    "ErrorTrackingIssueSplitFingerprintSerializer",
    "ErrorTrackingIssueSplitRequestSerializer",
    "ErrorTrackingIssueSplitResponseSerializer",
    "ErrorTrackingIssueViewSet",
    "IssueNotFoundError",
    "assign_issue",
    "get_status_from_string",
]
