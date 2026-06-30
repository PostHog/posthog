"""Facade re-exports for error tracking Temporal wiring.

Core registers these with the Temporal worker (``start_temporal_worker``) and the
schedule bootstrap (``posthog/temporal/schedule.py``). They cross the boundary as
objects, not data, so they live in their own facade submodule — keeping the
``temporalio`` imports out of ``facade/api.py``.
"""

from products.error_tracking.backend.temporal import ACTIVITIES, WORKFLOWS
from products.error_tracking.backend.temporal.recommendations_refresh.types import RecommendationsRefreshInputs
from products.error_tracking.backend.temporal.spike_event_cleanup.schedule import (
    create_error_tracking_spike_event_cleanup_schedule,
)
from products.error_tracking.backend.temporal.symbol_set_cleanup.schedule import (
    create_error_tracking_symbol_set_cleanup_schedule,
)

__all__ = [
    "ACTIVITIES",
    "WORKFLOWS",
    "RecommendationsRefreshInputs",
    "create_error_tracking_spike_event_cleanup_schedule",
    "create_error_tracking_symbol_set_cleanup_schedule",
]
