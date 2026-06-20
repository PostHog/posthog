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

import logging
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta
from uuid import UUID

from django.db import transaction
from django.db.models import CharField, Count, Exists, F, Min, Q, Subquery
from django.db.models.fields.json import KeyTextTransform
from django.utils import timezone as django_timezone

import posthoganalytics

from posthog.event_usage import groups
from posthog.models import User
from posthog.models.integration import Integration

from products.tasks.backend.logic.code_workstreams.default_workflow import build_default_bindings
from products.tasks.backend.logic.code_workstreams.validation import validate_bindings
from products.tasks.backend.models import (
    CodeInvite,
    CodeInviteRedemption,
    CodeWorkflowConfig,
    CodeWorkstream,
    SandboxEnvironment,
    SandboxSnapshot,
    Task,
    TaskAutomation,
    TaskRun,
)
from products.tasks.backend.visibility import task_run_visibility_q, task_visibility_q

from . import contracts

logger = logging.getLogger(__name__)

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

# --- Code-workflow save outcomes ---
# Returned on ``CodeWorkflowSaveResult.outcome``; the presentation layer maps each to an
# HTTP status (saved -> 200, conflict -> 409, invalid -> 422).
CODE_WORKFLOW_SAVED = "saved"
CODE_WORKFLOW_CONFLICT = "conflict"
CODE_WORKFLOW_INVALID = "invalid"

# --- Code-home tuning ---
# An agent run counts as "active" only if it updated within this window.
CODE_HOME_ACTIVE_AGENT_WINDOW = timedelta(minutes=30)
_CODE_HOME_RUNNING_STATUSES = (TaskRun.Status.QUEUED, TaskRun.Status.IN_PROGRESS)

