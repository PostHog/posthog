from django.utils import timezone

from celery import shared_task

from products.notebooks.backend.models import NotebookAppEmbed


@shared_task(ignore_result=True, soft_time_limit=240, time_limit=300)
def cleanup_expired_app_embeds() -> None:
    cutoff = timezone.now()
    expired = NotebookAppEmbed.objects.unscoped().filter(expires_at__lte=cutoff)
    for _ in range(10):
        ids = list(expired.order_by("expires_at").values_list("pk", flat=True)[:500])
        if not ids:
            break
        expired.filter(pk__in=ids).delete()
