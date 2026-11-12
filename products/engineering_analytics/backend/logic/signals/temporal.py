from products.engineering_analytics.backend.logic.signals.coordinator import (
    CISignalsCoordinatorWorkflow,
    detect_and_emit_ci_signals_activity,
    discover_ci_signal_targets_activity,
    discover_ci_signal_teams_activity,
)

WORKFLOWS = [CISignalsCoordinatorWorkflow]
ACTIVITIES = [
    discover_ci_signal_teams_activity,
    discover_ci_signal_targets_activity,
    detect_and_emit_ci_signals_activity,
]
