"""Facade re-exports for the logs Celery tasks.

Core's beat schedule (``posthog/tasks/scheduled.py``) imports the task objects and calls
``.s()`` on them, so the wiring crosses the boundary as objects, not data. Re-exporting
the tasks keeps that coupling at the facade boundary. Each ``name=`` is pinned in its
defining module, so the registered task identity is independent of the import path.
"""

from products.logs.backend.tasks.clickhouse_lag_metrics import logs_clickhouse_lag_metrics_task
from products.logs.backend.tasks.tasks import logs_alert_events_cleanup_task

__all__ = ["logs_alert_events_cleanup_task", "logs_clickhouse_lag_metrics_task"]
