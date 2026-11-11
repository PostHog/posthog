from typing import Any
from uuid import UUID

from django.db import transaction

import structlog

from posthog.exceptions_capture import capture_exception

from products.tasks.backend.facade.task_run_signals import TaskOriginProduct, connect_task_run_post_save

logger = structlog.get_logger(__name__)


def connect() -> None:
    connect_task_run_post_save(open_docs_pull_request, dispatch_uid="knowledge_writer_docs_pull_request")


def open_docs_pull_request(sender: type, instance: Any, created: bool, **kwargs: Any) -> None:
    try:
        schedule_docs_pull_request(instance, created=created, update_fields=kwargs.get("update_fields"))
    except Exception as error:
        logger.warning(
            "knowledge_writer_publish_schedule_failed",
            task_run_id=str(instance.id),
            team_id=instance.team_id,
            error_type=type(error).__name__,
        )
        capture_exception(error)


def schedule_docs_pull_request(instance: Any, *, created: bool, update_fields: Any) -> None:
    if created or instance.origin_product != TaskOriginProduct.KNOWLEDGE_WRITER:
        return
    if instance.status != instance.Status.COMPLETED:
        return
    if update_fields is not None and "status" not in update_fields and "output" not in update_fields:
        return
    if not (instance.output or {}).get("head_branches"):
        logger.warning(
            "knowledge_writer_run_without_docs_branch",
            task_id=str(instance.task_id),
            task_run_id=str(instance.id),
            team_id=instance.team_id,
        )
        return
    task_run_id, task_id, team_id = instance.id, instance.task_id, instance.team_id
    transaction.on_commit(lambda: start_publish_or_record_failure(task_run_id, task_id, team_id), robust=True)


def start_publish_or_record_failure(task_run_id: UUID, task_id: UUID, team_id: int) -> None:
    from .logic import pull_requests  # noqa: PLC0415 — keeps the GitHub client off the setup import path
    from .temporal import client as temporal_client  # noqa: PLC0415 — keeps temporalio off the setup import path

    pull_requests.claim_publication(task_id, team_id, task_run_id)
    try:
        temporal_client.start_publish(task_run_id, team_id=team_id)
    except Exception as error:
        logger.warning(
            "knowledge_writer_publish_not_started",
            task_run_id=str(task_run_id),
            team_id=team_id,
            error_type=type(error).__name__,
        )
        capture_exception(error, {"team_id": team_id, "task_run_id": str(task_run_id)})
        pull_requests.record_pull_request_failure(task_id, team_id, "publish_not_started")
