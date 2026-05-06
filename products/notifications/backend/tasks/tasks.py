from datetime import timedelta

from django.utils import timezone

import structlog
from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit

from products.notifications.backend.models import NotificationEvent

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True)
@skip_team_scope_audit
def cleanup_old_notifications() -> None:
    cutoff = timezone.now() - timedelta(days=90)
    batch_size = 10000
    total_deleted = 0
    while True:
        ids = list(NotificationEvent.objects.filter(created_at__lt=cutoff).values_list("id", flat=True)[:batch_size])
        if not ids:
            break
        deleted, _ = NotificationEvent.objects.filter(id__in=ids).delete()
        total_deleted += deleted
    if total_deleted:
        logger.info("notifications.cleanup", deleted=total_deleted)
