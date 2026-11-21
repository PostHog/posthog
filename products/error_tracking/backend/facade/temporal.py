"""Facade re-exports for error tracking Temporal wiring.

Core registers these with the Temporal worker (``start_temporal_worker``) and the
schedule bootstrap (``posthog/temporal/schedule.py``). They cross the boundary as
objects, not data, so they live in their own facade submodule — keeping the
``temporalio`` imports out of ``facade/api.py``.
"""

from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from products.error_tracking.backend.temporal import ACTIVITIES, LIFECYCLE_ACTIVITIES, LIFECYCLE_WORKFLOWS, WORKFLOWS
from products.error_tracking.backend.temporal.built_in_filters_refresh.schedule import (
    create_error_tracking_built_in_filters_refresh_schedule,
)
from products.error_tracking.backend.temporal.issue_change_cleanup.schedule import (
    create_error_tracking_issue_change_cleanup_schedule,
)
from products.error_tracking.backend.temporal.platform_alert_evaluate import (
    ERROR_TRACKING_ALERT_EVALUATION_ACTIVITIES,
    ERROR_TRACKING_ALERT_EVALUATION_WORKFLOWS,
)
from products.error_tracking.backend.temporal.recommendations_refresh.types import RecommendationsRefreshInputs
from products.error_tracking.backend.temporal.spike_event_cleanup.schedule import (
    create_error_tracking_spike_event_cleanup_schedule,
)
from products.error_tracking.backend.temporal.symbol_set_cleanup.schedule import (
    create_error_tracking_symbol_set_cleanup_schedule,
)
from products.error_tracking.backend.temporal.weekly_digest.schedule import create_error_tracking_weekly_digest_schedule

__all__ = [
    "ACTIVITIES",
    "LIFECYCLE_ACTIVITIES",
    "LIFECYCLE_WORKFLOWS",
    "WORKFLOWS",
    "RecommendationsRefreshInputs",
    "create_error_tracking_built_in_filters_refresh_schedule",
    "create_error_tracking_issue_change_cleanup_schedule",
    "create_error_tracking_spike_event_cleanup_schedule",
    "create_error_tracking_symbol_set_cleanup_schedule",
    "create_error_tracking_weekly_digest_schedule",
]

TEMPORAL = TemporalRegistration(
    queues=(
        QueueBinding(
            queue_setting="ERROR_TRACKING_TASK_QUEUE", workflows=tuple(WORKFLOWS), activities=tuple(ACTIVITIES)
        ),
        QueueBinding(
            queue_setting="ERROR_TRACKING_LIFECYCLE_TASK_QUEUE",
            workflows=tuple(LIFECYCLE_WORKFLOWS),
            activities=tuple(LIFECYCLE_ACTIVITIES),
        ),
        QueueBinding(
            queue_setting="ALERTS_PLATFORM_EVALUATION_TASK_QUEUE",
            workflows=tuple(ERROR_TRACKING_ALERT_EVALUATION_WORKFLOWS),
            activities=tuple(ERROR_TRACKING_ALERT_EVALUATION_ACTIVITIES),
        ),
    ),
    schedules=(
        create_error_tracking_symbol_set_cleanup_schedule,
        create_error_tracking_spike_event_cleanup_schedule,
        create_error_tracking_issue_change_cleanup_schedule,
        create_error_tracking_weekly_digest_schedule,
        create_error_tracking_built_in_filters_refresh_schedule,
    ),
)
