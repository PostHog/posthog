from collections.abc import Callable
from typing import Any

from products.replay_vision.backend.temporal.activities import (
    create_observation_activity,
    ensure_session_asset_activity,
    fetch_session_events_activity,
    mark_observation_failed_activity,
    mark_observation_running_activity,
)
from products.replay_vision.backend.temporal.workflow import ApplyLensWorkflow

WORKFLOWS = [ApplyLensWorkflow]
ACTIVITIES: list[Callable[..., Any]] = [
    create_observation_activity,
    mark_observation_running_activity,
    mark_observation_failed_activity,
    fetch_session_events_activity,
    ensure_session_asset_activity,
]

__all__ = [
    "ACTIVITIES",
    "WORKFLOWS",
    "ApplyLensWorkflow",
    "create_observation_activity",
    "ensure_session_asset_activity",
    "fetch_session_events_activity",
    "mark_observation_failed_activity",
    "mark_observation_running_activity",
]
