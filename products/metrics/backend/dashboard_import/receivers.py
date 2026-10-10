"""Finishes a dashboard import when its agent task run ends, and checks the layout when the agent answers.

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
    finishes = instance.is_terminal and (update_fields is None or "status" in update_fields)
    # A run that checks the layout stays open after an answer, so the answer itself starts the next step.
    answers = (
        not instance.is_terminal
        and update_fields is not None
        and "output" in update_fields
        and bool((instance.state or {}).get("caller_ends_run"))
    )
    if not finishes and not answers:
        return
    from products.metrics.backend.tasks.tasks import (  # noqa: PLC0415 — keeps Celery task modules off the setup import path
        check_metrics_dashboard_import_layout,
        finalize_metrics_dashboard_import,
    )

    team_id, import_id = instance.team_id, str(instance.task_id)
    # The save time tells the layout check whether an answer replies to the latest picture.
    saved_at = instance.updated_at.isoformat() if update_fields and "updated_at" in update_fields else None

    def enqueue() -> None:
        if finishes:
            finalize_metrics_dashboard_import.delay(team_id, import_id)
        else:
            check_metrics_dashboard_import_layout.delay(team_id, import_id, saved_at)

    transaction.on_commit(enqueue, robust=True)
