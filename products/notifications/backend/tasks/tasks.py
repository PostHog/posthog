from datetime import timedelta

from django.utils import timezone

from celery import shared_task


@shared_task(ignore_result=True)
def cleanup_old_notifications() -> None:
    from products.notifications.backend.models import Notification

    cutoff = timezone.now() - timedelta(days=90)
    Notification.objects.filter(created_at__lt=cutoff).delete()
