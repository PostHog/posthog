from products.error_tracking.backend.temporal.fingerprint_embedding_result import (
    ACTIVITIES as FINGERPRINT_EMBEDDING_RESULT_ACTIVITIES,
    WORKFLOWS as FINGERPRINT_EMBEDDING_RESULT_WORKFLOWS,
    ErrorTrackingFingerprintEmbeddingResultWorkflow,
    merge_similar_fingerprints_activity,
)
from products.error_tracking.backend.temporal.recommendations_refresh import (
    ACTIVITIES as RECOMMENDATIONS_REFRESH_ACTIVITIES,
    WORKFLOWS as RECOMMENDATIONS_REFRESH_WORKFLOWS,
    ErrorTrackingRecommendationsRefreshWorkflow,
    get_team_batches_activity,
    refresh_recommendations_batch_activity,
)
from products.error_tracking.backend.temporal.spike_event_cleanup import (
    ACTIVITIES as SPIKE_EVENT_ACTIVITIES,
    WORKFLOWS as SPIKE_EVENT_WORKFLOWS,
    ErrorTrackingSpikeEventCleanupWorkflow,
    cleanup_spike_events_activity,
)
from products.error_tracking.backend.temporal.symbol_set_cleanup import (
    ACTIVITIES as SYMBOL_SET_ACTIVITIES,
    WORKFLOWS as SYMBOL_SET_WORKFLOWS,
    ErrorTrackingSymbolSetCleanupWorkflow,
    cleanup_symbol_sets_activity,
)

WORKFLOWS = (
    SYMBOL_SET_WORKFLOWS
    + SPIKE_EVENT_WORKFLOWS
    + RECOMMENDATIONS_REFRESH_WORKFLOWS
    + FINGERPRINT_EMBEDDING_RESULT_WORKFLOWS
)
ACTIVITIES = (
    SYMBOL_SET_ACTIVITIES
    + SPIKE_EVENT_ACTIVITIES
    + RECOMMENDATIONS_REFRESH_ACTIVITIES
    + FINGERPRINT_EMBEDDING_RESULT_ACTIVITIES
)

__all__ = [
    "ACTIVITIES",
    "WORKFLOWS",
    "ErrorTrackingFingerprintEmbeddingResultWorkflow",
    "ErrorTrackingRecommendationsRefreshWorkflow",
    "ErrorTrackingSpikeEventCleanupWorkflow",
    "ErrorTrackingSymbolSetCleanupWorkflow",
    "cleanup_spike_events_activity",
    "cleanup_symbol_sets_activity",
    "get_team_batches_activity",
    "merge_similar_fingerprints_activity",
    "refresh_recommendations_batch_activity",
]
