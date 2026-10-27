from typing import Any

from django.db import transaction

from products.tasks.backend.facade.task_run_signals import TaskOriginProduct, connect_task_run_post_save


def connect() -> None:
    connect_task_run_post_save(open_docs_pull_request, dispatch_uid="knowledge_writer_docs_pull_request")


def open_docs_pull_request(sender: type, instance: Any, created: bool, **kwargs: Any) -> None:
    if created or instance.origin_product != TaskOriginProduct.KNOWLEDGE_WRITER:
        return
    if instance.status != instance.Status.COMPLETED:
        return
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and "status" not in update_fields and "output" not in update_fields:
        return
    if not (instance.output or {}).get("head_branches"):
        return
    from .logic import pull_requests  # noqa: PLC0415 — keeps the GitHub client off the setup import path

    task_run_id, team_id = instance.id, instance.team_id
    transaction.on_commit(lambda: pull_requests.open_or_join_pull_request(task_run_id, team_id=team_id), robust=True)
