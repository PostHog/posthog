from datetime import timedelta

from django.utils import timezone

from celery import shared_task

from products.notebooks.backend.models import NotebookWidgetSnapshot


@shared_task(ignore_result=True, soft_time_limit=300, time_limit=330)
def cleanup_widget_snapshots() -> None:
    from products.notebooks.backend.widget_snapshots import (
        WidgetSnapshots,  # noqa: PLC0415 — keeps widget runtime off Celery startup
    )

    team_ids = (
        NotebookWidgetSnapshot.objects.unscoped()
        .filter(created_at__lt=timezone.now() - timedelta(days=7))
        .order_by()
        .values_list("team_id", flat=True)
        .distinct()
    )
    for team_id in team_ids.iterator():
        WidgetSnapshots.delete_unreferenced(team_id)
