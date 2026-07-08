"""Facade re-export for the logs Celery task.

Core's beat schedule (``posthog/tasks/scheduled.py``) imports the task object and calls
``.s()`` on it, so the wiring crosses the boundary as an object, not data. Re-exporting
the task keeps that coupling at the facade boundary. Its ``name=`` is pinned in
``tasks/tasks.py``, so the registered task identity is independent of the import path.
"""

from products.logs.backend.tasks.tasks import logs_alert_events_cleanup_task

__all__ = ["logs_alert_events_cleanup_task"]
