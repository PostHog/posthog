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

from collections.abc import Iterable, Sequence
from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.db.models import CharField, Count, Exists, F, Min, Q, Subquery
from django.db.models.fields.json import KeyTextTransform
from django.utils import timezone as django_timezone

import posthoganalytics

from posthog.event_usage import groups
from posthog.models import User

from products.tasks.backend.models import (
    CodeInvite,
    CodeInviteRedemption,
    SandboxEnvironment,
    SandboxSnapshot,
    Task,
    TaskRun,
)
from products.tasks.backend.visibility import task_visibility_q

from . import contracts

# --- Enum re-exports ---
# Value types (not ORM models), safe to expose. External callers compare against the
# string-valued ``.status`` / ``.environment`` / ``.origin_product`` fields on the DTOs.
TaskRunStatus = TaskRun.Status
TaskRunEnvironment = TaskRun.Environment
TaskOriginProduct = Task.OriginProduct
SandboxNetworkAccessLevel = SandboxEnvironment.NetworkAccessLevel
SandboxSnapshotStatus = SandboxSnapshot.Status

# --- Code-invite redeem outcomes ---
# Returned on ``CodeInviteRedeemResult.outcome``; the presentation layer maps each to an
# HTTP response. ``REDEEMED`` covers both a fresh redemption and the idempotent no-op when
# the user already redeemed this code (both surface as success).
CODE_INVITE_REDEEMED = "redeemed"
CODE_INVITE_INVALID_CODE = "invalid_code"
CODE_INVITE_NOT_REDEEMABLE = "not_redeemable"

__all__ = [
    "CODE_INVITE_INVALID_CODE",
    "CODE_INVITE_NOT_REDEEMABLE",
    "CODE_INVITE_REDEEMED",
    "SandboxNetworkAccessLevel",
    "SandboxSnapshotStatus",
    "TaskOriginProduct",
    "TaskRunEnvironment",
    "TaskRunStatus",
    "create_and_run_task",
    "create_completed_sandbox_snapshot",
    "collect_task_run_state_metrics",
    "create_run",
    "create_sandbox_connection_token",
    "create_sandbox_environment",
    "delete_sandbox_environment",
    "fail_task_run",
    "get_latest_pr_url_by_task",
    "get_latest_run_by_task",
    "get_sandbox_environment",
    "get_sandbox_snapshot",
    "get_stale_queued_task_run_ids",
    "get_task_run",
    "is_task_visible_to_user",
    "is_valid_sandbox_env_var_key",
    "latest_task_run_pr_url_subquery",
    "list_sandbox_environments",
    "redeem_code_invite",
    "send_cancel",
    "send_user_message",
    "task_exists",
    "task_run_pr_url_exists_subquery",
    "update_sandbox_environment",
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
        created_by_id=parent.created_by_id if parent is not None else None,
        created_by_distinct_id=str(created_by.distinct_id) if created_by is not None else None,
        pr_url=(run.output or {}).get("pr_url"),
    )


def _hedgehog_config(user: "User") -> dict | None:
    """Mirror core ``UserBasicSerializer.get_hedgehog_config`` so ``created_by`` output is identical."""
    config = user.hedgehog_config
    if not config:
        return None
    if config.get("version") == 2:
        actor_options = config.get("actor_options", {})
        return {
            "use_as_profile": config.get("use_as_profile"),
            "color": actor_options.get("color"),
            "accessories": actor_options.get("accessories"),
            "skin": actor_options.get("skin"),
        }
    return {
        "use_as_profile": config.get("use_as_profile"),
        "color": config.get("color"),
        "accessories": config.get("accessories"),
        "skin": config.get("skin"),
    }


