"""Compatibility shim that re-exports the Error tracking viewsets.

The viewsets have moved to ``products.error_tracking.backend.presentation``.
This shim keeps existing import paths (``products.error_tracking.backend.api``)
working while callers are migrated.
"""

from products.error_tracking.backend.presentation.assignment_rules import ErrorTrackingAssignmentRuleViewSet
from products.error_tracking.backend.presentation.external_references import ErrorTrackingExternalReferenceViewSet
from products.error_tracking.backend.presentation.fingerprints import ErrorTrackingFingerprintViewSet
from products.error_tracking.backend.presentation.git_provider_file_link_resolver import GitProviderFileLinksViewSet
from products.error_tracking.backend.presentation.grouping_rules import ErrorTrackingGroupingRuleViewSet
from products.error_tracking.backend.presentation.issues import ErrorTrackingIssueViewSet
from products.error_tracking.backend.presentation.releases import ErrorTrackingReleaseViewSet
from products.error_tracking.backend.presentation.spike_detection_config import ErrorTrackingSpikeDetectionConfigViewSet
from products.error_tracking.backend.presentation.spike_events import ErrorTrackingSpikeEventViewSet
from products.error_tracking.backend.presentation.stack_frames import ErrorTrackingStackFrameViewSet
from products.error_tracking.backend.presentation.suppression_rules import ErrorTrackingSuppressionRuleViewSet
from products.error_tracking.backend.presentation.symbol_sets import ErrorTrackingSymbolSetViewSet

__all__ = [
    "ErrorTrackingAssignmentRuleViewSet",
    "ErrorTrackingExternalReferenceViewSet",
    "ErrorTrackingFingerprintViewSet",
    "ErrorTrackingGroupingRuleViewSet",
    "ErrorTrackingIssueViewSet",
    "ErrorTrackingReleaseViewSet",
    "ErrorTrackingSpikeDetectionConfigViewSet",
    "ErrorTrackingSpikeEventViewSet",
    "ErrorTrackingStackFrameViewSet",
    "ErrorTrackingSuppressionRuleViewSet",
    "ErrorTrackingSymbolSetViewSet",
    "GitProviderFileLinksViewSet",
]
