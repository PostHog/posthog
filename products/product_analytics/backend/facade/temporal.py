"""Facade re-exports for product analytics Temporal wiring.

Core registers these with the Temporal worker (``start_temporal_worker``) and the
schedule bootstrap (``posthog/temporal/schedule.py``). They cross the boundary as
objects, not data, so they live in their own facade submodule, which keeps the
``temporalio`` imports out of ``facade/api.py``.
"""

from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from products.product_analytics.backend.temporal import ACTIVITIES, WORKFLOWS
from products.product_analytics.backend.temporal.upgrade_queries_workflow import UpgradeQueriesWorkflowInputs

__all__ = [
    "ACTIVITIES",
    "WORKFLOWS",
    "UpgradeQueriesWorkflowInputs",
]

TEMPORAL = TemporalRegistration(
    queues=(
        QueueBinding(
            queue_setting="GENERAL_PURPOSE_TASK_QUEUE", workflows=tuple(WORKFLOWS), activities=tuple(ACTIVITIES)
        ),
    ),
)