__all__ = [
    "CODE_INVITE_INVALID_CODE",
    "CODE_INVITE_NOT_REDEEMABLE",
    "CODE_INVITE_REDEEMED",
    "CODE_WORKFLOW_CONFLICT",
    "CODE_WORKFLOW_INVALID",
    "CODE_WORKFLOW_SAVED",
    "SandboxNetworkAccessLevel",
    "SandboxSnapshotStatus",
    "TaskOriginProduct",
    "TaskRunEnvironment",
    "TaskRunStatus",
    "append_task_run_log",
    "bootstrap_task_run",
    "check_task_run_startable",
    "collect_task_run_state_metrics",
    "create_and_run_task",
    "create_completed_sandbox_snapshot",
    "create_run",
    "create_sandbox_connection_token",
    "create_sandbox_environment",
    "create_task_automation",
    "create_task_run_connection_token",
    "delete_sandbox_environment",
    "delete_task_automation",
    "fail_task_run",
    "finalize_task_run_artifact_uploads",
    "get_code_home",
    "get_code_workflow_config",
    "get_latest_pr_url_by_task",
    "get_latest_run_by_task",
    "get_sandbox_environment",
    "get_sandbox_snapshot",
    "get_stale_queued_task_run_ids",
    "get_task_automation",
    "get_task_id_for_run",
    "get_task_run",
    "get_task_run_detail",
    "get_task_run_sandbox_connection",
    "get_task_run_stream_info",
    "is_task_visible_to_user",
    "is_valid_sandbox_env_var_key",
    "latest_task_run_pr_url_subquery",
    "list_sandbox_environments",
    "list_task_automations",
    "list_task_runs",
    "prepare_task_run_artifact_uploads",
    "presign_task_run_artifact",
    "read_task_run_artifact",
    "read_task_run_logs",
    "read_task_run_session_log_content",
    "redeem_code_invite",
    "refresh_team_code_workstreams",
    "relay_task_run_message",
    "reset_code_workflow_bindings",
    "resume_task_run_in_cloud",
    "run_task_automation_now",
    "save_code_workflow_bindings",
    "send_cancel",
    "send_user_message",
    "set_task_run_output",
    "signal_task_run_user_message",
    "signal_workflow_completion",
    "start_task_run",
    "task_accessible_for_run_view",
    "task_exists",
    "task_run_has_slack_mapping",
    "task_run_is_terminal",
    "task_run_pr_url_exists_subquery",
    "update_sandbox_environment",
    "update_task_automation",
    "update_task_run",
    "update_task_run_state",
    "upsert_internal_sandbox_env",
    "validate_set_output",
    "validate_task_run_artifact_ids",
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


def _user_basic_info(user: "User | None") -> contracts.TaskUserBasicInfo | None:
    """Map a core ``User`` to the display DTO (matches ``UserBasicSerializer`` fields)."""
    if user is None:
        return None
    return contracts.TaskUserBasicInfo(
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


# Presigned log URLs are cached just under their 1-hour S3 expiry to avoid regeneration.
_TASK_RUN_LOG_URL_CACHE_TTL = 55 * 60


def _task_run_log_url(run: TaskRun) -> str | None:
    """Presigned S3 URL for a run's log, cached. Mirrors ``TaskRunDetailSerializer.get_log_url``."""
    from posthog.storage import object_storage  # noqa: PLC0415 — keep storage deps off the api import path

    from products.tasks.backend.redis import get_tasks_cache  # noqa: PLC0415 — keep redis off the api import path

    cache_key = f"task_run_log_url:{run.id}"
    cached_url = get_tasks_cache().get(cache_key)
    if cached_url:
        return cached_url

    presigned_url = object_storage.get_presigned_url(run.log_url, expiration=3600)
    if presigned_url:
        get_tasks_cache().set(cache_key, presigned_url, timeout=_TASK_RUN_LOG_URL_CACHE_TTL)
    return presigned_url


def _task_run_detail_to_dto(run: TaskRun) -> contracts.TaskRunDetailDTO:
    """Map a ``TaskRun`` to its HTTP detail DTO.

    Reproduces the SMF-derived fields ``TaskRunDetailSerializer`` computed: ``log_url`` does
    presigned-URL I/O (with caching), and ``runtime_adapter`` / ``provider`` / ``model`` /
    ``reasoning_effort`` are parsed off the run ``state``.
    """
    from products.tasks.backend.temporal.process_task.utils import (  # noqa: PLC0415 — keep temporalio off the api import path
        parse_run_state,
    )

    state = parse_run_state(run.state)
    return contracts.TaskRunDetailDTO(
        id=run.id,
        task=run.task_id,
        stage=run.stage,
        branch=run.branch,
        status=run.status,
        environment=run.environment,
        runtime_adapter=state.runtime_adapter.value if state.runtime_adapter is not None else None,
        provider=state.provider.value if state.provider is not None else None,
        model=state.model,
        reasoning_effort=state.reasoning_effort.value if state.reasoning_effort is not None else None,
        log_url=_task_run_log_url(run),
        error_message=run.error_message,
        output=run.output,
        state=run.state or {},
        artifacts=run.artifacts or [],
        created_at=run.created_at,
        updated_at=run.updated_at,
        completed_at=run.completed_at,
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


def get_task_id_for_run(run_id: str | UUID, team_id: int) -> UUID | None:
    """The parent task id for a run, team-scoped. ``None`` if the run isn't found for the team.

    A lightweight ``task_run_id -> task_id`` resolution (no DTO build) for callers that only
    need to deep-link a run to its task.
    """
    return TaskRun.objects.filter(id=run_id, team_id=team_id).values_list("task_id", flat=True).first()


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


# --- Task automations (presentation CRUD) ---
# Visibility mirrors the task-run visibility filter traversed via the automation's ``task`` FK
# (creator, legacy unowned tasks, and signals-pipeline tasks). Most read fields proxy off the
# linked ``Task``; the schedule (Temporal) is kept in sync from inside the write functions.


def _task_automation_to_dto(automation: TaskAutomation) -> contracts.TaskAutomationDTO:
    return contracts.TaskAutomationDTO(
        id=automation.id,
        name=automation.name,
        prompt=automation.prompt,
        repository=automation.repository,
        github_integration=automation.github_integration_id,
        cron_expression=automation.cron_expression,
        timezone=automation.timezone,
        template_id=automation.template_id,
        enabled=automation.enabled,
        last_run_at=automation.last_run_at,
        last_run_status=automation.last_run_status,
        last_task_id=str(automation.task_id),
        last_task_run_id=str(automation.last_task_run_id) if automation.last_task_run_id else None,
        last_error=automation.last_error,
        created_at=automation.created_at,
        updated_at=automation.updated_at,
    )


def _visible_task_automations(team_id: int, user_id: int | None):
    return TaskAutomation.objects.filter(task__team_id=team_id).filter(task_run_visibility_q(user_id))


def list_task_automations(team_id: int, user_id: int | None) -> list[contracts.TaskAutomationDTO]:
    """Automations for the team visible to the user, ordered by task title then newest first."""
    automations = _visible_task_automations(team_id, user_id).order_by("task__title", "-created_at")
    return [_task_automation_to_dto(automation) for automation in automations]


def get_task_automation(
    automation_id: str | UUID, team_id: int, user_id: int | None
) -> contracts.TaskAutomationDTO | None:
    """A single automation visible to the user. Returns ``None`` if not found/visible."""
    automation = _visible_task_automations(team_id, user_id).filter(pk=automation_id).first()
    return _task_automation_to_dto(automation) if automation is not None else None


def create_task_automation(
    team_id: int,
    user_id: int | None,
    *,
    name: str,
    prompt: str,
    repository: str,
    github_integration_id: int | None = None,
    cron_expression: str,
    timezone: str = "UTC",
    template_id: str | None = None,
    enabled: bool = True,
) -> contracts.TaskAutomationDTO:
    """Create an automation (and its backing task) and sync its Temporal schedule.

    Falls back to the team's default GitHub integration when none is supplied, mirroring the
    original serializer behavior.
    """
    if github_integration_id is None:
        default_integration = Integration.objects.filter(team_id=team_id, kind="github").first()
        github_integration_id = default_integration.id if default_integration else None

    with transaction.atomic():
        task = Task.objects.create(
            team_id=team_id,
            created_by_id=user_id,
            title=name,
            description=prompt,
            origin_product=Task.OriginProduct.AUTOMATION,
            repository=repository,
            github_integration_id=github_integration_id,
        )
        automation = TaskAutomation.objects.create(
            task=task,
            cron_expression=cron_expression,
            timezone=timezone,
            template_id=template_id,
            enabled=enabled,
        )

    _sync_automation_schedule(automation)
    return _task_automation_to_dto(automation)


def update_task_automation(
    automation_id: str | UUID, team_id: int, user_id: int | None, **fields
) -> contracts.TaskAutomationDTO | None:
    """Partially update a visible automation (and its backing task) and re-sync its schedule.

    Returns ``None`` if the automation is not found/visible. The ``github_integration_id``
    key (when present) updates the backing task's GitHub integration.
    """
    automation = _visible_task_automations(team_id, user_id).filter(pk=automation_id).first()
    if automation is None:
        return None

    task_field_map = {
        "name": "title",
        "prompt": "description",
        "repository": "repository",
        "github_integration_id": "github_integration_id",
    }
    task_updates = {task_field_map[key]: fields.pop(key) for key in list(fields) if key in task_field_map}

    with transaction.atomic():
        for key, value in fields.items():
            setattr(automation, key, value)
        automation.save()

        if task_updates:
            task = automation.task
            fields_to_update = []
            for field, value in task_updates.items():
                if getattr(task, field) != value:
                    setattr(task, field, value)
                    fields_to_update.append(field)
            if fields_to_update:
                fields_to_update.append("updated_at")
                task.save(update_fields=fields_to_update)

    _sync_automation_schedule(automation)
    return _task_automation_to_dto(automation)


def delete_task_automation(automation_id: str | UUID, team_id: int, user_id: int | None) -> bool:
    """Delete a visible automation and its Temporal schedule. Returns whether a row was deleted."""
    automation = _visible_task_automations(team_id, user_id).filter(pk=automation_id).first()
    if automation is None:
        return False

    from products.tasks.backend.automation_service import (  # noqa: PLC0415 — keep temporalio off the api import path
        delete_automation_schedule,
    )

    delete_automation_schedule(automation)
    automation.delete()
    return True


def run_task_automation_now(
    automation_id: str | UUID, team_id: int, user_id: int | None
) -> contracts.TaskAutomationDTO | None:
    """Trigger an automation run immediately and return the refreshed automation DTO.

    Returns ``None`` if the automation is not found/visible.
    """
    automation = _visible_task_automations(team_id, user_id).filter(pk=automation_id).first()
    if automation is None:
        return None

    from products.tasks.backend.automation_service import (  # noqa: PLC0415 — keep temporalio off the api import path
        run_task_automation,
    )

    run_task_automation(str(automation.id))
    automation.refresh_from_db()
    return _task_automation_to_dto(automation)


def _sync_automation_schedule(automation: TaskAutomation) -> None:
    from products.tasks.backend.automation_service import (  # noqa: PLC0415 — keep temporalio off the api import path
        sync_automation_schedule,
    )

    sync_automation_schedule(automation)


# --- Task runs (presentation lifecycle) ---
# Every function takes ids/primitives and returns a TaskRunDetailDTO (or a small result),
# moving all ORM access and Temporal/Slack/S3 orchestration behind the facade. Visibility on
# the parent task is enforced via ``task_visibility_q``; runs are always team-scoped.

# Run-state keys that are server-owned and must never be mutable through the PATCH endpoint:
#   - github_credential_source / pr_authorship_mode fix the run's GitHub identity at creation;
#     a caller could otherwise flip a caller-token run to ``server_integration`` and have the
#     task creator's server-side token injected into their sandbox.
#   - sandbox_id is the credential-propagation target; a caller could otherwise repoint a visible
#     run at a sandbox they control and capture the run owner's token on the next rotation.
#   - sandbox_cpu_cores / sandbox_memory_gb / sandbox_ttl_seconds / inactivity_timeout_seconds set
#     the run's compute and lifetime at creation; a caller could otherwise PATCH a queued run to
#     provision an oversized or long-lived sandbox beyond what they're entitled to.
# All are written only server-side (run creation + the temporal workflow), never via PATCH.
_PROTECTED_RUN_STATE_KEYS = frozenset(
    {
        "github_credential_source",
        "pr_authorship_mode",
        "sandbox_id",
        "sandbox_cpu_cores",
        "sandbox_memory_gb",
        "sandbox_ttl_seconds",
        "inactivity_timeout_seconds",
    }
)

_TERMINAL_TASK_RUN_STATUSES = (TaskRun.Status.COMPLETED, TaskRun.Status.FAILED, TaskRun.Status.CANCELLED)


def _task_run_queryset():
    return TaskRun.objects.select_related(
        "task", "task__created_by", "task__github_integration", "task__github_user_integration"
    )


def _get_task_for_run_visibility(task_id: str | UUID, team_id: int, user_id: int | None) -> Task | None:
    return Task.objects.filter(id=task_id, team_id=team_id).filter(task_visibility_q(user_id)).first()


def _get_visible_run(run_id: str | UUID, task_id: str | UUID, team_id: int) -> TaskRun | None:
    """A run scoped to its parent task + team. Caller is responsible for task visibility."""
    return _task_run_queryset().filter(pk=run_id, team_id=team_id, task_id=task_id).first()


def task_accessible_for_run_view(
    task_id: str | UUID, team_id: int, user_id: int | None, *, bypass_visibility: bool = False
) -> bool:
    """Whether the parent task exists and (unless bypassed) is visible to the user.

    Mirrors the parent-task gate in ``TaskRunViewSet.safely_get_queryset``: runs are always scoped
    to a task, and access to that task is gated by ``task_visibility_q`` except for internal-debug
    read actions, which the caller signals via ``bypass_visibility``.
    """
    task_filter = Task.objects.filter(id=task_id, team_id=team_id)
    if not bypass_visibility:
        task_filter = task_filter.filter(task_visibility_q(user_id))
    return task_filter.exists()


def list_task_runs(task_id: str | UUID, team_id: int) -> list[contracts.TaskRunDetailDTO]:
    """All runs for a task, team-scoped. Caller enforces task visibility."""
    runs = _task_run_queryset().filter(team_id=team_id, task_id=task_id)
    return [_task_run_detail_to_dto(run) for run in runs]


def get_task_run_detail(run_id: str | UUID, task_id: str | UUID, team_id: int) -> contracts.TaskRunDetailDTO | None:
    """A single run as a detail DTO, scoped to its task + team."""
    run = _get_visible_run(run_id, task_id, team_id)
    return _task_run_detail_to_dto(run) if run is not None else None


def get_task_run_stream_info(
    run_id: str | UUID, task_id: str | UUID, team_id: int
) -> contracts.TaskRunStreamInfoDTO | None:
    """The minimal run facts the SSE stream view needs. ``None`` if the run isn't found."""
    from products.tasks.backend.metrics import (  # noqa: PLC0415 — keep prometheus deps off the api import path
        origin_product_label,
    )

    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return None
    return contracts.TaskRunStreamInfoDTO(
        id=run.id,
        state=run.state or {},
        origin_product=origin_product_label(run),
    )


def signal_workflow_completion(run_id: str | UUID, status: str, error_message: str | None) -> None:
    """Send a completion signal to a run's Temporal workflow (best-effort)."""
    import asyncio  # noqa: PLC0415 — only needed when signalling

    from posthog.temporal.common.client import sync_connect  # noqa: PLC0415 — keep temporalio off the api import path

    from products.tasks.backend.temporal.process_task.workflow import (  # noqa: PLC0415 — keep temporalio off the api import path
        ProcessTaskWorkflow,
    )

    run = TaskRun.objects.filter(pk=run_id).first()
    if run is None:
        return
    try:
        client = sync_connect()
        handle = client.get_workflow_handle(run.workflow_id)
        asyncio.run(handle.signal(ProcessTaskWorkflow.complete_task, args=[status, error_message]))
        logger.info("Signaled workflow completion for task run %s with status %s", run.id, status)
    except Exception as e:
        logger.warning("Failed to signal workflow completion for task run %s: %s", run.id, e)


def _post_slack_update_for_pr(run: TaskRun) -> None:
    pr_url = (run.output or {}).get("pr_url") if isinstance(run.output, dict) else None
    if not pr_url:
        return

    from products.slack_app.backend.models import (  # noqa: PLC0415 — cross-product import kept off the api import path
        SlackThreadTaskMapping,
    )
    from products.tasks.backend.temporal.process_task.activities.post_slack_update import (  # noqa: PLC0415 — keep temporalio off the api import path
        PostSlackUpdateInput,
        post_slack_update,
    )

    try:
        mapping = (
            SlackThreadTaskMapping.objects.filter(task_run=run)
            .order_by("-updated_at")
            .values("integration_id", "channel", "thread_ts", "mentioning_slack_user_id")
            .first()
        )
        if not mapping:
            return
        post_slack_update(
            PostSlackUpdateInput(
                run_id=str(run.id),
                slack_thread_context={
                    "integration_id": mapping["integration_id"],
                    "channel": mapping["channel"],
                    "thread_ts": mapping["thread_ts"],
                    "mentioning_slack_user_id": mapping["mentioning_slack_user_id"],
                },
            )
        )
    except Exception:
        logger.exception("task_run_slack_update_for_pr_failed for run %s", run.id)


def update_task_run(
    run_id: str | UUID, task_id: str | UUID, team_id: int, *, validated_data: dict
) -> contracts.TaskRunDetailDTO | None:
    """Apply a PATCH to a run: merge output/state, set completion, then dispatch side effects.

    Mirrors ``TaskRunViewSet.partial_update`` byte-for-byte: protected state keys are stripped,
    output/state merges take a row lock, terminal transitions signal Temporal + dispatch
    push/Slack updates after commit, and a cloud→local transition cancels the workflow.
    """
    from products.tasks.backend.automation_service import (  # noqa: PLC0415 — keep temporalio off the api import path
        update_automation_run_result,
    )

    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return None

    validated_data = dict(validated_data)
    has_output_merge = "output" in validated_data and isinstance(validated_data["output"], dict)
    has_state_merge = "state" in validated_data and isinstance(validated_data["state"], dict)
    if has_state_merge:
        validated_data["state"] = {
            k: v for k, v in validated_data["state"].items() if k not in _PROTECTED_RUN_STATE_KEYS
        }
    state_remove_keys = [
        k for k in (validated_data.get("state_remove_keys") or []) if k not in _PROTECTED_RUN_STATE_KEYS
    ]
    has_state_mutation = has_state_merge or bool(state_remove_keys)
    update_fields: set[str] = set()

    with transaction.atomic():
        if has_output_merge or has_state_mutation:
            run = TaskRun.objects.select_for_update().get(pk=run.pk)

        old_status = run.status
        old_environment = run.environment
        old_pr_url = (run.output or {}).get("pr_url") if isinstance(run.output, dict) else None

        for key, value in validated_data.items():
            if key == "output" and isinstance(value, dict):
                existing_output = run.output if isinstance(run.output, dict) else {}
                setattr(run, key, {**existing_output, **value})
                update_fields.add(key)
                continue
            if key == "state_remove_keys":
                continue
            if key == "state" and has_state_merge:
                existing_state = run.state if isinstance(run.state, dict) else {}
                next_state = dict(existing_state)
                for remove_key in state_remove_keys:
                    next_state.pop(remove_key, None)
                next_state.update(value)
                setattr(run, key, next_state)
                update_fields.add(key)
                continue
            setattr(run, key, value)
            update_fields.add(key)

        if state_remove_keys and not has_state_merge:
            existing_state = run.state if isinstance(run.state, dict) else {}
            next_state = dict(existing_state)
            for remove_key in state_remove_keys:
                next_state.pop(remove_key, None)
            run.state = next_state
            update_fields.add("state")

        new_status = validated_data.get("status")
        if new_status in _TERMINAL_TASK_RUN_STATUSES:
            if not run.completed_at:
                run.completed_at = django_timezone.now()
                update_fields.add("completed_at")

        update_fields.add("updated_at")
        run.save(update_fields=list(update_fields))
        run.publish_stream_state_event()

    update_automation_run_result(run)

    if new_status in _TERMINAL_TASK_RUN_STATUSES and old_status != new_status:
        signal_workflow_completion(run.id, new_status, validated_data.get("error_message"))
        if new_status == TaskRun.Status.CANCELLED:
            from products.tasks.backend.push_dispatcher import (  # noqa: PLC0415 — keep push deps off the api import path
                notify_task_run_cancelled,
            )

            notify_task_run_cancelled(run)
    new_environment = validated_data.get("environment")
    if new_environment == "local" and old_environment == TaskRun.Environment.CLOUD:
        signal_workflow_completion(run.id, "cancelled", "handoff")

    new_pr_url = (run.output or {}).get("pr_url") if isinstance(run.output, dict) else None
    if new_pr_url and new_pr_url != old_pr_url:
        _post_slack_update_for_pr(run)

    return _task_run_detail_to_dto(run)


def validate_set_output(run_id: str | UUID, task_id: str | UUID, team_id: int, *, output: dict) -> str | None:
    """Validate output against the task's json_schema. Returns an error message or ``None``."""
    import jsonschema  # noqa: PLC0415 — only needed when a json_schema is set

    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return None
    task = run.task
    if task.json_schema:
        try:
            jsonschema.validate(instance=output, schema=task.json_schema)
        except jsonschema.ValidationError as e:
            return f"Output validation error: {e.message}"
    return None


def set_task_run_output(
    run_id: str | UUID, task_id: str | UUID, team_id: int, *, output: dict
) -> contracts.TaskRunDetailDTO | None:
    """Persist a run's output. Completes the run for structured-output tasks; posts Slack PR update."""
    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return None
    task = run.task
    run.output = output
    run.save(update_fields=["output", "updated_at"])
    if task.json_schema:
        signal_workflow_completion(run.id, TaskRun.Status.COMPLETED, None)
    run.publish_stream_state_event()
    _post_slack_update_for_pr(run)
    return _task_run_detail_to_dto(run)


def append_task_run_log(
    run_id: str | UUID, task_id: str | UUID, team_id: int, *, entries: list[dict]
) -> contracts.TaskRunDetailDTO | None:
    """Append log entries to a run's S3 log and heartbeat its workflow."""
    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return None
    run.append_log(entries)
    run.heartbeat_workflow(agent_active=True)
    return _task_run_detail_to_dto(run)


def task_run_has_slack_mapping(run_id: str | UUID, task_id: str | UUID, team_id: int) -> bool | None:
    """Whether a run is mapped to a Slack thread. ``None`` if the run isn't found."""
    from products.slack_app.backend.models import (  # noqa: PLC0415 — cross-product import kept off the api import path
        SlackThreadTaskMapping,
    )

    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return None
    return SlackThreadTaskMapping.objects.filter(task_run=run).exists()


def task_run_is_terminal(run_id: str | UUID, task_id: str | UUID, team_id: int) -> bool | None:
    """Whether a run is in a terminal state. ``None`` if the run isn't found."""
    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return None
    return run.is_terminal


# --- Task run artifacts (S3 + manifest) ---


def _build_artifact_storage_path(run: TaskRun, artifact_id: str, name: str) -> tuple[str, str]:
    from products.tasks.backend.logic.services.staged_artifacts import (  # noqa: PLC0415 — keep storage deps off the api import path
        get_safe_artifact_name,
    )

    safe_name = get_safe_artifact_name(name)
    prefix = run.get_artifact_s3_prefix()
    return safe_name, f"{prefix}/{artifact_id[:8]}_{safe_name}"


def _tag_artifact_object(run: TaskRun, storage_path: str) -> None:
    from posthog.storage import object_storage  # noqa: PLC0415 — keep storage deps off the api import path

    try:
        object_storage.tag(storage_path, {"ttl_days": "30", "team_id": str(run.team_id)})
    except Exception as exc:
        logger.warning(
            "task_run.artifact_tag_failed",
            extra={"task_run_id": str(run.id), "storage_path": storage_path, "error": str(exc)},
        )


def _build_artifact_manifest_entry(
    *,
    artifact_id: str,
    name: str,
    artifact_type: str,
    source: str,
    size: int,
    content_type: str,
    storage_path: str,
    uploaded_at: str,
) -> dict[str, str | int]:
    return {
        "id": artifact_id,
        "name": name,
        "type": artifact_type,
        "source": source,
        "size": size,
        "content_type": content_type,
        "storage_path": storage_path,
        "uploaded_at": uploaded_at,
    }


def _find_artifact_manifest_entry(manifest: list[dict], artifact_id: str, storage_path: str) -> dict | None:
    return next(
        (e for e in manifest if e.get("id") == artifact_id or e.get("storage_path") == storage_path),
        None,
    )


def _save_artifact_manifest(run: TaskRun, manifest: list[dict]) -> None:
    run.artifacts = manifest
    run.save(update_fields=["artifacts", "updated_at"])


def upload_task_run_artifacts(
    run_id: str | UUID, task_id: str | UUID, team_id: int, *, artifacts: list[dict]
) -> list[dict] | None:
    """Write artifact bytes to S3 and append them to the run manifest. Returns the full manifest."""
    import uuid as uuid_module  # noqa: PLC0415

    from posthog.storage import object_storage  # noqa: PLC0415 — keep storage deps off the api import path

    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return None

    uploaded: list[dict] = []
    for artifact in artifacts:
        artifact_id = uuid_module.uuid4().hex
        safe_name, storage_path = _build_artifact_storage_path(run, artifact_id, artifact["name"])

        content_bytes = artifact["content_bytes"]
        extras: dict[str, str] = {}
        content_type = artifact.get("content_type")
        if content_type:
            extras["ContentType"] = content_type

        object_storage.write(storage_path, content_bytes, extras or None)
        _tag_artifact_object(run, storage_path)

        uploaded.append(
            _build_artifact_manifest_entry(
                artifact_id=artifact_id,
                name=safe_name,
                artifact_type=artifact["type"],
                source=artifact.get("source") or "",
                size=len(content_bytes),
                content_type=content_type or "",
                storage_path=storage_path,
                uploaded_at=django_timezone.now().isoformat(),
            )
        )
        logger.info(
            "task_run.artifact_uploaded",
            extra={
                "task_run_id": str(run.id),
                "storage_path": storage_path,
                "artifact_type": artifact["type"],
                "size": len(content_bytes),
            },
        )

    with transaction.atomic():
        run = TaskRun.objects.select_for_update().get(pk=run.pk)
        manifest = list(run.artifacts or [])
        manifest.extend(uploaded)
        _save_artifact_manifest(run, manifest)

    return manifest


def prepare_task_run_artifact_uploads(
    run_id: str | UUID,
    task_id: str | UUID,
    team_id: int,
    *,
    artifacts: list[dict],
    upload_expiration_seconds: int,
    form_overhead_bytes: int,
) -> tuple[list[dict] | None, bool]:
    """Reserve S3 keys and presigned POST forms for direct artifact uploads.

    Returns ``(prepared, ok)``: ``(None, _)`` when the run isn't found, ``(None, False)`` when a
    presigned POST could not be generated, else ``(prepared, True)``.
    """
    import uuid as uuid_module  # noqa: PLC0415

    from posthog.storage import object_storage  # noqa: PLC0415 — keep storage deps off the api import path

    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return None, True

    prepared: list[dict] = []
    for artifact in artifacts:
        artifact_id = uuid_module.uuid4().hex
        safe_name, storage_path = _build_artifact_storage_path(run, artifact_id, artifact["name"])
        content_type = artifact.get("content_type") or ""
        conditions: list[list[str | int]] = [["content-length-range", 0, artifact["size"] + form_overhead_bytes]]

        presigned_post = object_storage.get_presigned_post(
            storage_path, conditions=conditions, expiration=upload_expiration_seconds
        )
        if not presigned_post:
            return None, False

        prepared.append(
            {
                "id": artifact_id,
                "name": safe_name,
                "type": artifact["type"],
                "source": artifact.get("source") or "",
                "size": artifact["size"],
                "content_type": content_type,
                "storage_path": storage_path,
                "expires_in": upload_expiration_seconds,
                "presigned_post": presigned_post,
            }
        )
    return prepared, True


def finalize_task_run_artifact_uploads(
    run_id: str | UUID, task_id: str | UUID, team_id: int, *, artifacts: list[dict]
) -> tuple[list[dict] | None, str | None]:
    """Verify directly-uploaded S3 objects and attach them to the run manifest.

    Returns ``(finalized_entries, error)``: ``(None, None)`` when the run isn't found,
    ``(None, error_message)`` on a validation failure, else ``(finalized_entries, None)``.
    """
    from posthog.storage import object_storage  # noqa: PLC0415 — keep storage deps off the api import path

    from products.tasks.backend.logic.services.staged_artifacts import (  # noqa: PLC0415 — keep storage deps off the api import path
        get_safe_artifact_name,
    )
    from products.tasks.backend.presentation.serializers import (  # noqa: PLC0415 — pure size helpers, kept off the api import path
        build_task_run_artifact_size_error,
        get_task_run_artifact_max_size_bytes,
    )

    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return None, None

    manifest = list(run.artifacts or [])
    artifact_prefix = f"{run.get_artifact_s3_prefix()}/"
    finalized_entries: list[dict] = []
    new_storage_paths: list[str] = []

    for artifact in artifacts:
        artifact_id = artifact["id"]
        storage_path = artifact["storage_path"]

        if not storage_path.startswith(artifact_prefix) or f"/{artifact_id[:8]}_" not in storage_path:
            return None, "Artifact storage path is invalid for this run"

        existing_entry = _find_artifact_manifest_entry(manifest, artifact_id, storage_path)
        if existing_entry is not None:
            finalized_entries.append(existing_entry)
            continue

        s3_object = object_storage.head_object(storage_path)
        if not s3_object:
            return None, "Artifact upload not found in object storage"

        safe_name = get_safe_artifact_name(artifact["name"])
        content_type = artifact.get("content_type") or s3_object.get("ContentType") or ""
        content_length = s3_object.get("ContentLength")
        if not isinstance(content_length, int):
            return None, "Artifact upload metadata is unavailable"

        max_size_bytes = get_task_run_artifact_max_size_bytes(safe_name, content_type, artifact.get("type"))
        if content_length > max_size_bytes:
            return None, build_task_run_artifact_size_error(safe_name, max_size_bytes)

        entry = _build_artifact_manifest_entry(
            artifact_id=artifact_id,
            name=safe_name,
            artifact_type=artifact["type"],
            source=artifact.get("source") or "",
            size=content_length,
            content_type=content_type,
            storage_path=storage_path,
            uploaded_at=django_timezone.now().isoformat(),
        )
        manifest.append(entry)
        finalized_entries.append(entry)
        new_storage_paths.append(storage_path)

    _save_artifact_manifest(run, manifest)
    for storage_path in new_storage_paths:
        _tag_artifact_object(run, storage_path)

    return finalized_entries, None


def presign_task_run_artifact(
    run_id: str | UUID, task_id: str | UUID, team_id: int, *, storage_path: str
) -> tuple[str | None, str | None]:
    """Presign a download URL for an artifact on the run.

    Returns ``(url, error)``: ``(None, None)`` if the run isn't found, ``(None, "not_found")`` if
    the artifact isn't on the run, ``(None, "unavailable")`` if presigning fails, else ``(url, None)``.
    """
    from posthog.storage import object_storage  # noqa: PLC0415 — keep storage deps off the api import path

    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return None, None

    artifacts = run.artifacts or []
    if not any(artifact.get("storage_path") == storage_path for artifact in artifacts):
        return None, "not_found"

    url = object_storage.get_presigned_url(storage_path)
    if not url:
        return None, "unavailable"
    return url, None


def read_task_run_artifact(
    run_id: str | UUID, task_id: str | UUID, team_id: int, *, storage_path: str
) -> tuple[bytes | None, dict | None, str | None]:
    """Read artifact bytes for download, walking the resume chain.

    Returns ``(content, artifact_entry, error)``. ``error`` is one of ``None`` (run not found),
    ``"not_found"`` (artifact not on the run/chain), ``"read_failed"`` (storage read raised), or
    ``"content_missing"`` (object absent). On success returns ``(content, artifact_entry, None)``.
    """
    from posthog.storage import object_storage  # noqa: PLC0415 — keep storage deps off the api import path

    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return None, None, None

    artifact = run.find_artifact_in_resume_chain(storage_path)
    if artifact is None:
        return None, None, "not_found"

    try:
        content = object_storage.read_bytes(storage_path, missing_ok=True)
    except Exception:
        logger.exception(
            "task_run.artifact_download_failed",
            extra={"task_run_id": str(run.id), "storage_path": storage_path},
        )
        return None, artifact, "read_failed"

    if content is None:
        return None, artifact, "content_missing"
    return content, artifact, None


def read_task_run_logs(run_id: str | UUID, task_id: str | UUID, team_id: int) -> str | None:
    """Concatenated JSONL logs across the run's resume chain (oldest ancestor first)."""
    from posthog.storage import object_storage  # noqa: PLC0415 — keep storage deps off the api import path

    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return None

    parts: list[str] = []
    for ancestor in run.get_resume_chain():
        chunk = object_storage.read(ancestor.log_url, missing_ok=True) or ""
        if chunk:
            if not chunk.endswith("\n"):
                chunk = chunk + "\n"
            parts.append(chunk)
    return "".join(parts)


def read_task_run_session_log_content(run_id: str | UUID, task_id: str | UUID, team_id: int) -> str | None:
    """Raw session-log JSONL for a run. ``None`` if the run isn't found."""
    from posthog.storage import object_storage  # noqa: PLC0415 — keep storage deps off the api import path

    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return None
    return object_storage.read(run.log_url, missing_ok=True) or ""


def create_task_run_connection_token(
    run_id: str | UUID, task_id: str | UUID, team_id: int, *, user_id: int, distinct_id: str
) -> str | None:
    """Mint a sandbox connection token for a run. ``None`` if the run isn't found."""
    from products.tasks.backend.logic.services.connection_token import (  # noqa: PLC0415 — keep sandbox deps off the api import path
        create_sandbox_connection_token as _create,
    )

    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return None
    return _create(task_run=run, user_id=user_id, distinct_id=distinct_id)


# --- Task run commands (user_message signal + sandbox proxy) ---


def validate_task_run_artifact_ids(
    run_id: str | UUID, task_id: str | UUID, team_id: int, *, artifact_ids: list[str]
) -> tuple[list[str], bool]:
    """Resolve artifact ids for a run. Returns ``(missing_ids, found)``; ``found=False`` if the run isn't found."""
    from products.tasks.backend.logic.services.staged_artifacts import (  # noqa: PLC0415 — keep storage deps off the api import path
        get_task_run_artifacts_by_id,
    )

    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return [], False
    _, missing_artifact_ids = get_task_run_artifacts_by_id(run, artifact_ids)
    return missing_artifact_ids, True


def signal_task_run_user_message(
    run_id: str | UUID, task_id: str | UUID, team_id: int, *, content: str | None, artifact_ids: list[str]
) -> bool | None:
    """Queue a user_message follow-up signal on the run's workflow.

    Returns ``True`` on success, ``False`` if signalling failed, ``None`` if the run isn't found.
    """
    from products.tasks.backend.temporal.client import (  # noqa: PLC0415 — keep temporalio off the api import path
        signal_task_followup_message,
    )

    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return None
    try:
        signal_task_followup_message(run.workflow_id, content, artifact_ids)
    except Exception:
        logger.exception("Failed to signal follow-up message for task run %s", run.id)
        return False
    return True


def get_task_run_sandbox_connection(
    run_id: str | UUID, task_id: str | UUID, team_id: int, *, user_id: int, distinct_id: str
) -> contracts.TaskRunSandboxConnectionDTO | None:
    """Sandbox connection details for proxying a command. ``None`` if the run isn't found.

    ``sandbox_url`` is ``None`` when the run has no active sandbox (no connection token is minted
    in that case).
    """
    from products.tasks.backend.logic.services.connection_token import (  # noqa: PLC0415 — keep sandbox deps off the api import path
        create_sandbox_connection_token as _create,
    )
    from products.tasks.backend.temporal.process_task.utils import (  # noqa: PLC0415 — keep temporalio off the api import path
        parse_run_state,
    )

    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return None

    run_state = parse_run_state(run.state)
    if not run_state.sandbox_url:
        return contracts.TaskRunSandboxConnectionDTO(sandbox_url=None, sandbox_connect_token=None)

    connection_token = _create(task_run=run, user_id=user_id, distinct_id=distinct_id)
    return contracts.TaskRunSandboxConnectionDTO(
        sandbox_url=run_state.sandbox_url,
        sandbox_connect_token=run_state.sandbox_connect_token,
        connection_token=connection_token,
    )


# --- Task run relay (Slack) ---


def relay_task_run_message(
    run_id: str | UUID, task_id: str | UUID, team_id: int, *, text: str
) -> tuple[str, str | None]:
    """Queue a Slack relay workflow for a run message.

    Returns ``(status, relay_id)`` where status is ``"accepted"`` (relay_id set), ``"skipped"``
    (run not found / terminal / no Slack mapping / empty text), or ``"failed"``.
    """
    from products.slack_app.backend.models import (  # noqa: PLC0415 — cross-product import kept off the api import path
        SlackThreadTaskMapping,
    )
    from products.tasks.backend.temporal.client import (  # noqa: PLC0415 — keep temporalio off the api import path
        execute_posthog_code_agent_relay_workflow,
    )

    run = _get_visible_run(run_id, task_id, team_id)
    if run is None or run.is_terminal:
        return "skipped", None
    if not SlackThreadTaskMapping.objects.filter(task_run=run).exists():
        return "skipped", None

    trimmed = text.strip()
    if not trimmed:
        return "skipped", None

    try:
        relay_id = execute_posthog_code_agent_relay_workflow(run_id=str(run.id), text=trimmed, delete_progress=True)
    except Exception:
        logger.exception("task_run_relay_message_enqueue_failed", extra={"run_id": str(run.id)})
        return "failed", None
    return "accepted", relay_id


# --- Task run creation / start / cloud resume ---


def _ensure_task_team_github_integration(task: Task) -> bool:
    if task.github_integration_id is not None:
        return True
    github_integration = Integration.objects.filter(team_id=task.team_id, kind="github").first()
    if github_integration is None:
        return False
    task.github_integration = github_integration
    task.save(update_fields=["github_integration", "updated_at"])
    return True


def _resolve_cloud_pr_authorship_mode(
    task: Task,
    *,
    pr_authorship_mode,
    request_user_id: int | None,
    github_user_token: str | None,
):
    """Resolve the effective PR-authorship mode for a cloud run.

    Returns ``(mode, error)``: ``error`` is a ``TaskRunValidationError`` when authorship can't be
    established (mode is then ``None``); otherwise ``error`` is ``None`` and ``mode`` is the
    resolved value. Mirrors the original view helper exactly.
    """
    from products.tasks.backend.temporal.process_task.utils import (  # noqa: PLC0415 — keep temporalio off the api import path
        PrAuthorshipMode,
        resolve_user_github_integration_for_task,
        user_github_integration_is_usable,
    )

    if pr_authorship_mode != PrAuthorshipMode.USER or github_user_token:
        return pr_authorship_mode, None

    if task.created_by_id != request_user_id:
        return None, contracts.TaskRunValidationError(
            kind="validation_error",
            code="github_authorization_required",
            detail="User-authored runs must be started by the task creator, or provide github_user_token.",
            attr="pr_authorship_mode",
        )

    user_github_integration = resolve_user_github_integration_for_task(task, allow_refresh=False)
    if user_github_integration is not None and user_github_integration_is_usable(user_github_integration):
        if task.github_user_integration_id != user_github_integration.integration.id:
            task.github_user_integration = user_github_integration.integration
            task.save(update_fields=["github_user_integration", "updated_at"])
        return PrAuthorshipMode.USER, None

    if _ensure_task_team_github_integration(task):
        return PrAuthorshipMode.BOT, None

    return None, contracts.TaskRunValidationError(
        kind="validation_error",
        code="github_authorization_required",
        detail="Link a GitHub account with repo access before running user-authored cloud tasks.",
        attr="pr_authorship_mode",
    )


def _github_credential_source_extra_state(pr_authorship_mode, github_user_token: str | None) -> dict[str, str]:
    from products.tasks.backend.temporal.process_task.utils import (  # noqa: PLC0415 — keep temporalio off the api import path
        GitHubCredentialSource,
        PrAuthorshipMode,
    )

    if pr_authorship_mode != PrAuthorshipMode.USER:
        return {}
    source = GitHubCredentialSource.CALLER_TOKEN if github_user_token else GitHubCredentialSource.SERVER_INTEGRATION
    return {"github_credential_source": source.value}


def bootstrap_task_run(
    task_id: str | UUID, team_id: int, user_id: int | None, *, validated_data: dict
) -> contracts.TaskRunCreateResult | None:
    """Create a task run (without starting execution) from validated bootstrap data.

    Returns ``None`` if the task isn't found/visible (the view raises 404). Otherwise returns a
    ``TaskRunCreateResult`` carrying either the created run DTO or a structured validation error.
    Mirrors ``TaskRunViewSet.create`` byte-for-byte (minus the usage gate, which the view applies).
    """
    from products.tasks.backend.temporal.process_task.utils import (  # noqa: PLC0415 — keep temporalio off the api import path
        PrAuthorshipMode,
        RunSource,
        cache_github_user_token,
        get_provider_for_runtime_adapter,
        get_reasoning_effort_error,
    )

    task = _get_task_for_run_visibility(task_id, team_id, user_id)
    if task is None:
        return None

    mode = validated_data.get("mode", "background")
    environment = validated_data.get("environment", TaskRun.Environment.LOCAL)
    branch = validated_data.get("branch")
    sandbox_environment_id = validated_data.get("sandbox_environment_id")
    pr_authorship_mode = validated_data.get("pr_authorship_mode")
    run_source = validated_data.get("run_source")
    signal_report_id = validated_data.get("signal_report_id")
    runtime_adapter = validated_data.get("runtime_adapter")
    model = validated_data.get("model")
    reasoning_effort = validated_data.get("reasoning_effort")
    github_user_token = validated_data.get("github_user_token")
    initial_permission_mode = validated_data.get("initial_permission_mode")
    if run_source == RunSource.SIGNAL_REPORT:
        pr_authorship_mode = PrAuthorshipMode.BOT

    extra_state: dict | None = None
    if initial_permission_mode is not None:
        extra_state = {"initial_permission_mode": initial_permission_mode}

    provider = get_provider_for_runtime_adapter(runtime_adapter)
    for key, value in {
        "pr_base_branch": branch,
        "pr_authorship_mode": pr_authorship_mode,
        "run_source": run_source,
        "signal_report_id": signal_report_id,
        "runtime_adapter": runtime_adapter,
        "provider": provider,
        "model": model,
        "reasoning_effort": reasoning_effort,
    }.items():
        if value is not None:
            extra_state = extra_state or {}
            extra_state[key] = value.value if hasattr(value, "value") else value

    reasoning_effort_error = get_reasoning_effort_error(
        runtime_adapter=runtime_adapter, model=model, reasoning_effort=reasoning_effort
    )
    if reasoning_effort_error is not None:
        return contracts.TaskRunCreateResult(
            error=contracts.TaskRunValidationError(
                kind="validation_error", code="invalid_input", detail=reasoning_effort_error, attr="reasoning_effort"
            )
        )

    pr_authorship_mode, validation_error = _resolve_cloud_pr_authorship_mode(
        task,
        pr_authorship_mode=pr_authorship_mode,
        request_user_id=user_id,
        github_user_token=github_user_token,
    )
    if validation_error is not None:
        return contracts.TaskRunCreateResult(error=validation_error)
    if pr_authorship_mode is not None:
        extra_state = extra_state or {}
        extra_state["pr_authorship_mode"] = (
            pr_authorship_mode.value if hasattr(pr_authorship_mode, "value") else pr_authorship_mode
        )

    if credential_source := _github_credential_source_extra_state(pr_authorship_mode, github_user_token):
        extra_state = extra_state or {}
        extra_state.update(credential_source)

    if sandbox_environment_id is not None:
        sandbox_environment = SandboxEnvironment.get_accessible_for_task(
            environment_id=sandbox_environment_id,
            team_id=task.team_id,
            task_created_by_id=task.created_by_id,
        )
        if sandbox_environment is None:
            return contracts.TaskRunCreateResult(
                error=contracts.TaskRunValidationError(kind="detail", detail="Invalid sandbox_environment_id")
            )
        extra_state = extra_state or {}
        extra_state["sandbox_environment_id"] = str(sandbox_environment.id)
        logger.info(
            "Applying sandbox environment to task run",
            extra={
                "task_id": str(task.id),
                "sandbox_environment_id": str(sandbox_environment.id),
                "sandbox_environment_name": sandbox_environment.name,
                "network_access_level": sandbox_environment.network_access_level,
            },
        )

    logger.info(
        "Creating task run for task %s with mode=%s, branch=%s, environment=%s", task.id, mode, branch, environment
    )
    run = task.create_run(environment=environment, mode=mode, branch=branch, extra_state=extra_state)

    if github_user_token and pr_authorship_mode == PrAuthorshipMode.USER:
        cache_github_user_token(str(run.id), github_user_token)

    return contracts.TaskRunCreateResult(run=_task_run_detail_to_dto(_task_run_queryset().get(pk=run.pk)))


def _trigger_task_processing_workflow(
    task: Task, run: TaskRun, user_id: int | None, *, raise_on_error: bool = False
) -> None:
    from products.tasks.backend.temporal.client import (  # noqa: PLC0415 — keep temporalio off the api import path
        execute_task_processing_workflow,
    )
    from products.tasks.backend.temporal.process_task.utils import (  # noqa: PLC0415 — keep temporalio off the api import path
        RunSource,
        parse_run_state,
    )

    full_mcp_run_sources = frozenset({None, RunSource.MANUAL})
    run_source = parse_run_state(run.state).run_source
    posthog_mcp_scopes = "full" if run_source in full_mcp_run_sources else "read_only"
    try:
        logger.info("Attempting to trigger task processing workflow for task %s, run %s", task.id, run.id)
        execute_task_processing_workflow(
            task_id=str(task.id),
            run_id=str(run.id),
            team_id=task.team.id,
            user_id=user_id,
            posthog_mcp_scopes=posthog_mcp_scopes,
        )
        logger.info("Workflow trigger completed for task %s, run %s", task.id, run.id)
    except Exception as e:
        logger.exception("Failed to trigger task processing workflow for task %s, run %s: %s", task.id, run.id, e)
        if raise_on_error:
            raise


# Statuses from which a cloud run may be started via the start endpoint.
_STARTABLE_TASK_RUN_STATUSES = (TaskRun.Status.NOT_STARTED, TaskRun.Status.QUEUED)


def check_task_run_startable(run_id: str | UUID, task_id: str | UUID, team_id: int) -> str:
    """Whether a run can be started via the start endpoint.

    Returns ``"not_found"`` (run missing), ``"not_cloud"``, ``"bad_status:<current>"``, or
    ``"ok"``. The usage gate (429) is applied by the view between this check and ``start_task_run``.
    """
    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return "not_found"
    if run.environment != TaskRun.Environment.CLOUD:
        return "not_cloud"
    if run.status not in _STARTABLE_TASK_RUN_STATUSES:
        return f"bad_status:{run.status}"
    return "ok"


def start_task_run(
    run_id: str | UUID, task_id: str | UUID, team_id: int, user_id: int | None, *, validated_data: dict
) -> tuple[str, UUID | None]:
    """Apply run-scoped attachments and trigger the cloud workflow for a startable run.

    Caller must have already verified startability and applied the usage gate. Returns
    ``(outcome, task_id)``: ``"not_found"``, ``"missing_artifacts:<csv>"``, or ``"started"``
    (``task_id`` set). Rolls back any pending-state writes on failure (re-raising), mirroring
    the original view.
    """
    from products.tasks.backend.logic.services.staged_artifacts import (  # noqa: PLC0415 — keep storage deps off the api import path
        get_task_run_artifacts_by_id,
    )

    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return "not_found", None
    task = run.task

    pending_user_message = validated_data.get("pending_user_message")
    pending_user_artifact_ids = validated_data.get("pending_user_artifact_ids") or []

    if pending_user_artifact_ids:
        _, missing_artifact_ids = get_task_run_artifacts_by_id(run, pending_user_artifact_ids)
        if missing_artifact_ids:
            return "missing_artifacts:" + ",".join(missing_artifact_ids), None

    state_updates: dict = {}
    if pending_user_message is not None:
        state_updates["pending_user_message"] = pending_user_message
    if pending_user_artifact_ids:
        state_updates["pending_user_artifact_ids"] = pending_user_artifact_ids

    previous_state = dict(run.state or {})
    try:
        if state_updates:
            TaskRun.update_state_atomic(run.id, updates=state_updates)
            run.refresh_from_db()
        logger.info("Triggering workflow for task %s, existing run %s", task.id, run.id)
        _trigger_task_processing_workflow(task, run, user_id, raise_on_error=True)
    except Exception:
        if state_updates:
            rollback_updates = {
                key: previous_state[key] for key in state_updates.keys() if key in previous_state
            } or None
            rollback_remove_keys = [key for key in state_updates.keys() if key not in previous_state] or None
            TaskRun.update_state_atomic(run.id, updates=rollback_updates, remove_keys=rollback_remove_keys)
        raise

    return "started", task.id


def resume_task_run_in_cloud(
    run_id: str | UUID, task_id: str | UUID, team_id: int, user_id: int | None
) -> tuple[str, contracts.TaskRunDetailDTO | None, str | None]:
    """Resume a run in a cloud sandbox, terminating any prior workflow.

    Returns ``(outcome, run_dto, debug_use_modal)``. ``outcome`` is one of: ``"not_found"``,
    ``"already_active"`` (400), ``"auth_error:<detail>"`` (400, github auth), ``"workflow_failed"``
    (502), or ``"resumed"`` (run_dto set). Mirrors ``TaskRunViewSet.resume_in_cloud``.
    """
    from django.conf import settings  # noqa: PLC0415

    from products.tasks.backend.temporal.client import (  # noqa: PLC0415 — keep temporalio off the api import path
        resume_task_in_cloud_workflow,
    )
    from products.tasks.backend.temporal.process_task.utils import (  # noqa: PLC0415 — keep temporalio off the api import path
        PrAuthorshipMode,
        get_pr_authorship_mode,
    )

    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return "not_found", None, None

    logger.info(
        "resume_in_cloud_called",
        extra={
            "task_run_id": str(run.id),
            "task_id": str(run.task_id),
            "prior_status": run.status,
            "prior_environment": run.environment,
            "prior_state_keys": sorted((run.state or {}).keys()),
            "prior_snapshot_external_id": (run.state or {}).get("snapshot_external_id"),
            "use_modal_resume_snapshots": settings.TASKS_USE_MODAL_RESUME_SNAPSHOTS,
        },
    )

    with transaction.atomic():
        run = (
            TaskRun.objects.select_for_update(of=("self",))
            .select_related("task", "task__created_by", "task__github_integration", "task__github_user_integration")
            .get(pk=run.pk)
        )

        is_cloud_active = run.environment == TaskRun.Environment.CLOUD and run.status in (
            TaskRun.Status.QUEUED,
            TaskRun.Status.IN_PROGRESS,
        )
        if is_cloud_active:
            return "already_active", None, None

        if get_pr_authorship_mode(run.task, run.state) == PrAuthorshipMode.USER:
            pr_authorship_mode, validation_error = _resolve_cloud_pr_authorship_mode(
                run.task,
                pr_authorship_mode=PrAuthorshipMode.USER,
                request_user_id=user_id,
                github_user_token=None,
            )
            if validation_error is not None:
                return f"auth_error:{validation_error.detail}", None, None
            if pr_authorship_mode is not None:
                run.state = {
                    **(run.state or {}),
                    "pr_authorship_mode": (
                        pr_authorship_mode.value if hasattr(pr_authorship_mode, "value") else pr_authorship_mode
                    ),
                }

        prior_status = run.status
        prior_environment = run.environment
        prior_completed_at = run.completed_at
        prior_state = dict(run.state or {})
        run.prepare_for_cloud_handoff()

    logger.info("Resuming task run in cloud", extra={"task_run_id": str(run.id), "task_id": str(run.task_id)})

    try:
        resume_task_in_cloud_workflow(str(run.id), run.workflow_id)
    except Exception as e:
        logger.exception("Failed to trigger handoff workflow", extra={"task_run_id": str(run.id), "error": str(e)})
        with transaction.atomic():
            run = TaskRun.objects.select_for_update().get(pk=run.pk)
            run.status = prior_status
            run.environment = prior_environment
            run.completed_at = prior_completed_at
            run.state = prior_state
            run.error_message = "Failed to start cloud workflow"
            run.save(update_fields=["status", "environment", "completed_at", "state", "error_message", "updated_at"])
        run.publish_stream_state_event()
        return "workflow_failed", None, None

    return "resumed", _task_run_detail_to_dto(run), None


# --- Code workflow config (presentation CRUD) ---
# A user's per-team binding configuration. Reads seed a default config on first access;
# saves are optimistic-locked on ``version`` and validate the bindings before persisting.


def _epoch_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _code_workflow_config_to_dto(config: CodeWorkflowConfig) -> contracts.CodeWorkflowConfigDTO:
    return contracts.CodeWorkflowConfigDTO(
        id=str(config.id),
        version=config.version,
        updated_at=config.updated_at,
        bindings=config.bindings,
    )


def get_code_workflow_config(team_id: int, user_id: int) -> contracts.CodeWorkflowConfigDTO:
    """Return the user's config for the team, seeding a default one on first access."""
    config, _ = CodeWorkflowConfig.objects.get_or_create(
        team_id=team_id,
        user_id=user_id,
        defaults={"bindings": build_default_bindings(), "version": 1},
    )
    return _code_workflow_config_to_dto(config)


def save_code_workflow_bindings(
    team_id: int, user_id: int, *, bindings: dict, expected_version: object
) -> contracts.CodeWorkflowSaveResult:
    """Validate and save bindings under optimistic locking.

    Returns a ``conflict`` result when ``expected_version`` is not an int or does not match
    the stored version, an ``invalid`` result (with diagnostics) when validation fails, or a
    ``saved`` result with the version-bumped config.
    """
    with transaction.atomic():
        current, _ = CodeWorkflowConfig.objects.select_for_update().get_or_create(
            team_id=team_id,
            user_id=user_id,
            defaults={"bindings": build_default_bindings(), "version": 1},
        )
        if not isinstance(expected_version, int) or current.version != expected_version:
            return contracts.CodeWorkflowSaveResult(
                outcome=CODE_WORKFLOW_CONFLICT,
                config=_code_workflow_config_to_dto(current),
            )

        result = validate_bindings(bindings)
        if not result.can_save:
            return contracts.CodeWorkflowSaveResult(
                outcome=CODE_WORKFLOW_INVALID,
                config=_code_workflow_config_to_dto(current),
                diagnostics=[
                    contracts.CodeWorkflowDiagnosticDTO(
                        severity=d.severity,
                        code=d.code,
                        message=d.message,
                        situation_id=d.situation_id,
                        action_id=d.action_id,
                    )
                    for d in result.diagnostics
                ],
            )

        current.bindings = bindings
        current.version = current.version + 1
        current.save(update_fields=["bindings", "version", "updated_at"])

    return contracts.CodeWorkflowSaveResult(
        outcome=CODE_WORKFLOW_SAVED,
        config=_code_workflow_config_to_dto(current),
    )


def reset_code_workflow_bindings(team_id: int, user_id: int) -> contracts.CodeWorkflowConfigDTO:
    """Reset the user's bindings back to the defaults and bump the version."""
    with transaction.atomic():
        config, _ = CodeWorkflowConfig.objects.select_for_update().get_or_create(
            team_id=team_id,
            user_id=user_id,
            defaults={"bindings": build_default_bindings(), "version": 1},
        )
        config.bindings = build_default_bindings()
        config.version = config.version + 1
        config.save(update_fields=["bindings", "version", "updated_at"])
    return _code_workflow_config_to_dto(config)


# --- Code home board ---
# Active agents are computed live off in-flight runs; workstreams are persisted by the
# worker and split into board columns by their stored ``state``.


def _code_home_workstream_to_dto(ws: CodeWorkstream) -> contracts.CodeHomeWorkstreamDTO:
    return contracts.CodeHomeWorkstreamDTO(
        id=ws.key,
        repo_name=ws.repo_name,
        repo_full_path=ws.repo_full_path,
        branch=ws.branch,
        pr_url=ws.pr_url,
        pr=ws.pr,
        primary_situation=ws.primary_situation,
        last_activity_at=_epoch_ms(ws.last_activity_at),
        tasks=[
            contracts.CodeHomeWorkstreamTaskDTO(
                id=t.get("id"),
                title=t.get("title"),
                status=t.get("status"),
                is_generating=False,
                needs_permission=False,
            )
            for t in (ws.tasks or [])
        ],
        situations=ws.situations or [],
    )


def _code_home_active_agents(team_id: int, user_id: int) -> list[contracts.CodeHomeActiveAgentDTO]:
    cutoff = django_timezone.now() - CODE_HOME_ACTIVE_AGENT_WINDOW
    runs = (
        TaskRun.objects.filter(
            team_id=team_id,
            task__created_by_id=user_id,
            task__archived=False,
            task__deleted=False,
            status__in=_CODE_HOME_RUNNING_STATUSES,
            updated_at__gte=cutoff,
        )
        .select_related("task")
        .order_by("-updated_at")
    )

    seen_tasks: set[str] = set()
    agents: list[contracts.CodeHomeActiveAgentDTO] = []
    for run in runs.iterator():
        task = run.task
        if str(task.id) in seen_tasks:
            continue
        if (run.output or {}).get("pr_url"):
            continue
        seen_tasks.add(str(task.id))
        agents.append(
            contracts.CodeHomeActiveAgentDTO(
                task_id=str(task.id),
                title=task.title,
                repo_name=task.repository.split("/")[-1] if task.repository else None,
                branch=run.branch,
                status=run.status,
                last_activity_at=_epoch_ms(run.updated_at),
                needs_permission=False,
                cloud_pr_url=None,
            )
        )
    return agents


def get_code_home(team_id: int, user_id: int) -> contracts.CodeHomeDTO:
    """Assemble the code-home board: live active agents plus persisted workstreams by column."""
    workstreams = CodeWorkstream.objects.filter(team_id=team_id, user_id=user_id)
    needs_attention: list[contracts.CodeHomeWorkstreamDTO] = []
    in_progress: list[contracts.CodeHomeWorkstreamDTO] = []
    for ws in workstreams.iterator():
        dto = _code_home_workstream_to_dto(ws)
        if ws.state == CodeWorkstream.WorkstreamState.ATTENTION:
            needs_attention.append(dto)
        else:
            in_progress.append(dto)

    return contracts.CodeHomeDTO(
        active_agents=_code_home_active_agents(team_id, user_id),
        needs_attention=needs_attention,
        in_progress=in_progress,
    )


def refresh_team_code_workstreams(team_id: int) -> bool:
    """Trigger an on-demand evaluation of the team's code workstreams.

    Returns whether a new evaluation workflow was started (``False`` if one was already
    running).
    """
    from products.tasks.backend.temporal.code_workstreams.client import (  # noqa: PLC0415 — keep temporalio off the api import path
        trigger_team_code_workstreams_evaluation,
    )

    return trigger_team_code_workstreams_evaluation(team_id)


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
