"""
Facade API for the tasks product — the data surface other apps may import.

Responsibilities:
- Accept ids / DTOs as input.
- Call into the product's models and logic.
- Convert Django models to DTOs before returning — never return ORM instances.
- Stay thin and stable.

This module is deliberately light: it imports the models and small helpers only. The
heavy behavioral surfaces (sandbox provisioning, the multi-turn agent machinery, temporal
workflows, max tools) live in sibling facade submodules (``sandbox``, ``agents``,
``temporal``, ``max_tools``, ``webhooks``, ``streams``, ``repo_selection``) so a
config-only importer never drags docker/temporalio onto the ``django.setup()`` path.
Functions that bridge to those heavy surfaces import them lazily inside the function body.
"""

from collections.abc import Iterable
from datetime import timedelta
from uuid import UUID

from django.db.models import Count
from django.db.models.fields.json import KeyTextTransform
from django.utils import timezone as django_timezone

from products.tasks.backend.models import SandboxEnvironment, Task, TaskRun
from products.tasks.backend.visibility import task_visibility_q

from . import contracts

# --- Enum re-exports ---
# Value types (not ORM models), safe to expose. External callers compare against the
# string-valued ``.status`` / ``.environment`` / ``.origin_product`` fields on the DTOs.
TaskRunStatus = TaskRun.Status
TaskRunEnvironment = TaskRun.Environment
TaskOriginProduct = Task.OriginProduct
SandboxNetworkAccessLevel = SandboxEnvironment.NetworkAccessLevel

__all__ = [
    "SandboxNetworkAccessLevel",
    "TaskOriginProduct",
    "TaskRunEnvironment",
    "TaskRunStatus",
    "create_and_run_task",
    "create_sandbox_connection_token",
    "fail_task_run",
    "get_latest_pr_url_by_task",
    "get_latest_run_by_task",
    "get_stale_queued_task_run_ids",
    "get_task_run",
    "get_task_run_state_counts",
    "is_task_visible_to_user",
    "send_cancel",
    "send_user_message",
    "task_exists",
    "update_task_run_state",
    "upsert_internal_sandbox_env",
]


# --- Mappers ---


def _task_to_dto(task: Task) -> contracts.TaskDTO:
    return contracts.TaskDTO(
        id=task.id,
        team_id=task.team_id,
        title=task.title,
        description=task.description,
        origin_product=task.origin_product,
        repository=task.repository,
        internal=task.internal,
        archived=task.archived,
        created_at=task.created_at,
        updated_at=task.updated_at,
        created_by_id=task.created_by_id,
        task_number=task.task_number,
        slug=task.slug,
    )


def _task_run_to_dto(run: TaskRun, *, task: Task | None = None) -> contracts.TaskRunDTO:
    """Map a TaskRun to its DTO.

    Pass ``task`` (or rely on a ``select_related("task", "task__created_by")`` queryset)
    so the denormalised parent-task fields can be populated without an extra query.
    """
    parent = task if task is not None else getattr(run, "task", None)
    created_by = getattr(parent, "created_by", None) if parent is not None else None
    return contracts.TaskRunDTO(
        id=run.id,
        task_id=run.task_id,
        team_id=run.team_id,
        status=run.status,
        environment=run.environment,
        stage=run.stage,
        branch=run.branch,
        error_message=run.error_message,
        output=run.output,
        state=run.state or {},
        artifacts=run.artifacts or [],
        created_at=run.created_at,
        updated_at=run.updated_at,
        completed_at=run.completed_at,
        is_terminal=run.is_terminal,
        workflow_id=run.workflow_id,
        mode=run.mode,
        task_origin_product=parent.origin_product if parent is not None else None,
        created_by_distinct_id=str(created_by.distinct_id) if created_by is not None else None,
        pr_url=(run.output or {}).get("pr_url"),
    )


def _sandbox_env_to_dto(env: SandboxEnvironment) -> contracts.SandboxEnvironmentDTO:
    return contracts.SandboxEnvironmentDTO(
        id=env.id,
        team_id=env.team_id,
        name=env.name,
        network_access_level=env.network_access_level,
        private=env.private,
        internal=env.internal,
        include_default_domains=env.include_default_domains,
        allowed_domains=list(env.allowed_domains or []),
        repositories=list(env.repositories or []),
        created_at=env.created_at,
        updated_at=env.updated_at,
    )


# --- Reads ---


