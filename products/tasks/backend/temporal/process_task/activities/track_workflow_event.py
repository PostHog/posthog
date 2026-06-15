from dataclasses import dataclass
from typing import Any

import posthoganalytics
from temporalio import activity

from posthog.temporal.common.logger import get_logger

from products.tasks.backend.metrics import observe_task_run_failed

logger = get_logger(__name__)


@dataclass
class TrackWorkflowEventInput:
    event_name: str
    distinct_id: str
    properties: dict[str, Any]
    groups: dict[str, str] | None = None


@activity.defn
def track_workflow_event(input: TrackWorkflowEventInput) -> None:
    """Track workflow-level events to PostHog."""
    try:
        if input.event_name == "task_run_failed":
            observe_task_run_failed(input.properties)

        posthoganalytics.capture(
            distinct_id=input.distinct_id,
            event=input.event_name,
            properties=input.properties,
            groups=input.groups or {},
        )
    except Exception:
        logger.exception(
            "Failed to track workflow event",
            event_name=input.event_name,
            distinct_id=input.distinct_id,
            properties=input.properties,
        )
