from datetime import timedelta

from django.utils import timezone

import structlog
from celery import shared_task

from products.notifications.backend.models import NotificationEvent

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True)
def cleanup_old_notifications() -> None:
    cutoff = timezone.now() - timedelta(days=90)
    deleted_count, _ = NotificationEvent.objects.filter(created_at__lt=cutoff).delete()
    if deleted_count:
        logger.info("notifications.cleanup", deleted=deleted_count)