def get_task_run(run_id: str | UUID, team_id: int | None = None) -> contracts.TaskRunDTO | None:
    """Fetch a single task run as a DTO, optionally scoped to a team."""
    qs = TaskRun.objects.select_related("task", "task__created_by")
    if team_id is not None:
        qs = qs.filter(team_id=team_id)
    run = qs.filter(id=run_id).first()
    if run is None:
        return None
    return _task_run_to_dto(run)


def task_exists(task_id: str | UUID, team_id: int) -> bool:
    """Whether a (non-deleted) task exists for the team."""
    return Task.objects.filter(id=task_id, team_id=team_id).exists()


def is_task_visible_to_user(task_id: str | UUID, user_id: int | None) -> bool:
    """Whether the task is visible to the user under the task visibility rules.

    Tasks belong to their creator, plus team-wide signal-pipeline tasks and legacy unowned
    tasks. Used by core's file-system flow to gate delete/restore on a filed task.
    """
    return Task.objects.filter(task_visibility_q(user_id), pk=task_id).exists()


def get_latest_pr_url_by_task(task_ids: Iterable[str | UUID]) -> dict[str, str]:
    """Latest non-empty ``output.pr_url`` per task, for the supplied task ids."""
    ids = [str(t) for t in task_ids]
    if not ids:
        return {}
    rows = (
        TaskRun.objects.filter(task_id__in=ids, output__pr_url__isnull=False)
        .exclude(output__pr_url="")
        .order_by("task_id", "-created_at", "-id")
        .annotate(output_pr_url_text=KeyTextTransform("pr_url", "output"))
        .values("task_id", "output_pr_url_text")
        .distinct("task_id")
    )
    return {str(row["task_id"]): row["output_pr_url_text"] for row in rows if row["output_pr_url_text"]}


def get_latest_run_by_task(task_ids: Iterable[str | UUID]) -> dict[str, contracts.TaskRunDTO]:
    """Most-recent run per task (by ``created_at`` then ``id``), for the supplied task ids."""
    ids = [str(t) for t in task_ids]
    if not ids:
        return {}
    runs = (
        TaskRun.objects.filter(task_id__in=ids)
        .select_related("task", "task__created_by")
        .order_by("task_id", "-created_at", "-id")
        .distinct("task_id")
    )
    return {str(run.task_id): _task_run_to_dto(run) for run in runs}


def get_stale_queued_task_run_ids(older_than: timedelta, limit: int) -> list[UUID]:
    """Ids of runs stuck in QUEUED with ``updated_at`` older than the cutoff.

    Intentionally cross-team — the janitor sweep runs without a team context.
    """
    cutoff = django_timezone.now() - older_than
    return list(
        TaskRun.objects.filter(  # nosemgrep: celery-task-team-scope-audit
            status=TaskRun.Status.QUEUED, updated_at__lt=cutoff
        )
        .order_by("updated_at")
        .values_list("id", flat=True)[:limit]
    )


def get_task_run_state_counts() -> list[contracts.TaskRunStateCountDTO]:
    """Counts of runs grouped by (status, environment, parent origin_product)."""
    rows = (
        TaskRun.objects.values("status", "environment", "task__origin_product").annotate(count=Count("id")).order_by()
    )
    return [
        contracts.TaskRunStateCountDTO(
            status=row["status"],
            environment=row["environment"],
            origin_product=row["task__origin_product"],
            count=row["count"],
        )
        for row in rows
    ]


# --- Writes ---


def create_and_run_task(
    *,
    team,
    title: str,
    description: str,
    origin_product: "Task.OriginProduct",
    user_id: int,
    repository: str | None = None,
    create_pr: bool = True,
    mode: str = "background",
    start_workflow: bool = True,
    branch: str | None = None,
    signal_report_id: str | None = None,
    internal: bool = False,
    sandbox_environment_id: str | None = None,
    **extra,
) -> contracts.CreatedTaskDTO:
    """Create a task and (optionally) kick off its processing workflow.

    Thin wrapper over ``Task.create_and_run`` that returns ids + the created run as a DTO
    instead of leaking the ORM ``Task``. ``team`` is a core ``posthog.Team`` (not a tasks
    model). Less-common keyword arguments are forwarded verbatim via ``**extra``.
    """
    task = Task.create_and_run(
        team=team,
        title=title,
        description=description,
        origin_product=origin_product,
        user_id=user_id,
        repository=repository,
        create_pr=create_pr,
        mode=mode,
        start_workflow=start_workflow,
        branch=branch,
        signal_report_id=signal_report_id,
        internal=internal,
        sandbox_environment_id=sandbox_environment_id,
        **extra,
    )
    latest = task.latest_run
    return contracts.CreatedTaskDTO(
        task_id=task.id,
        team_id=task.team_id,
        latest_run=_task_run_to_dto(latest, task=task) if latest is not None else None,
    )