def _user_basic_info(user: "User | None") -> contracts.UserBasicInfo | None:
    """Map a core ``User`` to the display DTO (matches ``UserBasicSerializer`` fields)."""
    if user is None:
        return None
    return contracts.UserBasicInfo(
        id=user.id,
        uuid=user.uuid,
        distinct_id=str(user.distinct_id),
        first_name=user.first_name,
        last_name=user.last_name,
        email=user.email,
        is_email_verified=user.is_email_verified,
        hedgehog_config=_hedgehog_config(user),
        role_at_organization=user.role_at_organization,
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
        effective_domains=env.get_effective_domains(),
        has_environment_variables=bool(env.environment_variables),
        created_by=_user_basic_info(env.created_by if env.created_by_id else None),
        created_at=env.created_at,
        updated_at=env.updated_at,
    )


def _sandbox_snapshot_to_dto(snapshot: SandboxSnapshot) -> contracts.SandboxSnapshotDTO:
    return contracts.SandboxSnapshotDTO(
        id=snapshot.id,
        external_id=snapshot.external_id,
        status=snapshot.status,
        repos=list(snapshot.repos or []),
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


def get_sandbox_snapshot(snapshot_id: str | UUID) -> contracts.SandboxSnapshotDTO | None:
    """Fetch a sandbox snapshot as a DTO."""
    snapshot = SandboxSnapshot.objects.filter(id=snapshot_id).first()
    return _sandbox_snapshot_to_dto(snapshot) if snapshot is not None else None


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


def task_run_pr_url_exists_subquery(**task_run_filter) -> Exists:
    """``Exists`` over runs matching ``task_run_filter`` that produced a non-empty output.pr_url.

    The caller supplies the correlation filter (e.g. ``task__signal_report_tasks__report_id=
    OuterRef("id")`` plus its own relationship value). Returns a query expression to embed in
    the caller's queryset — no ORM instances cross the boundary, and the tasks facade stays
    free of the caller's domain.
    """
    return Exists(TaskRun.objects.filter(**task_run_filter, output__pr_url__isnull=False).exclude(output__pr_url=""))


def latest_task_run_pr_url_subquery(**task_run_filter) -> Subquery:
    """``Subquery`` of the latest non-empty output.pr_url for runs matching ``task_run_filter``."""
    return Subquery(
        TaskRun.objects.filter(**task_run_filter, output__pr_url__isnull=False)
        .exclude(output__pr_url="")
        .order_by("-created_at")
        .annotate(output_pr_url_text=KeyTextTransform("pr_url", "output"))
        .values("output_pr_url_text")[:1],
        output_field=CharField(),
    )


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


def _gauge_rows(values_qs, value_key: str, *, with_status: bool, now=None) -> list[contracts.TaskRunGaugeRow]:
    rows = []
    for row in values_qs:
        raw = row[value_key]
        value = (now - raw).total_seconds() if now is not None else raw
        rows.append(
            contracts.TaskRunGaugeRow(
                environment=row["environment"],
                origin_product=row["task__origin_product"] or "unknown",
                value=value,
                status=row["status"] if with_status else None,
            )
        )
    return rows


def collect_task_run_state_metrics(
    *,
    open_statuses: Sequence[str],
    age_statuses: Sequence[str],
    terminal_statuses: Sequence[str],
    window_seconds: int,
) -> contracts.TaskRunStateMetricsDTO:
    """Aggregate TaskRun state for monitoring gauges.

    The caller (a core celery task) owns which statuses count as open/age/terminal and the
    recency window; this returns the raw numbers grouped by (status, environment,
    parent origin_product) so no ORM leaks across the boundary.
    """
    now = django_timezone.now()
    window_start = now - timedelta(seconds=window_seconds)
    return contracts.TaskRunStateMetricsDTO(
        runs_in_status=_gauge_rows(
            TaskRun.objects.filter(status__in=open_statuses)
            .values("status", "environment", "task__origin_product")
            .annotate(count=Count("id")),
            "count",
            with_status=True,
        ),
        oldest_open_age_seconds=_gauge_rows(
            TaskRun.objects.filter(status__in=age_statuses)
            .values("status", "environment", "task__origin_product")
            .annotate(oldest_created_at=Min("created_at")),
            "oldest_created_at",
            with_status=True,
            now=now,
        ),
        created_recently=_gauge_rows(
            TaskRun.objects.filter(created_at__gte=window_start)
            .values("environment", "task__origin_product")
            .annotate(count=Count("id")),
            "count",
            with_status=False,
        ),
        terminal_recently=_gauge_rows(
            TaskRun.objects.filter(status__in=terminal_statuses, updated_at__gte=window_start)
            .values("status", "environment", "task__origin_product")
            .annotate(count=Count("id")),
            "count",
            with_status=True,
        ),
    )


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


def create_run(
    task_id: str | UUID,
    *,
    mode: str = "background",
    extra_state: dict | None = None,
    branch: str | None = None,
) -> contracts.TaskRunDTO:
    """Create a new run for an existing task (e.g. resuming an interactive sandbox session)."""
    task = Task.objects.get(id=task_id)
    run = task.create_run(mode=mode, extra_state=extra_state, branch=branch)
    return _task_run_to_dto(run, task=task)


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


def create_completed_sandbox_snapshot(external_id: str) -> UUID:
    """Record a completed sandbox snapshot for an externally-built image; return its id."""
    snapshot = SandboxSnapshot.objects.create(external_id=external_id, status=SandboxSnapshot.Status.COMPLETE)
    return snapshot.id


# --- Code invites ---


def redeem_code_invite(code: str, user_id: int) -> contracts.CodeInviteRedeemResult:
    """Redeem a PostHog Code invite for a user.

    Idempotent: a user who already redeemed this code gets ``REDEEMED`` without a second
    redemption row. A fresh redemption takes a row lock on the invite, re-checks
    redeemability under the lock, records the redemption, bumps ``redemption_count``, and
    captures the activation analytics — all in one transaction, mirroring the original view.
    """
    code_str = code.strip()

    try:
        invite_code = CodeInvite.objects.get(code__iexact=code_str)
    except CodeInvite.DoesNotExist:
        return contracts.CodeInviteRedeemResult(outcome=CODE_INVITE_INVALID_CODE)

    user = User.objects.get(pk=user_id)

    if CodeInviteRedemption.objects.filter(invite_code=invite_code, user=user).exists():
        return contracts.CodeInviteRedeemResult(outcome=CODE_INVITE_REDEEMED)

    with transaction.atomic():
        invite_code = CodeInvite.objects.select_for_update().get(id=invite_code.id)

        if not invite_code.is_redeemable:
            return contracts.CodeInviteRedeemResult(outcome=CODE_INVITE_NOT_REDEEMABLE)

        organization = user.organization if hasattr(user, "organization") else None

        CodeInviteRedemption.objects.create(
            invite_code=invite_code,
            user=user,
            organization=organization,
        )

        CodeInvite.objects.filter(id=invite_code.id).update(redemption_count=F("redemption_count") + 1)

        posthoganalytics.capture(
            distinct_id=str(user.distinct_id),
            event="code_invite_redeemed",
            groups=groups(organization=organization),
        )

    return contracts.CodeInviteRedeemResult(outcome=CODE_INVITE_REDEEMED)


# --- Sandbox environments (presentation CRUD) ---
# Visibility: an environment is reachable by a team member if it is non-private, or it is
# theirs (``created_by``). ``list`` additionally hides ``internal`` environments.


def is_valid_sandbox_env_var_key(key: str) -> bool:
    """Whether ``key`` is a valid environment-variable name (``[A-Za-z_][A-Za-z0-9_]*``)."""
    return SandboxEnvironment.is_valid_env_var_key(key)


def _accessible_sandbox_envs(team_id: int, user_id: int):
    return (
        SandboxEnvironment.objects.filter(team_id=team_id)
        .filter(Q(private=False) | Q(created_by_id=user_id))
        .select_related("created_by")
    )


def list_sandbox_environments(team_id: int, user_id: int) -> list[contracts.SandboxEnvironmentDTO]:
    """Non-internal environments visible to the user, for the list view."""
    return [_sandbox_env_to_dto(env) for env in _accessible_sandbox_envs(team_id, user_id).filter(internal=False)]


def get_sandbox_environment(env_id: str | UUID, team_id: int, user_id: int) -> contracts.SandboxEnvironmentDTO | None:
    """A single environment visible to the user (internal ones are retrievable by id)."""
    env = _accessible_sandbox_envs(team_id, user_id).filter(pk=env_id).first()
    return _sandbox_env_to_dto(env) if env is not None else None


def create_sandbox_environment(
    team_id: int,
    user_id: int,
    *,
    name: str,
    network_access_level: str,
    allowed_domains: list[str],
    include_default_domains: bool,
    repositories: list[str],
    environment_variables: dict,
    private: bool,
) -> contracts.SandboxEnvironmentDTO:
    """Create a team environment owned by the user and return it as a DTO."""
    env = SandboxEnvironment.objects.create(
        team_id=team_id,
        created_by_id=user_id,
        name=name,
        network_access_level=network_access_level,
        allowed_domains=allowed_domains,
        include_default_domains=include_default_domains,
        repositories=repositories,
        environment_variables=environment_variables,
        private=private,
    )
    return _sandbox_env_to_dto(SandboxEnvironment.objects.select_related("created_by").get(pk=env.pk))


def update_sandbox_environment(
    env_id: str | UUID, team_id: int, user_id: int, **fields
) -> contracts.SandboxEnvironmentDTO | None:
    """Partially update a visible environment. Returns ``None`` if not found/visible."""
    env = _accessible_sandbox_envs(team_id, user_id).filter(pk=env_id).first()
    if env is None:
        return None
    for key, value in fields.items():
        setattr(env, key, value)
    env.save()
    return _sandbox_env_to_dto(SandboxEnvironment.objects.select_related("created_by").get(pk=env.pk))


def delete_sandbox_environment(env_id: str | UUID, team_id: int, user_id: int) -> bool:
    """Delete a visible environment. Returns whether a row was deleted."""
    env = _accessible_sandbox_envs(team_id, user_id).filter(pk=env_id).first()
    if env is None:
        return False
    env.delete()
    return True


# --- Id-based bridges to the sandbox/agent-command surface ---
# These take a run id (not an ORM TaskRun) so callers never hold a tasks model. The heavy
# service modules are imported lazily to keep them off this module's import path.


def create_sandbox_connection_token(run_id: str | UUID, user_id: int, distinct_id: str) -> str:
    """Mint a short-lived connection token for talking to a run's live sandbox."""
    from products.tasks.backend.logic.services.connection_token import (  # noqa: PLC0415 — keep sandbox deps off the api import path
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
    timeout: int | None = None,
):
    """Push a follow-up user message (and/or artifacts) into a run's live sandbox."""
    from products.tasks.backend.logic.services.agent_command import (  # noqa: PLC0415 — keep sandbox deps off the api import path
        send_user_message as _send,
    )

    run = TaskRun.objects.select_related("task").get(id=run_id)
    # Forward only explicitly-provided optionals so the underlying call shape is unchanged.
    extra: dict = {}
    if artifacts is not None:
        extra["artifacts"] = artifacts
    if timeout is not None:
        extra["timeout"] = timeout
    return _send(run, message, auth_token=auth_token, **extra)


def send_cancel(run_id: str | UUID, *, auth_token: str | None = None):
    """Cancel the agent running in a run's live sandbox."""
    from products.tasks.backend.logic.services.agent_command import (  # noqa: PLC0415 — keep sandbox deps off the api import path
        send_cancel as _send_cancel,
    )

    run = TaskRun.objects.select_related("task").get(id=run_id)
    return _send_cancel(run, auth_token=auth_token)
