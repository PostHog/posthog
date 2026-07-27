# Re-export tasks for Celery autodiscover
from products.logs.backend.tasks.tasks import logs_alert_events_cleanup_task

__all__ = ["logs_alert_events_cleanup_task"]