def update_task_run_state(
    run_id: str | UUID,
    *,
    updates: dict | None = None,
    remove_keys: Iterable[str] | None = None,
) -> dict:
    """Atomically merge state updates into a run's ``state`` and return the new state."""
    return TaskRun.update_state_atomic(run_id, updates=updates, remove_keys=remove_keys)


def fail_task_run(run_id: str | UUID, error: str) -> bool:
    """Mark a QUEUED run as failed. Returns whether a run was acted on.

    Refetches filtered on ``status=QUEUED`` so a run that left the queue between the
    candidate scan and this call is skipped. Intentionally cross-team (janitor sweep).
    """
    run = TaskRun.objects.filter(
        pk=run_id, status=TaskRun.Status.QUEUED
    ).first()  # nosemgrep: celery-task-team-scope-audit
    if run is None:
        return False
    run.mark_failed(error)
    return True


def upsert_internal_sandbox_env(
    team_id: int,
    name: str,
    network_access_level: "SandboxEnvironment.NetworkAccessLevel",
    *,
    private: bool = False,
    internal: bool = True,
    allowed_domains: list[str] | None = None,
    include_default_domains: bool = False,
) -> UUID:
    """Get-or-create an internal sandbox environment, reasserting policy on every call.

    ``SandboxEnvironment`` has no unique constraint on ``(team_id, name)``, so concurrent
    callers can both INSERT. We dedupe on ``MultipleObjectsReturned`` by keeping the oldest
    row and deleting the rest.
    """
    from django.db import transaction  # noqa: PLC0415 — narrow transaction around the dedupe retry

    defaults: dict = {
        "network_access_level": network_access_level,
        "private": private,
        "internal": internal,
    }
    if allowed_domains is not None:
        defaults["allowed_domains"] = allowed_domains
        defaults["include_default_domains"] = include_default_domains
    try:
        env, _ = SandboxEnvironment.objects.update_or_create(team_id=team_id, name=name, defaults=defaults)
        return env.id
    except SandboxEnvironment.MultipleObjectsReturned:
        with transaction.atomic():
            dupes = list(SandboxEnvironment.objects.filter(team_id=team_id, name=name).order_by("created_at"))
            keeper = dupes[0]
            SandboxEnvironment.objects.filter(id__in=[d.id for d in dupes[1:]]).delete()
        for key, value in defaults.items():
            setattr(keeper, key, value)
        keeper.save(update_fields=list(defaults.keys()))
        return keeper.id


# --- Id-based bridges to the sandbox/agent-command surface ---
# These take a run id (not an ORM TaskRun) so callers never hold a tasks model. The heavy
# service modules are imported lazily to keep them off this module's import path.


def create_sandbox_connection_token(run_id: str | UUID, user_id: int, distinct_id: str) -> str:
    """Mint a short-lived connection token for talking to a run's live sandbox."""
    from products.tasks.backend.services.connection_token import (  # noqa: PLC0415 — keep sandbox deps off the api import path
        create_sandbox_connection_token as _create,
    )

    run = TaskRun.objects.select_related("task").get(id=run_id)
    return _create(run, user_id, distinct_id)


def send_user_message(
    run_id: str | UUID,
    message: str | None = None,
    *,
    artifacts: list[dict] | None = None,
    auth_token: str | None = None,
):
    """Push a follow-up user message (and/or artifacts) into a run's live sandbox."""
    from products.tasks.backend.services.agent_command import (  # noqa: PLC0415 — keep sandbox deps off the api import path
        send_user_message as _send,
    )

    run = TaskRun.objects.select_related("task").get(id=run_id)
    return _send(run, message, artifacts=artifacts, auth_token=auth_token)


def send_cancel(run_id: str | UUID, *, auth_token: str | None = None):
    """Cancel the agent running in a run's live sandbox."""
    from products.tasks.backend.services.agent_command import (  # noqa: PLC0415 — keep sandbox deps off the api import path
        send_cancel as _send_cancel,
    )

    run = TaskRun.objects.select_related("task").get(id=run_id)
    return _send_cancel(run, auth_token=auth_token)
