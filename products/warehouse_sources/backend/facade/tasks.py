"""
Celery task wiring for warehouse_sources.

Re-export of the beat-scheduled task that core registers (posthog/tasks/scheduled.py).
"""

from products.warehouse_sources.backend.tasks import reconcile_stuck_running_data_import_jobs

__all__ = ["reconcile_stuck_running_data_import_jobs"]
