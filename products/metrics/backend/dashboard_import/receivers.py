"""Finishes a dashboard import when its agent task run ends.

This module loads at Django setup, so it imports only the light task run signal module.
"""

from typing import Any

from django.db import transaction

from products.tasks.backend.facade.task_run_signals import TaskOriginProduct, connect_task_run_post_save


def connect() -> None:
    connect_task_run_post_save(
        schedule_import_finalization, dispatch_uid="metrics_schedule_dashboard_import_finalization"
    )


def schedule_import_finalization(sender: type, instance: Any, created: bool, **kwargs: Any) -> None:
    # Every task run save calls this, so the checks that need no query come first.
    if created or instance.origin_product != TaskOriginProduct.METRICS_IMPORT:
        return
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and "status" not in update_fields:
        return
    if not instance.is_terminal:
        return
    from products.metrics.backend.tasks.tasks import (  # noqa: PLC0415 — keeps Celery task modules off the setup import path
        finalize_metrics_dashboard_import,
    )

    team_id, import_id = instance.team_id, str(instance.task_id)

    def enqueue() -> None:
        finalize_metrics_dashboard_import.delay(team_id, import_id)

    transaction.on_commit(enqueue, robust=True)
