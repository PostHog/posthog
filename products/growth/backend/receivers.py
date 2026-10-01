from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from django.db import transaction
from django.db.models.signals import post_save

from products.growth.backend.models import AccountAuditAdmission
from products.tasks.backend.facade.task_run_signals import connect_task_run_post_save

if TYPE_CHECKING:
    from posthog.models.file_system.file_system_view_log import FileSystemViewLog


def list_viewed_audit_notebook(sender: type, instance: "FileSystemViewLog", created: bool, **kwargs: object) -> None:
    if not created or instance.type != "notebook":
        return
    if not AccountAuditAdmission.objects.for_team(instance.team_id).filter(notebook_short_id=instance.ref).exists():
        return

    from products.notebooks.backend.facade.api import (
        make_notebook_listed,  # noqa: PLC0415 — keeps notebook dependencies off Django startup
    )

    make_notebook_listed(instance.team_id, instance.ref, user=instance.user)


class AuditRunSave(Protocol):
    id: UUID
    team_id: int
    status: str


def schedule_audit_completion(
    sender: type, instance: AuditRunSave, created: bool, update_fields: frozenset[str] | None = None, **kwargs: object
) -> None:
    if created or instance.status not in {"completed", "failed", "cancelled"}:
        return
    if update_fields is not None and not {"status", "output", "state"}.intersection(update_fields):
        return
    if not AccountAuditAdmission.objects.for_team(instance.team_id).filter(task_run_id=instance.id).exists():
        return
    from products.growth.backend.tasks import finalize_account_audit  # noqa: PLC0415 — keeps Celery off Django startup

    transaction.on_commit(lambda: finalize_account_audit.delay(instance.team_id, str(instance.id)), robust=True)


def connect() -> None:
    connect_task_run_post_save(schedule_audit_completion, dispatch_uid="growth_finalize_account_audit")
    post_save.connect(
        list_viewed_audit_notebook,
        sender="posthog.FileSystemViewLog",
        dispatch_uid="growth_list_viewed_audit_notebook",
    )
