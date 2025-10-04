from dataclasses import dataclass
from typing import Any

import posthoganalytics
from temporalio import activity


@dataclass
class TrackWorkflowEventInput:
    event_name: str
    distinct_id: str
    properties: dict[str, Any]


@activity.defn
def track_workflow_event(input: TrackWorkflowEventInput) -> None:
    """Track workflow-level events to PostHog."""
    try:
        posthoganalytics.capture(
            distinct_id=input.distinct_id,
            event=input.event_name,
            properties=input.properties,
        )
    except Exception:
        pass
