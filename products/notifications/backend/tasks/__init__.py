# Re-export tasks for Celery autodiscover
from products.notifications.backend.tasks.tasks import cleanup_old_notifications

__all__ = ["cleanup_old_notifications"]
