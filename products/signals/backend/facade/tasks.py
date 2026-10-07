"""Celery tasks that core's beat schedule registers.

Importing this module loads the signals task module, which the Django startup import
budget keeps off the ``django.setup()`` path. Import it only from code that runs after
setup, such as ``posthog/tasks/scheduled.py``.
"""

from products.signals.backend.tasks import (
    pause_inactive_signal_scouts as pause_inactive_signal_scouts,
    prune_expired_scratchpad_entries_task as prune_expired_scratchpad_entries_task,
    refresh_signal_repository_activity as refresh_signal_repository_activity,
    refresh_signal_scout_background_bands as refresh_signal_scout_background_bands,
    sweep_implementation_dispatches as sweep_implementation_dispatches,
    sync_pending_signals_refund_credits as sync_pending_signals_refund_credits,
)
