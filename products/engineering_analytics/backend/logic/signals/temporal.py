"""Workflow + activity registration lists for the CI-signals coordinator.

Registered on ``settings.GENERAL_PURPOSE_TASK_QUEUE`` (the queue the schedule targets) via the
product facade in ``backend/facade/temporal.py``.
"""

from products.engineering_analytics.backend.logic.signals.coordinator import (
    CISignalsCoordinatorWorkflow,
    detect_and_emit_ci_signals_activity,
    discover_ci_signal_teams_activity,
)

WORKFLOWS = [CISignalsCoordinatorWorkflow]
ACTIVITIES = [discover_ci_signal_teams_activity, detect_and_emit_ci_signals_activity]
