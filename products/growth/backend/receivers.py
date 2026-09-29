from typing import Protocol
from uuid import UUID

from django.db import transaction

from products.tasks.backend.facade.task_run_signals import connect_task_run_post_save


class AuditRunSave(Protocol):
    id: UUID
    team_id: int
    status: str
    state: dict[str, object]


def schedule_audit_completion(
    sender: type, instance: AuditRunSave, created: bool, update_fields: frozenset[str] | None = None, **kwargs: object
) -> None:
    if created or instance.status not in {"completed", "failed", "cancelled"}:
        return
    if update_fields is not None and not {"status", "output", "state"}.intersection(update_fields):
        return
    if not instance.state.get("audit_notebook_short_id"):
        return
    from products.growth.backend.tasks import finalize_account_audit  # noqa: PLC0415 — keeps Celery off Django startup

    transaction.on_commit(lambda: finalize_account_audit.delay(instance.team_id, str(instance.id)), robust=True)


def connect() -> None:
    connect_task_run_post_save(schedule_audit_completion, dispatch_uid="growth_finalize_account_audit")
