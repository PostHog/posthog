"""Celery surface of the logs facade.

Core's beat schedule registers the cleanup task through this module. Only
task objects cross the boundary here — invocation happens via the queue.
"""

from products.logs.backend.tasks import logs_alert_events_cleanup_task

__all__ = ["logs_alert_events_cleanup_task"]
