"""Celery tasks that core's beat schedule registers.

Importing this module loads the signals task module. Import it only from code that runs after
``django.setup()``, such as ``posthog/tasks/scheduled.py``.
"""

from products.signals.backend.tasks import (
    pause_inactive_signal_scouts,
    prune_expired_scratchpad_entries_task,
    reconcile_report_inbox_state_cache,
    refresh_signal_repository_activity,
    refresh_signal_scout_background_bands,
    sweep_first_report_notifications,
    sweep_implementation_dispatches,
    sweep_monitoring_tracker_issues,
    sync_pending_signals_refund_credits,
)

__all__ = [
    "pause_inactive_signal_scouts",
    "prune_expired_scratchpad_entries_task",
    "reconcile_report_inbox_state_cache",
    "refresh_signal_repository_activity",
    "refresh_signal_scout_background_bands",
    "sweep_first_report_notifications",
    "sweep_implementation_dispatches",
    "sweep_monitoring_tracker_issues",
    "sync_pending_signals_refund_credits",
]
