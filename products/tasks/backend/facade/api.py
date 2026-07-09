"""
Facade API for the tasks product — the data surface other apps may import.

Responsibilities:
- Accept ids / DTOs as input.
- Call into the product's models and logic.
- Convert Django models to DTOs before returning — never return ORM instances.
- Stay thin and stable.

This module is deliberately light: it imports the models and small helpers only. The
heavy behavioral surfaces (sandbox provisioning, warming, the multi-turn agent machinery,
temporal workflows, max tools) live in sibling facade submodules (``sandbox``, ``warm``,
``agents``, ``temporal``, ``max_tools``, ``webhooks``, ``streams``, ``repo_selection``) so a
config-only importer never drags docker/temporalio onto the ``django.setup()`` path.
Functions that bridge to those heavy surfaces import them lazily inside the function body.
"""

import re
import logging
import secrets
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import CharField, Count, Exists, F, Min, OuterRef, Q, QuerySet, Subquery
from django.db.models.fields.json import KeyTextTransform
from django.utils import timezone as django_timezone

import posthoganalytics

from posthog.event_usage import groups
from posthog.models import Team, User
from posthog.models.integration import Integration

from products.tasks.backend.constants import (
    MAX_CUSTOM_IMAGES_PER_TEAM,
    MAX_CUSTOM_IMAGES_PER_USER,
    RESERVED_SANDBOX_ENVIRONMENT_VARIABLE_KEYS,
    is_blocked_sandbox_env_key,
)
from products.tasks.backend.logic.code_workstreams.default_workflow import build_default_bindings
from products.tasks.backend.logic.code_workstreams.validation import validate_bindings
from products.tasks.backend.logic.services.image_builder import (
    ensure_image_builder_task,
    is_custom_images_enabled,
    read_spec_from_builder_sandbox,
)
from products.tasks.backend.mentions import resolve_mentioned_user_ids
from products.tasks.backend.models import (
    Channel,
    CodeInvite,
    CodeInviteRedemption,
    CodeWorkflowConfig,
    CodeWorkstream,
    SandboxCustomImage,
    SandboxEnvironment,
    SandboxSnapshot,
    Task,
    TaskAutomation,
    TaskRun,
    TaskThreadMessage,
    TaskThreadMessageMention,
)
from products.tasks.backend.prompts import WIZARD_HEAD_BRANCH_PREFIX, build_wizard_pr_agent_prompt
from products.tasks.backend.visibility import task_control_q, task_run_visibility_q, task_visibility_q

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
    "beacon_task_presence",
    "bootstrap_task_run",
    "check_task_run_startable",
    "collect_task_run_state_metrics",
    "compute_repository_readiness",
    "create_and_run_task",
    "create_completed_sandbox_snapshot",
    "create_run",
    "create_sandbox_connection_token",
    "build_sandbox_custom_image",
    "create_sandbox_custom_image",
    "create_sandbox_environment",
    "create_task",
    "create_task_automation",
    "create_task_without_run",
    "create_task_run_connection_token",
    "create_task_run_stream_read_token",
    "resolve_stream_base_url",
    "claim_and_fail_stale_run",
    "delete_sandbox_custom_image",
    "delete_sandbox_environment",
    "ensure_sandbox_custom_image_builder_task",
    "delete_task_automation",
    "fail_task_run",
    "finalize_task_run_artifact_uploads",
    "finalize_task_staged_artifacts",
    "get_code_home",
    "get_code_workflow_config",
    "get_conversation_task_dtos",
    "get_latest_pr_url_by_task",
    "get_latest_run_by_task",
    "get_resume_snapshot_carry_state",
    "get_sandbox_custom_image",
    "get_sandbox_environment",
    "get_sandbox_snapshot",
    "get_stale_prewarmed_queued_task_run_ids",
    "get_stale_queued_task_run_ids",
    "get_task_automation",
    "get_task_detail",
    "get_task_id_for_run",
    "get_task_run",
    "get_task_run_detail",
    "get_task_run_sandbox_connection",
    "capture_relay_command_telemetry",
    "get_task_run_stream_info",
    "get_task_summaries",
    "is_internal_debug_team",
    "is_task_controllable_by_user",
    "is_valid_sandbox_env_var_key",
    "latest_task_run_pr_url_subquery",
    "leave_task_presence",
    "list_sandbox_custom_images",
    "list_sandbox_environments",
    "sandbox_custom_images_enabled",
    "list_task_automations",
    "list_task_repositories",
    "list_task_runs",
    "list_tasks",
    "prepare_task_run_artifact_uploads",
    "prepare_task_staged_artifacts",
    "presign_task_run_artifact",
    "read_task_run_artifact",
    "read_task_run_logs",
    "redeem_code_invite",
    "redispatch_task_run",
    "refresh_team_code_workstreams",
    "relay_task_run_message",
    "reset_code_workflow_bindings",
    "resolve_slack_thread_context",
    "resume_task_run_in_cloud",
    "run_task",
    "run_task_automation_now",
    "save_code_workflow_bindings",
    "send_cancel",
    "send_user_message",
    "select_repository_for_message",
    "set_task_run_output",
    "set_task_title",
    "signal_report_queryset",
    "signal_task_run_user_message",
    "signal_workflow_completion",
    "soft_delete_task",
    "start_task_run",
    "task_accessible_for_run_view",
    "task_exists",
    "task_ids_with_pr_url_subquery",
    "task_run_has_slack_mapping",
    "task_run_is_terminal",
    "task_visible",
    "update_sandbox_environment",
    "update_task",
    "update_task_automation",
    "update_task_run",
    "update_task_run_state",
    "upsert_internal_sandbox_env",
    "validate_set_output",
    "validate_task_run_artifact_ids",
    "warm_task_sandbox",
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


class _LatestRunUnset:
    pass


_LATEST_RUN_UNSET = _LatestRunUnset()


def _task_detail_to_dto(
    task: Task,
    *,
    include_latest_run: bool = True,
    latest_run: TaskRun | None | _LatestRunUnset = _LATEST_RUN_UNSET,
) -> contracts.TaskDetailDTO:
    """Map a ``Task`` to its HTTP detail DTO."""
    if not include_latest_run:
        resolved_latest_run = None
    elif isinstance(latest_run, _LatestRunUnset):
        resolved_latest_run = task.latest_run
    else:
        resolved_latest_run = latest_run
    latest_run_id = getattr(task, "_latest_run_id", None)
    if latest_run_id is None and resolved_latest_run is not None:
        latest_run_id = resolved_latest_run.id
    return contracts.TaskDetailDTO(
        id=task.id,
        task_number=task.task_number,
        slug=task.slug,
        title=task.title,
        title_manually_set=task.title_manually_set,
        description=task.description,
        origin_product=task.origin_product,
        repository=task.repository,
        github_integration=task.github_integration_id,
        github_user_integration=task.github_user_integration_id,
        signal_report=task.signal_report_id,
        json_schema=task.json_schema,
        internal=task.internal,
        archived=task.archived,
        archived_at=task.archived_at,
        ci_prompt=task.ci_prompt,
        latest_run=_task_run_detail_to_dto(resolved_latest_run) if resolved_latest_run is not None else None,
        created_at=task.created_at,
        updated_at=task.updated_at,
        created_by=_user_basic_info(task.created_by if task.created_by_id else None),
        latest_run_id=latest_run_id,
        channel=task.channel_id,
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
        custom_image_id=env.custom_image_id,
        custom_image_name=env.custom_image.name if env.custom_image else None,
        custom_image_status=env.custom_image.status if env.custom_image else None,
    )


def _sandbox_snapshot_to_dto(snapshot: SandboxSnapshot) -> contracts.SandboxSnapshotDTO:
    return contracts.SandboxSnapshotDTO(
        id=snapshot.id,
        external_id=snapshot.external_id,
        status=snapshot.status,
        repos=list(snapshot.repos or []),
    )


# --- Reads ---


def get_resume_snapshot_carry_state(run_state: dict[str, Any] | None) -> dict[str, Any]:
    """State keys a successor run must merge (whole dict, never ``snapshot_external_id`` alone)
    to resume from a prior run's sandbox snapshot; empty when there is no usable snapshot."""
    from products.tasks.backend.temporal.process_task.utils import (  # noqa: PLC0415 — keep temporalio off the api import path
        parse_run_state,
    )

    return parse_run_state(run_state).resume_snapshot_carry_state()


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


def count_in_progress_runs_for_github_integration(team_id: int, integration_id: int) -> int:
    """In-progress runs whose task uses this team GitHub integration.

    Used by core's integration API to block disconnecting a GitHub integration while
    live runs still depend on it for credential refresh — deleting the row SET_NULLs
    ``Task.github_integration`` and permanently orphans every live sandbox's token.
    """
    return TaskRun.objects.filter(
        team_id=team_id,
        status=TaskRun.Status.IN_PROGRESS,
        task__github_integration_id=integration_id,
    ).count()


def is_task_controllable_by_user(task_id: str | UUID, user_id: int | None) -> bool:
    """Whether the user may mutate the task under the task control rules.

    Tasks belong to their creator, plus team-wide signal-pipeline tasks and legacy unowned
    tasks. Used by core's file-system flow to gate delete/restore on a filed task; public-channel
    read visibility deliberately does not qualify.
    """
    return Task.objects.filter(task_control_q(user_id), pk=task_id).exists()


def get_sandbox_snapshot(snapshot_id: str | UUID) -> contracts.SandboxSnapshotDTO | None:
    """Fetch a sandbox snapshot as a DTO."""
    snapshot = SandboxSnapshot.objects.filter(id=snapshot_id).first()
    return _sandbox_snapshot_to_dto(snapshot) if snapshot is not None else None


def get_tasks_by_ids(task_ids: Iterable[str | UUID], team_ids: Iterable[int]) -> list[contracts.TaskDTO]:
    """Tasks matching the supplied ids, restricted to ``team_ids``.

    For multi-team callers (e.g. the Slack App Home Tasks card) that already resolved the
    set of accessible teams upstream and need a bulk DTO fetch in one query.
    """
    ids = [str(t) for t in task_ids]
    teams = list(team_ids)
    if not ids or not teams:
        return []
    return [_task_to_dto(task) for task in Task.objects.filter(id__in=ids, team_id__in=teams)]


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


def task_ids_with_pr_url_subquery(team_id: int) -> QuerySet[TaskRun, Any]:
    """A ``values('task_id')`` queryset of ``team_id``'s tasks that produced a non-empty ``output.pr_url``.

    For embedding in a caller's ``task_id__in=...`` lookup so the report→PR correlation can be
    *decorrelated*: instead of a per-report ``Exists`` over runs, the caller drives off this small,
    index-backed set (served by the partial ``task_run_output_pr_url_idx``) and joins outward to its
    own report-association tables. Returns a query expression — no ORM instances cross the boundary.

    Scoped to ``team_id`` so the set stays bounded to the request's tenant rather than scanning every
    team's PR-bearing runs — associated runs are always same-team, so this drops no valid matches.
    """
    return (
        TaskRun.objects.filter(team_id=team_id, output__pr_url__isnull=False)
        .exclude(output__pr_url="")
        .values("task_id")
    )


def latest_task_run_pr_url_subquery(*conditions: Q, **task_run_filter) -> Subquery:
    """``Subquery`` of the latest non-empty output.pr_url for runs matching the supplied correlation
    (keyword lookups and/or positional ``Q`` objects). Returns a query expression to embed in the
    caller's queryset — no ORM instances cross the boundary, and the tasks facade stays free of the
    caller's domain."""
    return Subquery(
        TaskRun.objects.filter(*conditions, output__pr_url__isnull=False, **task_run_filter)
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


def get_stale_queued_task_run_ids(
    older_than: timedelta,
    limit: int,
    *,
    created_hard_cap: timedelta | None = None,
    hard_cap_min_queued: timedelta = timedelta(hours=1),
    cloud_only: bool = False,
) -> list[UUID]:
    """Ids of runs stuck in QUEUED, by ``updated_at`` age or an optional ``created_at`` backstop.

    ``cloud_only`` restricts the sweep to cloud-environment runs. Local (desktop) runs sit in
    QUEUED by design while the desktop agent drives them, so dispatch-recovery callers must
    exclude them — cloud-dispatching one hijacks the user's live local session.

    Intentionally cross-team — the janitor sweep runs without a team context.
    """
    now = django_timezone.now()
    stale = Q(updated_at__lt=now - older_than)
    if created_hard_cap is not None:
        stale |= Q(created_at__lt=now - created_hard_cap, updated_at__lt=now - hard_cap_min_queued)
    queryset = TaskRun.objects.filter(status=TaskRun.Status.QUEUED)  # nosemgrep: celery-task-team-scope-audit
    if cloud_only:
        queryset = queryset.filter(environment=TaskRun.Environment.CLOUD)
    return list(queryset.filter(stale).order_by("updated_at").values_list("id", flat=True)[:limit])


def get_stale_prewarmed_queued_task_run_ids(older_than: timedelta, limit: int) -> list[UUID]:
    """Ids of prewarmed runs orphaned in QUEUED — their processing workflow never started, so the
    in-workflow ``WARM_IDLE_TIMEOUT`` (10m) never armed to finalize them.

    A live warm run idles in QUEUED awaiting its first message and self-terminates at
    ``WARM_IDLE_TIMEOUT``, so a prewarmed run still QUEUED well past that window has no workflow
    behind it (dispatch lost — e.g. an ``on_commit`` callback that never ran) and can be reaped
    immediately rather than lingering until the 24h stale sweep. ``older_than`` should sit safely
    above ``WARM_IDLE_TIMEOUT`` so a still-idling warm run is never killed early.

    Intentionally cross-team — the janitor sweep runs without a team context.
    """
    now = django_timezone.now()
    return list(
        TaskRun.objects.filter(  # nosemgrep: celery-task-team-scope-audit
            status=TaskRun.Status.QUEUED,
            state__prewarmed=True,
            updated_at__lt=now - older_than,
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


def create_wizard_cloud_run(
    *,
    team,
    user_id: int,
    repository: str,
    branch: str | None = None,
) -> contracts.CreatedTaskDTO:
    """Create + run a cloud setup-wizard task.

    The workflow runs the published wizard in the sandbox (it integrates PostHog), then the agent
    commits the changes, opens a PR on the user's repo, and keeps it green — it never implements
    PostHog itself (see the wizard PR agent prompt). The wizard authenticates with its own scoped
    token (see ``create_wizard_oauth_access_token``), independent of the agent's sandbox token, so
    the agent runs with read-only PostHog scopes.``wizard_config`` marks the run so the workflow runs the wizard pre-agent step.

    ``user_id`` is the person going through onboarding; it becomes the task's ``created_by`` so the
    run is explicitly attributed to them.

    The PR head branch is generated here (not by the agent) so the GitHub PR webhook can bind the
    opened PR back to this run by branch + repository — wizard PRs are bot-authored, which the
    agent-side PR attribution cannot match.
    """
    head_branch = f"{WIZARD_HEAD_BRANCH_PREFIX}{secrets.token_hex(3)}"
    prompt = build_wizard_pr_agent_prompt(head_branch)
    return create_and_run_task(
        team=team,
        title="Set up PostHog",
        description=prompt,
        origin_product=Task.OriginProduct.ONBOARDING,
        user_id=user_id,
        repository=repository,
        create_pr=True,
        mode="background",
        branch=branch,
        wizard_config={},
        wizard_head_branch=head_branch,
        posthog_mcp_scopes="read_only",
        # The agent server boots idle; this is the message that actually kicks it off once ready
        # (delivered by forward_pending_user_message). Without it the run stalls after "Started agent".
        pending_user_message=prompt,
    )


def create_task_without_run(
    *,
    team,
    user_id: int,
    origin_product: "Task.OriginProduct",
    title: str = "",
    description: str = "",
    repository: str | None = None,
) -> UUID:
    """Create a Task row with no initial run, returning its id.

    For callers that own run creation themselves — e.g. the sandbox warm path, which boots the first
    run via the warming facade. ``team`` is a core ``posthog.Team`` (not a tasks model).
    """
    task = Task.create_without_run(
        team=team,
        title=title,
        description=description,
        origin_product=origin_product,
        user_id=user_id,
        repository=repository,
    )
    return task.id


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


def claim_and_fail_stale_run(run_id: str | UUID, error: str) -> bool:
    """Compare-and-set reap of a stranded run. Returns whether this caller won the claim.

    Atomically flips a run still in ``QUEUED``/``IN_PROGRESS`` to ``FAILED`` via a conditional
    update, so concurrent reapers of the same row resolve to exactly one winner (the losers match
    zero rows). The winner finalizes via ``mark_failed`` (error message, ``completed_at``, stream +
    analytics). Intentionally cross-team (janitor sweep).
    """
    claimed = TaskRun.objects.filter(
        id=run_id,
        status__in=(TaskRun.Status.QUEUED, TaskRun.Status.IN_PROGRESS),
    ).update(status=TaskRun.Status.FAILED)  # nosemgrep: celery-task-team-scope-audit
    if not claimed:
        return False
    run = TaskRun.objects.filter(pk=run_id).first()  # nosemgrep: celery-task-team-scope-audit
    if run is not None:
        run.mark_failed(error)
    return True


def redispatch_task_run(run_id: str | UUID) -> str:
    """Re-dispatch a QUEUED run whose create-time workflow dispatch was lost. Cross-team janitor call.

    Idempotent recover-only wrapper over the temporal client — never fails the run. Returns the
    outcome (``recovered`` / ``already_running`` / ``left_queue`` / ``error``).
    """
    from products.tasks.backend.temporal.client import (  # noqa: PLC0415 — keep temporalio off the api import path
        redispatch_orphaned_task_run,
    )

    return redispatch_orphaned_task_run(str(run_id))


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


def is_blocked_sandbox_env_var_key(key: str) -> bool:
    return is_blocked_sandbox_env_key(key)


def is_reserved_sandbox_env_var_key(key: str) -> bool:
    return key in RESERVED_SANDBOX_ENVIRONMENT_VARIABLE_KEYS


def _validate_user_sandbox_env_vars(environment_variables: dict | None) -> None:
    for key in environment_variables or {}:
        if not SandboxEnvironment.is_valid_env_var_key(key):
            raise ValueError(f"Invalid environment variable key: {key!r}")
        if is_blocked_sandbox_env_key(key) or key in RESERVED_SANDBOX_ENVIRONMENT_VARIABLE_KEYS:
            raise ValueError(f"Environment variable key {key!r} is not allowed")


def _accessible_sandbox_envs(team_id: int, user_id: int):
    return (
        SandboxEnvironment.objects.filter(team_id=team_id)
        .filter(Q(private=False) | Q(created_by_id=user_id))
        .select_related("created_by", "custom_image")
    )


def list_sandbox_environments(team_id: int, user_id: int) -> list[contracts.SandboxEnvironmentDTO]:
    """Non-internal environments visible to the user, for the list view."""
    return [_sandbox_env_to_dto(env) for env in _accessible_sandbox_envs(team_id, user_id).filter(internal=False)]


def get_sandbox_environment(env_id: str | UUID, team_id: int, user_id: int) -> contracts.SandboxEnvironmentDTO | None:
    """A single environment visible to the user (internal ones are retrievable by id)."""
    env = _accessible_sandbox_envs(team_id, user_id).filter(pk=env_id).first()
    return _sandbox_env_to_dto(env) if env is not None else None


def _validate_custom_image_id(team_id: int, user_id: int, custom_image_id: str | UUID | None) -> None:
    if custom_image_id is None:
        return
    if not sandbox_custom_images_enabled(team_id, user_id):
        raise ValueError("Custom sandbox images require the Modal VM runtime, which is not enabled")
    image = SandboxCustomImage.get_accessible_for_task(
        image_id=custom_image_id, team_id=team_id, task_created_by_id=user_id
    )
    if image is None:
        raise ValueError(f"Invalid custom_image_id: {custom_image_id}")


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
    custom_image_id: str | None = None,
) -> contracts.SandboxEnvironmentDTO:
    """Create a team environment owned by the user and return it as a DTO."""
    _validate_user_sandbox_env_vars(environment_variables)
    _validate_custom_image_id(team_id, user_id, custom_image_id)
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
        custom_image_id=custom_image_id,
    )
    return _sandbox_env_to_dto(SandboxEnvironment.objects.select_related("created_by", "custom_image").get(pk=env.pk))


def update_sandbox_environment(
    env_id: str | UUID, team_id: int, user_id: int, **fields
) -> contracts.SandboxEnvironmentDTO | None:
    """Partially update a visible environment. Returns ``None`` if not found/visible."""
    env = _accessible_sandbox_envs(team_id, user_id).filter(pk=env_id).first()
    if env is None:
        return None
    if "environment_variables" in fields:
        _validate_user_sandbox_env_vars(fields["environment_variables"])
    if "custom_image_id" in fields:
        _validate_custom_image_id(team_id, user_id, fields["custom_image_id"])
    for key, value in fields.items():
        setattr(env, key, value)
    env.save()
    return _sandbox_env_to_dto(SandboxEnvironment.objects.select_related("created_by", "custom_image").get(pk=env.pk))


def delete_sandbox_environment(env_id: str | UUID, team_id: int, user_id: int) -> bool:
    """Delete a visible environment. Returns whether a row was deleted."""
    env = _accessible_sandbox_envs(team_id, user_id).filter(pk=env_id).first()
    if env is None:
        return False
    env.delete()
    return True


# --- Sandbox custom images (presentation CRUD + builder/build flows) ---


def sandbox_custom_images_enabled(team_id: int, user_id: int) -> bool:
    """Whether custom base images are available for this team (Modal VM runtime flag gate)."""
    team = Team.objects.only("id", "organization_id").get(id=team_id)
    user = User.objects.only("id", "distinct_id").get(id=user_id)
    return is_custom_images_enabled(
        distinct_id=user.distinct_id or f"user-{user_id}",
        organization_id=str(team.organization_id),
    )


def _custom_image_to_dto(
    image: SandboxCustomImage, *, include_build_log: bool = False
) -> contracts.SandboxCustomImageDTO:
    from products.tasks.backend.logic.services.image_spec import spec_json_to_yaml  # noqa: PLC0415

    return contracts.SandboxCustomImageDTO(
        id=image.id,
        team_id=image.team_id,
        name=image.name,
        description=image.description,
        repository=image.repository,
        private=image.private,
        status=image.status,
        version=image.version,
        modal_image_name=image.modal_image_name,
        error=image.error,
        spec=image.spec or {},
        spec_yaml=spec_json_to_yaml(image.spec or {}),
        scan_result=image.scan_result or {},
        build_log=image.build_log if include_build_log else "",
        builder_task_id=image.builder_task_id,
        created_by=_user_basic_info(image.created_by if image.created_by_id else None),
        created_at=image.created_at,
        updated_at=image.updated_at,
    )


def _accessible_custom_images(team_id: int, user_id: int):
    return (
        SandboxCustomImage.objects.filter(team_id=team_id)
        .filter(Q(private=False) | Q(created_by_id=user_id))
        .select_related("created_by")
    )


def _reload_image_dto(image_pk: UUID) -> contracts.SandboxCustomImageDTO:
    return _custom_image_to_dto(SandboxCustomImage.objects.select_related("created_by").get(pk=image_pk))


def list_sandbox_custom_images(team_id: int, user_id: int) -> list[contracts.SandboxCustomImageDTO]:
    """Non-archived custom images visible to the user, newest first."""
    images = (
        _accessible_custom_images(team_id, user_id)
        .exclude(status=SandboxCustomImage.Status.ARCHIVED)
        .order_by("-created_at")
    )
    return [_custom_image_to_dto(image) for image in images]


def get_sandbox_custom_image(
    image_id: str | UUID, team_id: int, user_id: int
) -> contracts.SandboxCustomImageDTO | None:
    """Single-image detail; the only read that includes the (potentially large) build log."""
    image = _accessible_custom_images(team_id, user_id).filter(id=image_id).first()
    return _custom_image_to_dto(image, include_build_log=True) if image is not None else None


def create_sandbox_custom_image(
    team_id: int,
    user_id: int,
    *,
    name: str,
    description: str = "",
    repository: str | None = None,
    private: bool = False,
) -> contracts.SandboxCustomImageDTO:
    """Create a draft custom image and dispatch its interactive image-builder agent task."""
    from products.tasks.backend.logic.services.image_spec import validate_image_repository  # noqa: PLC0415

    if repository:
        validate_image_repository(repository)

    counts = (
        SandboxCustomImage.objects.filter(team_id=team_id)
        .exclude(status=SandboxCustomImage.Status.ARCHIVED)
        .aggregate(team=Count("id"), user=Count("id", filter=Q(created_by_id=user_id)))
    )
    if counts["team"] >= MAX_CUSTOM_IMAGES_PER_TEAM:
        raise ValueError(f"This team already has {MAX_CUSTOM_IMAGES_PER_TEAM} custom images; delete one first")
    if counts["user"] >= MAX_CUSTOM_IMAGES_PER_USER:
        raise ValueError(f"You already have {MAX_CUSTOM_IMAGES_PER_USER} custom images; delete one first")

    image = SandboxCustomImage.objects.create(
        team_id=team_id,
        created_by_id=user_id,
        name=name,
        description=description,
        repository=repository or "",
        private=private,
    )
    ensure_image_builder_task(image, user_id)
    return _reload_image_dto(image.pk)


def ensure_sandbox_custom_image_builder_task(
    image_id: str | UUID, team_id: int, user_id: int
) -> contracts.SandboxCustomImageDTO | None:
    """Revive (or reuse) the image's builder session; new sessions are seeded with the stored spec."""
    image = _accessible_custom_images(team_id, user_id).filter(id=image_id).first()
    if image is None:
        return None
    ensure_image_builder_task(image, user_id)
    return _reload_image_dto(image.pk)


def build_sandbox_custom_image(
    image_id: str | UUID, team_id: int, user_id: int, *, spec_yaml: str | None = None
) -> contracts.SandboxCustomImageDTO | None:
    """Persist the image spec and kick off the scan → build → publish workflow.

    The spec comes from ``spec_yaml`` when provided, otherwise it is read from the
    builder task's live sandbox. Raises ``ValueError`` on an invalid or empty spec.
    """
    from products.tasks.backend.logic.services.image_spec import (  # noqa: PLC0415
        SandboxImageSpecError,
        parse_image_spec_json,
        parse_image_spec_yaml,
        validate_spec_buildable,
    )
    from products.tasks.backend.temporal.client import execute_build_sandbox_image_workflow  # noqa: PLC0415

    image = _accessible_custom_images(team_id, user_id).filter(id=image_id).first()
    if image is None:
        return None
    if image.status in (SandboxCustomImage.Status.SCANNING, SandboxCustomImage.Status.BUILDING):
        raise ValueError("A build is already in progress for this image")

    try:
        spec = parse_image_spec_yaml(spec_yaml) if spec_yaml is not None else read_spec_from_builder_sandbox(image)
    except SandboxImageSpecError as e:
        # Builder sandbox gone → the stored spec is the only correct rebuild source.
        if spec_yaml is None and image.spec:
            spec = parse_image_spec_json(image.spec)
        else:
            raise ValueError(str(e))
    if spec.is_empty:
        raise ValueError("The image spec is empty; add packages, commands, or env vars before building")
    validate_spec_buildable(spec, image.repository)

    image.spec = spec.model_dump()
    image.status = SandboxCustomImage.Status.SCANNING
    image.error = ""
    image.save(update_fields=["spec", "status", "error", "updated_at"])

    execute_build_sandbox_image_workflow(str(image.id), team_id)
    return _reload_image_dto(image.pk)


def delete_sandbox_custom_image(image_id: str | UUID, team_id: int, user_id: int) -> bool:
    """Delete a visible custom image. Environments referencing it fall back to the default base (SET_NULL)."""
    image = _accessible_custom_images(team_id, user_id).filter(id=image_id).first()
    if image is None:
        return False
    image.delete()
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
#   - use_modal_directory_resume_snapshots is the server-side directory snapshot rollout decision;
#     a caller could otherwise force directory snapshot creation while the feature flag is off.
#   - snapshot_external_id / snapshot_kind / snapshot_mount_path control which Modal image is
#     restored on resume and where directory snapshots are mounted.
# These keys are reserved for server-owned run state, never PATCH input.
_PROTECTED_RUN_STATE_KEYS = frozenset(
    {
        "github_credential_source",
        "pr_authorship_mode",
        "sandbox_id",
        "sandbox_cpu_cores",
        "sandbox_memory_gb",
        "sandbox_ttl_seconds",
        "inactivity_timeout_seconds",
        "wizard_config",
        "wizard_head_branch",
        "use_modal_directory_resume_snapshots",
        "snapshot_external_id",
        "snapshot_kind",
        "snapshot_mount_path",
    }
)

_TERMINAL_TASK_RUN_STATUSES = (TaskRun.Status.COMPLETED, TaskRun.Status.FAILED, TaskRun.Status.CANCELLED)


def _task_run_queryset():
    return TaskRun.objects.select_related(
        "task", "task__created_by", "task__github_integration", "task__github_user_integration"
    )


def _get_task_for_run_control(task_id: str | UUID, team_id: int, user_id: int | None) -> Task | None:
    """The task, only if the user may drive runs on it (``task_control_q``, not mere visibility)."""
    return Task.objects.filter(id=task_id, team_id=team_id).filter(task_control_q(user_id)).first()


def _get_visible_run(run_id: str | UUID, task_id: str | UUID, team_id: int) -> TaskRun | None:
    """A run scoped to its parent task + team. Caller is responsible for task visibility."""
    return _task_run_queryset().filter(pk=run_id, team_id=team_id, task_id=task_id).first()


def task_accessible_for_run_view(
    task_id: str | UUID,
    team_id: int,
    user_id: int | None,
    *,
    bypass_visibility: bool = False,
    for_control: bool = False,
) -> bool:
    """Whether the parent task exists and (unless bypassed) is visible to the user.

    Mirrors the parent-task gate in ``TaskRunViewSet.safely_get_queryset``: runs are always scoped
    to a task, and access to that task is gated by ``task_visibility_q`` except for internal-debug
    read actions, which the caller signals via ``bypass_visibility``. Run-mutating actions pass
    ``for_control`` to use the narrower ``task_control_q`` — public-channel visibility lets
    teammates watch a run, not drive it.
    """
    task_filter = Task.objects.filter(id=task_id, team_id=team_id)
    if not bypass_visibility:
        task_filter = task_filter.filter(task_control_q(user_id) if for_control else task_visibility_q(user_id))
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
    from products.tasks.backend.metrics import (  # noqa: PLC0415 — keep prometheus deps off the api import path
        observe_agent_turn_failed,
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
        if new_status == TaskRun.Status.FAILED:
            observe_agent_turn_failed(run)
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
        # Surface the PR in the run's progress timeline the moment the agent reports it, so the install
        # UI advances past "Started agent" instead of waiting on the 15-min CI follow-up loop to emit
        # these. Steps coalesce by id with the workflow's own pr/ci emissions (frontend mergeProgressStep),
        # so the double-emit is harmless. Tolerant: a logging/stream hiccup must not fail the PATCH.
        try:
            run.emit_progress_event("pr", "completed", "Opened pull request", "setup", detail=new_pr_url)
            run.emit_progress_event("ci", "in_progress", "Keeping CI green", "setup")
        except Exception:
            logger.warning("task_run.pr_progress_emit_failed", extra={"run_id": str(run.id)}, exc_info=True)

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
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": artifact_id,
        "name": name,
        "type": artifact_type,
        "source": source,
        "size": size,
        "content_type": content_type,
        "storage_path": storage_path,
        "uploaded_at": uploaded_at,
    }
    if metadata:
        entry["metadata"] = metadata
    return entry


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
                metadata=artifact.get("metadata"),
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

        prepared_artifact = {
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
        if metadata := artifact.get("metadata"):
            prepared_artifact["metadata"] = metadata
        prepared.append(prepared_artifact)
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
            metadata=artifact.get("metadata"),
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


def create_task_run_stream_read_token(run_id: str | UUID, task_id: str | UUID, team_id: int) -> str | None:
    """Mint a run-scoped token for reading a run's live event stream. ``None`` if the run isn't found."""
    from products.tasks.backend.logic.services.connection_token import (  # noqa: PLC0415 — keep sandbox deps off the api import path
        create_stream_read_token as _create,
    )

    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return None
    return _create(task_run=run)


def resolve_stream_base_url(*, distinct_id: str, organization_id: str | UUID) -> str | None:
    """Agent-proxy base URL for the read leg, or ``None`` to read from Django directly.

    Returns the configured agent-proxy URL only when it is set for this environment AND the
    read-via-proxy flag is enabled for the user, so rollout stays gradual and reversible. The
    server owns this decision; clients just connect to whatever URL comes back.
    """
    from products.tasks.backend.constants import STREAM_VIA_PROXY_FEATURE_FLAG  # noqa: PLC0415

    proxy_url = settings.TASKS_AGENT_PROXY_PUBLIC_URL
    if not proxy_url:
        return None
    # Local dev disables the analytics SDK, so the rollout flag never evaluates; the URL setting
    # is the opt-in there. Prod (DEBUG off) still gates on the flag below.
    if settings.DEBUG:
        return proxy_url
    try:
        enabled = bool(
            posthoganalytics.feature_enabled(
                STREAM_VIA_PROXY_FEATURE_FLAG,
                distinct_id=distinct_id,
                groups={"organization": str(organization_id)},
                group_properties={"organization": {"id": str(organization_id)}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        return None
    return proxy_url if enabled else None


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


# Relay control verbs whose outcome PostHog AI funnels track. Captured here (gated on
# origin_product) so the generic relay stays product-agnostic while the conversation layer stops
# firing them as the renderer drives permission/cancel through `runs/{run}/command/`.
_POSTHOG_AI_RELAY_TELEMETRY_METHODS: frozenset[str] = frozenset({"cancel", "permission_response"})


def capture_relay_command_telemetry(
    run_id: str | UUID,
    task_id: str | UUID,
    team_id: int,
    *,
    method: str,
    params: dict | None,
    success: bool,
) -> None:
    """Emit PostHog AI control-verb telemetry for a relayed agent command.

    Preserves the ``task_run_cancelled`` / ``permission_responded`` funnels once the renderer moves
    permission/cancel onto the generic relay. ``conversation_id`` is intentionally null (the relay
    has no conversation); ``TaskRun.capture_event`` stamps ``origin_product``/``run_id`` so
    generic-task usage stays out of the PostHog AI funnels. Mirrors the old conversation-layer
    semantics: a cancel is recorded only when it actually reached the agent, while a permission
    response is recorded with its forward ``success`` either way.
    """
    if method not in _POSTHOG_AI_RELAY_TELEMETRY_METHODS:
        return
    run = _get_visible_run(run_id, task_id, team_id)
    if run is None or run.task.origin_product != Task.OriginProduct.POSTHOG_AI:
        return

    params = params or {}
    if method == "cancel":
        if not success:
            return
        run.capture_event(
            "task_run_cancelled",
            {
                "execution_type": "sandbox",
                "surface": "relay",
                "conversation_id": None,
                "cancel_source": "user",
            },
        )
        return

    run.capture_event(
        "permission_responded",
        {
            "execution_type": "sandbox",
            "surface": "relay",
            "conversation_id": None,
            "request_id": params.get("requestId"),
            "option_id": params.get("optionId"),
            "success": success,
        },
    )


# --- Task run relay (Slack) ---


def _pick_relay_text(*, text: str, text_parts: list[str] | None) -> str:
    """Pick the text to post. If ``text_parts`` has any non-empty entries,
    the last one wins (that's the post-last-tool-use answer). Otherwise fall
    back to the joined ``text`` field."""
    if text_parts:
        for part in reversed(text_parts):
            if isinstance(part, str) and part.strip():
                return part
    return text


def relay_task_run_message(
    run_id: str | UUID,
    task_id: str | UUID,
    team_id: int,
    *,
    text: str,
    text_parts: list[str] | None = None,
) -> tuple[str, str | None]:
    """Queue a Slack relay workflow for a run message, or under the agent-design
    flag signal the running task workflow to stream the text inline.

    Returns ``(status, relay_id)`` where status is ``"accepted"`` (relay_id set), ``"skipped"``
    (run not found / terminal / no Slack mapping / empty text / streamed inline under the
    agent-design flag), or ``"failed"``.

    When ``text_parts`` is provided the last non-empty entry is used — it's the
    post-last-tool-use answer, and posting only that keeps the interim narration
    ("Let me check…") out of the Slack thread. Older callers still send just
    ``text`` and get the previous behavior unchanged.
    """
    from products.slack_app.backend.models import (  # noqa: PLC0415 — cross-product import kept off the api import path
        SlackThreadTaskMapping,
    )
    from products.tasks.backend.models import TaskRun  # noqa: PLC0415 — keep ORM off the api import path
    from products.tasks.backend.temporal.client import (  # noqa: PLC0415 — keep temporalio off the api import path
        execute_posthog_code_agent_relay_workflow,
        signal_agent_text_delta,
    )
    from products.tasks.backend.temporal.process_task.activities.feature_flags import (  # noqa: PLC0415 — keep temporal off the api import path
        AGENT_DESIGN_STATE_KEY,
    )

    run = _get_visible_run(run_id, task_id, team_id)
    if run is None or run.is_terminal:
        return "skipped", None
    if not SlackThreadTaskMapping.objects.filter(task_run=run).exists():
        return "skipped", None

    posted_text = _pick_relay_text(text=text, text_parts=text_parts)
    trimmed = posted_text.strip()
    if not trimmed:
        return "skipped", None

    if bool((run.state or {}).get(AGENT_DESIGN_STATE_KEY)):
        try:
            signal_agent_text_delta(TaskRun.get_workflow_id(str(run.task_id), str(run.id)), trimmed)
        except Exception:
            logger.exception("task_run_relay_text_signal_failed", extra={"run_id": str(run.id)})
        return "skipped", None

    try:
        relay_id = execute_posthog_code_agent_relay_workflow(run_id=str(run.id), text=trimmed, delete_progress=True)
    except Exception:
        logger.exception("task_run_relay_message_enqueue_failed", extra={"run_id": str(run.id)})
        return "failed", None
    return "accepted", relay_id


# --- Task run creation / start / cloud resume ---


def user_can_author_repository(user_id: int, repository: str) -> bool:
    from products.tasks.backend.temporal.process_task.utils import (  # noqa: PLC0415 — keep temporalio off the api import path
        get_user_github_integration,
        user_github_integration_is_usable,
    )

    user = User.objects.filter(id=user_id).first()
    integration = get_user_github_integration(user, repository=repository, allow_refresh=False)
    return user_github_integration_is_usable(integration)


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

    task = _get_task_for_run_control(task_id, team_id, user_id)
    if task is None:
        return None

    mode = validated_data.get("mode", "background")
    environment = validated_data.get("environment", TaskRun.Environment.LOCAL)
    branch = validated_data.get("branch")
    sandbox_environment_id = validated_data.get("sandbox_environment_id")
    pr_authorship_mode = validated_data.get("pr_authorship_mode")
    auto_publish = validated_data.get("auto_publish")
    run_source = validated_data.get("run_source")
    signal_report_id = validated_data.get("signal_report_id")
    runtime_adapter = validated_data.get("runtime_adapter")
    model = validated_data.get("model")
    reasoning_effort = validated_data.get("reasoning_effort")
    github_user_token = validated_data.get("github_user_token")
    initial_permission_mode = validated_data.get("initial_permission_mode")
    home_quick_action = validated_data.get("home_quick_action")
    if run_source == RunSource.SIGNAL_REPORT:
        pr_authorship_mode = PrAuthorshipMode.BOT

    extra_state: dict | None = None
    if initial_permission_mode is not None:
        extra_state = {"initial_permission_mode": initial_permission_mode}

    provider = get_provider_for_runtime_adapter(runtime_adapter)
    for key, value in {
        "pr_base_branch": branch,
        "pr_authorship_mode": pr_authorship_mode,
        "auto_publish": auto_publish,
        "run_source": run_source,
        "signal_report_id": signal_report_id,
        "runtime_adapter": runtime_adapter,
        "provider": provider,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "home_quick_action": home_quick_action,
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

    custom_image_id = validated_data.get("custom_image_id")
    if custom_image_id is not None:
        custom_image = SandboxCustomImage.get_accessible_for_task(
            image_id=custom_image_id, team_id=task.team_id, task_created_by_id=task.created_by_id
        )
        if custom_image is None:
            return contracts.TaskRunCreateResult(
                error=contracts.TaskRunValidationError(kind="detail", detail="Invalid custom_image_id")
            )
        if not custom_image.is_ready:
            return contracts.TaskRunCreateResult(
                error=contracts.TaskRunValidationError(
                    kind="detail", detail=f"Custom image is not ready (status: {custom_image.status})"
                )
            )
        extra_state = extra_state or {}
        extra_state["custom_image_id"] = str(custom_image.id)

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

    # SIGNAL_REPORT: implementation runs log their work on the report (notes, code references)
    # via the task:write artefact tools.
    full_mcp_run_sources = frozenset({None, RunSource.MANUAL, RunSource.SIGNAL_REPORT})
    run_source = parse_run_state(run.state).run_source
    posthog_mcp_scopes: Literal["read_only", "full"] = "full" if run_source in full_mcp_run_sources else "read_only"
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
            "prior_snapshot_kind": (run.state or {}).get("snapshot_kind"),
            "prior_snapshot_mount_path": (run.state or {}).get("snapshot_mount_path"),
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


# --- Task presentation CRUD + actions ---
# These back the thin ``TaskViewSet``. They mirror the original viewset's querysets
# (team scoping, ``task_visibility_q`` visibility, ordering, filters, annotations) and
# orchestration (title generation, signal-report linkage, workflow triggers, S3 artifact
# staging, presence beacons) byte-for-byte.


def signal_report_queryset():
    """The ``SignalReport`` manager queryset, for the task write serializer's report FK field.

    Kept here so presentation never imports the ``signals`` product's models directly; team
    scoping on the selected report is enforced by the serializer's ``validate_signal_report``.
    """
    from products.signals.backend.models import (  # noqa: PLC0415 — cross-product import kept off the api import path
        SignalReport,
    )

    return SignalReport.objects.all()


def channel_queryset():
    """Live ``Channel`` queryset for the task write serializer's channel FK field.

    Kept here so presentation never imports tasks models directly. Deliberately
    ``unscoped()``: the serializer is also instantiated without team context (e.g.
    drf-spectacular schema generation), where the fail-closed manager would raise.
    Team scoping comes from the serializer's team-scoped field, ownership of
    personal channels from ``validate_channel``.
    """
    return Channel.objects.unscoped().filter(deleted=False)


def is_internal_debug_team(team_id: int | None) -> bool:
    """Whether the team is the PostHog-internal debugging team. Mirrors the original view helper."""
    from django.conf import settings  # noqa: PLC0415

    if settings.DEBUG and not settings.TEST:
        return team_id == 1
    return team_id == 2 and settings.CLOUD_DEPLOYMENT == "US"


def _task_detail_queryset():
    return Task.objects.select_related(
        "created_by", "team", "github_integration", "github_user_integration"
    ).prefetch_related("runs")


def _visible_task_qs(team_id: int, user_id: int | None, *, bypass_visibility: bool = False, for_control: bool = False):
    """Team-scoped live tasks, gated by read visibility — or by the narrower
    control predicate when ``for_control`` (mutations, runs, agent commands)."""
    qs = Task.objects.filter(team_id=team_id, deleted=False)
    if not bypass_visibility:
        qs = qs.filter(task_control_q(user_id) if for_control else task_visibility_q(user_id))
    return qs


def get_task_detail(
    task_id: str | UUID, team_id: int, user_id: int | None, *, bypass_visibility: bool = False
) -> contracts.TaskDetailDTO | None:
    """A single task as a detail DTO, team-scoped and visibility-gated.

    ``bypass_visibility`` mirrors the ``?ph_debug=true`` retrieve path for internal-debug teams.
    """
    task = (
        _visible_task_qs(team_id, user_id, bypass_visibility=bypass_visibility)
        .select_related("created_by", "team", "github_integration", "github_user_integration")
        .prefetch_related("runs")
        .filter(id=task_id)
        .first()
    )
    return _task_detail_to_dto(task) if task is not None else None


def get_conversation_task_dtos(task_ids: Sequence[str | UUID], team_id: int) -> dict[UUID, contracts.TaskDetailDTO]:
    """Task payloads for the Max conversation API, keyed by task id.

    Intentionally team-scoped, with no ``task_visibility_q(user_id)`` gate: the conversation is the
    read-share unit, so anyone who can ``retrieve`` a conversation may read its backing task. Broad
    read here does not grant action — write/send to a task stays creator-gated in the conversation
    viewset (``create``/``open``/``queue``) and at bind time (``validate_task_id``). Direct task reads
    (``get_task_detail``) gate by creator because that is the task-enumeration path; this one is not.

    ``latest_run`` (the nested run payload) stays excluded so conversation lists never presign per-row
    log URLs; instead a single ``latest_run_id`` subquery carries the latest run id, which the frontend
    needs to reconnect to sandbox logs.
    """
    if not task_ids:
        return {}

    latest_run_id_sq = (
        TaskRun.objects.filter(task=OuterRef("pk"), team_id=team_id).order_by("-created_at", "-id").values("id")[:1]
    )
    tasks = (
        Task.objects.filter(team_id=team_id, id__in=task_ids)
        .select_related("created_by", "team")
        .annotate(_latest_run_id=Subquery(latest_run_id_sq))
    )
    return {task.id: _task_detail_to_dto(task, include_latest_run=False) for task in tasks}


def task_visible(task_id: str | UUID, team_id: int, user_id: int | None, *, for_control: bool = False) -> bool:
    """Whether a non-deleted task exists for the team and is visible to the user.

    Mirrors the existence gate ``TaskViewSet.get_object()`` applied (team + ``deleted=False`` +
    ``task_visibility_q``). Used by the ``run`` action to 404 before the usage gate, preserving
    the original ordering; the ``run`` action passes ``for_control`` since starting a run drives
    the task.
    """
    return _visible_task_qs(team_id, user_id, for_control=for_control).filter(id=task_id).exists()


async def select_repository_for_message(team_id: int, user_id: int, message: str, *, origin_product: str) -> str | None:
    """Pick the repository a free-form chat message is most likely about.

    Kept as a lazy facade wrapper so API importers do not load the repo-selection agent or
    sandbox/Temporal dependencies on their request import path.
    """
    from products.tasks.backend.logic.repo_selection.cascade import (  # noqa: PLC0415 — keeps repo-selection agent imports lazy
        select_repository_for_message as select_repository_for_message_impl,
    )

    return await select_repository_for_message_impl(
        team_id, user_id, message, origin_product=Task.OriginProduct(origin_product)
    )


def _list_tasks_queryset(team_id: int, user_id: int | None, *, filters: dict) -> QuerySet[Task]:
    latest_run = TaskRun.objects.filter(task=OuterRef("pk"), team_id=team_id).order_by("-created_at", "-id")
    qs = _visible_task_qs(team_id, user_id).order_by("-created_at", "-id")

    origin_product = filters.get("origin_product")
    if origin_product:
        qs = qs.filter(origin_product=origin_product)

    stage = filters.get("stage")
    if stage:
        stage_run = TaskRun.objects.filter(task=OuterRef("pk"), team_id=team_id, stage=stage)
        qs = qs.filter(Exists(stage_run))

    organization = filters.get("organization")
    repository = filters.get("repository")
    created_by = filters.get("created_by")
    search = filters.get("search")
    status_filter = filters.get("status")

    if repository:
        repo_str = repository.strip().lower()
        if "/" in repo_str:
            qs = qs.filter(repository__iexact=repo_str)
        else:
            qs = qs.filter(repository__iendswith=f"/{repo_str}")

    if organization:
        org_str = organization.strip().lower()
        qs = qs.filter(repository__istartswith=f"{org_str}/")

    if created_by:
        qs = qs.filter(created_by_id=created_by)

    channel = filters.get("channel")
    if channel:
        qs = qs.filter(channel_id=channel)

    if search:
        search_term = search.strip()
        if search_term:
            search_q = Q(title__icontains=search_term) | Q(description__icontains=search_term)
            number_part = search_term.split("-")[-1].strip()
            if number_part.isdigit():
                search_q |= Q(task_number=int(number_part))
            qs = qs.filter(search_q)

    if status_filter:
        latest_run_status = latest_run.values("status")[:1]
        qs = qs.annotate(_latest_run_status=Subquery(latest_run_status)).filter(_latest_run_status=status_filter)

    # `internal` controls default visibility, not access — task visibility (applied above) is the real
    # authorization boundary, open to any team member. `all` returns both, `true` returns only-internal,
    # and the default excludes internal tasks so the main task list stays clean.
    internal_param = filters.get("internal")
    if internal_param == "all":
        pass
    elif internal_param == "true":
        qs = qs.filter(internal=True)
    else:
        qs = qs.filter(internal=False)

    archived_param = filters.get("archived")
    if archived_param == "true":
        qs = qs.filter(archived=True)
    elif archived_param == "all":
        pass
    else:
        qs = qs.filter(archived=False)

    qs = qs.select_related("created_by", "team", "github_integration", "github_user_integration").annotate(
        _latest_run_id=Subquery(latest_run.values("id")[:1])
    )

    return qs


def _latest_runs_by_id(run_ids: Iterable[UUID], team_id: int) -> dict[UUID, TaskRun]:
    unique_run_ids = list(dict.fromkeys(run_ids))
    if not unique_run_ids:
        return {}

    return {run.id: run for run in TaskRun.objects.filter(id__in=unique_run_ids, team_id=team_id)}


def _tasks_to_dtos(tasks: Iterable[Task], team_id: int) -> list[contracts.TaskDetailDTO]:
    task_list = list(tasks)
    latest_run_ids_by_task_id = {
        task.id: latest_run_id
        for task in task_list
        if (latest_run_id := getattr(task, "_latest_run_id", None)) is not None
    }
    latest_runs_by_id = _latest_runs_by_id(latest_run_ids_by_task_id.values(), team_id)

    dtos = []
    for task in task_list:
        latest_run_id = latest_run_ids_by_task_id.get(task.id)
        latest_run = latest_runs_by_id.get(latest_run_id) if latest_run_id is not None else None
        dtos.append(_task_detail_to_dto(task, latest_run=latest_run))
    return dtos


def list_tasks(team_id: int, user_id: int | None, *, filters: dict) -> list[contracts.TaskDetailDTO]:
    """All visible tasks for the team as DTOs, mirroring the task list view filters."""
    return _tasks_to_dtos(_list_tasks_queryset(team_id, user_id, filters=filters), team_id)


def list_task_repositories(team_id: int, user_id: int | None) -> list[str]:
    """Distinct repositories used by non-deleted, non-internal visible tasks for the team."""
    repositories = (
        Task.objects.filter(team_id=team_id, deleted=False, internal=False)
        .filter(task_visibility_q(user_id))
        .exclude(repository__isnull=True)
        .exclude(repository__exact="")
        .values_list("repository", flat=True)
        .distinct()
        .order_by("repository")
    )
    return [repo for repo in repositories if repo is not None]


def get_task_summaries(team_id: int, user_id: int | None, *, ids: list) -> list[contracts.TaskSummaryDTO]:
    """Summary fields for the requested tasks, mirroring ``TaskViewSet.summaries``."""
    from django.db.models.functions import JSONObject  # noqa: PLC0415

    latest_run = (
        TaskRun.objects.filter(task=OuterRef("pk"), team_id=team_id)
        .order_by("-created_at", "-id")
        .annotate(_data=JSONObject(status="status", environment="environment"))
    )
    tasks = (
        Task.objects.filter(team_id=team_id, deleted=False, id__in=ids)
        .filter(task_visibility_q(user_id))
        .annotate(_latest_run=Subquery(latest_run.values("_data")[:1]))
        .order_by("-created_at", "id")
    )
    summaries: list[contracts.TaskSummaryDTO] = []
    for task in tasks:
        raw = getattr(task, "_latest_run", None)
        latest = (
            contracts.TaskLatestRunSummaryDTO(status=raw.get("status"), environment=raw.get("environment"))
            if isinstance(raw, dict)
            else None
        )
        summaries.append(
            contracts.TaskSummaryDTO(
                id=task.id,
                title=task.title,
                repository=task.repository,
                created_at=task.created_at,
                updated_at=task.updated_at,
                origin_product=task.origin_product,
                latest_run=latest,
            )
        )
    return summaries


def compute_repository_readiness(team_id: int, *, repository: str, window_days: int, refresh: bool) -> dict:
    """Autonomy-readiness details for a repository. Thin wrapper over the internal computation."""
    from posthog.models import Team  # noqa: PLC0415

    from products.tasks.backend.repository_readiness import (  # noqa: PLC0415 — keep readiness deps off the api import path
        compute_repository_readiness as _compute,
    )

    team = Team.objects.get(id=team_id)
    return _compute(team=team, repository=repository, window_days=window_days, refresh=refresh)


def create_task(team_id: int, user_id: int | None, *, validated_data: dict) -> contracts.TaskDetailDTO:
    """Create a task, mirroring ``TaskSerializer.create`` byte-for-byte.

    Absorbs the cross-product ``SignalReportTask`` linkage, ``generate_task_title``, and
    ``resolve_user_github_integration_for_task`` so no internal/other-product import leaks into
    presentation. ``validated_data`` carries the validated write fields (integrations already
    resolved to instances by the write serializer's PK fields).
    """
    from posthog.models import Team  # noqa: PLC0415

    from products.signals.backend.task_run_artefacts import (  # noqa: PLC0415 — cross-product write kept off the api import path
        record_implementation_task,
    )
    from products.tasks.backend.logic.services.title_generator import generate_task_title  # noqa: PLC0415
    from products.tasks.backend.temporal.process_task.utils import (  # noqa: PLC0415 — keep temporalio off the api import path
        resolve_user_github_integration_for_task,
    )

    team = Team.objects.get(id=team_id)
    validated_data = dict(validated_data)
    validated_data["team"] = team
    validated_data.setdefault("origin_product", Task.OriginProduct.USER_CREATED)
    warm_branch_provided = "branch" in validated_data
    warm_branch = validated_data.pop("branch", None)
    warm_runtime_adapter = validated_data.pop("runtime_adapter", None)
    warm_model = validated_data.pop("model", None)
    warm_reasoning_effort = validated_data.pop("reasoning_effort", None)
    pending_user_message = (validated_data.pop("pending_user_message", None) or "").strip() or None
    pending_user_artifact_ids = validated_data.pop("pending_user_artifact_ids", None) or []
    warm_auto_publish = validated_data.pop("auto_publish", None)

    if user_id is not None:
        validated_data["created_by"] = User.objects.get(id=user_id)

    if (
        warm_branch_provided
        and validated_data["origin_product"] == Task.OriginProduct.USER_CREATED
        and validated_data.get("repository")
        and user_id is not None
    ):
        warm_run = _find_idling_warm_run(
            team_id,
            user_id,
            repository=validated_data["repository"],
            branch=warm_branch,
            runtime_adapter=warm_runtime_adapter,
            model=warm_model,
            reasoning_effort=warm_reasoning_effort,
        )
        if warm_run is not None and pending_user_artifact_ids:
            from products.tasks.backend.logic.services.staged_artifacts import (  # noqa: PLC0415 — keep storage deps off the api import path
                get_task_run_artifacts_by_id,
            )

            _, missing_artifact_ids = get_task_run_artifacts_by_id(warm_run, pending_user_artifact_ids)
            if missing_artifact_ids:
                logger.info(
                    "Skipping warm run reuse: %d pending artifact id(s) missing from warm run %s manifest",
                    len(missing_artifact_ids),
                    warm_run.id,
                )
                warm_run = None
        if warm_run is not None:
            warm_task = warm_run.task
            description = (validated_data.get("description") or "").strip()
            update_fields: list[str] = []
            if description and not (warm_task.title or "").strip():
                warm_task.title = generate_task_title(description)
                warm_task.title_manually_set = False
                update_fields += ["title", "title_manually_set"]
            if description and not (warm_task.description or "").strip():
                warm_task.description = description
                update_fields.append("description")
            channel = validated_data.get("channel")
            if channel is not None and warm_task.channel_id != channel.id:
                warm_task.channel = channel
                update_fields.append("channel")
            if update_fields:
                warm_task.save(update_fields=[*update_fields, "updated_at"])
            _activate_warm_run(
                warm_run,
                warm_task,
                team_id,
                message=pending_user_message or description or None,
                description=description or None,
                artifact_ids=pending_user_artifact_ids,
                auto_publish=warm_auto_publish,
            )
            return _task_detail_to_dto(_task_detail_queryset().get(pk=warm_task.pk))

    # Only IMPLEMENTATION is accepted; pop it so it isn't forwarded to the model. The link itself
    # is recorded by record_implementation_task below.
    validated_data.pop("signal_report_task_relationship", None)

    if not validated_data.get("github_integration"):
        default_integration = Integration.objects.filter(team=team, kind="github").first()
        if default_integration:
            validated_data["github_integration"] = default_integration

    if (
        validated_data.get("repository")
        and validated_data.get("origin_product", Task.OriginProduct.USER_CREATED) == Task.OriginProduct.USER_CREATED
        and not validated_data.get("github_user_integration")
    ):
        task_stub = Task(
            team=team,
            created_by=validated_data.get("created_by"),
            origin_product=Task.OriginProduct.USER_CREATED,
            repository=validated_data["repository"],
            github_integration=validated_data.get("github_integration"),
        )
        github_user_integration = resolve_user_github_integration_for_task(task_stub, allow_refresh=False)
        if github_user_integration is not None:
            validated_data["github_user_integration"] = github_user_integration.integration

    title = (validated_data.get("title") or "").strip()
    if not title and validated_data.get("description"):
        validated_data["title"] = generate_task_title(validated_data["description"])
        validated_data.setdefault("title_manually_set", False)
    elif title:
        validated_data.setdefault("title_manually_set", True)

    logger.info("Creating task with data: %s", validated_data)
    with transaction.atomic():
        task = Task.objects.create(**validated_data)
        if task.signal_report_id and task.origin_product == Task.OriginProduct.SIGNAL_REPORT:
            # Dual-write the implementation gate row + task_run work-log artefact (see
            # record_implementation_task) so a manually-started task matches autostarted ones.
            record_implementation_task(
                team_id=task.team_id,
                report_id=str(task.signal_report_id),
                task_id=str(task.id),
            )

    return _task_detail_to_dto(_task_detail_queryset().get(pk=task.pk))


def set_task_title(task_id: str | UUID, team_id: int, title: str) -> bool:
    """Set a task's title, team-scoped. For automated relabels — e.g. backfilling a Signals research
    task with ``"Research: <report title>"`` once research produces the title. Leaves
    ``title_manually_set`` untouched (this isn't a user edit) and clamps to the column length. Returns
    whether a row was updated.
    """
    return bool(Task.objects.filter(id=task_id, team_id=team_id).update(title=title[:255]))


def update_task(
    task_id: str | UUID, team_id: int, user_id: int | None, *, validated_data: dict
) -> contracts.TaskDetailDTO | None:
    """Update a task, mirroring ``TaskSerializer.update``. ``None`` if not found/controllable."""
    task = _visible_task_qs(team_id, user_id, for_control=True).filter(id=task_id).first()
    if task is None:
        return None

    validated_data = dict(validated_data)
    # Immutable after creation; origin_product controls visibility, signal_report is set-once.
    validated_data.pop("signal_report", None)
    validated_data.pop("signal_report_task_relationship", None)
    validated_data.pop("origin_product", None)
    validated_data.pop("branch", None)
    if "title" in validated_data and "title_manually_set" not in validated_data:
        validated_data["title_manually_set"] = True
    if "archived" in validated_data and validated_data["archived"] != task.archived:
        validated_data["archived_at"] = django_timezone.now() if validated_data["archived"] else None

    logger.info("perform_update called for task %s with validated_data: %s", task.id, validated_data)
    for key, value in validated_data.items():
        setattr(task, key, value)
    task.save()
    logger.info("Task %s updated successfully", task.id)

    return _task_detail_to_dto(_task_detail_queryset().get(pk=task.pk))


def soft_delete_task(task_id: str | UUID, team_id: int, user_id: int | None) -> bool:
    """Soft-delete a task. Returns whether a task was found/controllable and deleted."""
    task = _visible_task_qs(team_id, user_id, for_control=True).filter(id=task_id).first()
    if task is None:
        return False
    logger.info("Soft deleting task %s", task.id)
    task.soft_delete()
    return True


# --- Task staged artifacts (S3 + cache, attached to the next run) ---


_TASK_STAGED_ARTIFACT_UPLOAD_FORM_OVERHEAD_BYTES = 64 * 1024


def prepare_task_staged_artifacts(
    task_id: str | UUID,
    team_id: int,
    user_id: int | None,
    *,
    artifacts: list[dict],
    upload_expiration_seconds: int,
) -> contracts.StagedArtifactPrepareResult | None:
    """Reserve S3 keys + presigned POST forms for task attachments. ``None`` if task not found."""
    from posthog.storage import object_storage  # noqa: PLC0415

    from products.tasks.backend.logic.services.staged_artifacts import (  # noqa: PLC0415
        build_task_staged_artifact_storage_path,
        get_safe_artifact_name,
    )

    # Staged artifacts feed the task's next run, so this is control, not viewing.
    task = _visible_task_qs(team_id, user_id, for_control=True).filter(id=task_id).first()
    if task is None:
        return None

    prepared: list[contracts.StagedArtifactPreparedDTO] = []
    for artifact in artifacts:
        artifact_id = uuid4().hex
        safe_name = get_safe_artifact_name(artifact["name"])
        storage_path = build_task_staged_artifact_storage_path(task, artifact_id, safe_name)
        presigned_post = object_storage.get_presigned_post(
            storage_path,
            conditions=[
                ["content-length-range", 0, artifact["size"] + _TASK_STAGED_ARTIFACT_UPLOAD_FORM_OVERHEAD_BYTES]
            ],
            expiration=upload_expiration_seconds,
        )
        if not presigned_post:
            return contracts.StagedArtifactPrepareResult(error="Unable to generate upload URL")

        prepared.append(
            contracts.StagedArtifactPreparedDTO(
                id=artifact_id,
                name=safe_name,
                type=artifact["type"],
                source=artifact.get("source") or "",
                size=artifact["size"],
                content_type=artifact.get("content_type") or "",
                storage_path=storage_path,
                expires_in=upload_expiration_seconds,
                presigned_post=presigned_post,
                metadata=artifact.get("metadata"),
            )
        )

    return contracts.StagedArtifactPrepareResult(artifacts=prepared)


def finalize_task_staged_artifacts(
    task_id: str | UUID,
    team_id: int,
    user_id: int | None,
    *,
    artifacts: list[dict],
) -> contracts.StagedArtifactFinalizeResult | None:
    """Verify staged S3 uploads and cache their metadata. ``None`` if task not found."""
    from django.conf import settings  # noqa: PLC0415

    from posthog.storage import object_storage  # noqa: PLC0415

    from products.tasks.backend.logic.services.staged_artifacts import (  # noqa: PLC0415
        STAGED_ARTIFACT_TTL_DAYS,
        build_task_artifact_entry,
        cache_task_staged_artifact,
        get_safe_artifact_name,
        tag_task_artifact,
    )
    from products.tasks.backend.presentation.serializers import (  # noqa: PLC0415
        build_task_run_artifact_size_error,
        get_task_run_artifact_max_size_bytes,
    )

    task = _visible_task_qs(team_id, user_id, for_control=True).filter(id=task_id).first()
    if task is None:
        return None

    artifact_prefix = f"{settings.OBJECT_STORAGE_TASKS_FOLDER}/artifacts/team_{task.team_id}/task_{task.id}/staged/"
    finalized: list[dict] = []
    for artifact in artifacts:
        artifact_id = artifact["id"]
        storage_path = artifact["storage_path"]
        if not storage_path.startswith(artifact_prefix) or f"/{artifact_id}/" not in storage_path:
            return contracts.StagedArtifactFinalizeResult(error="Artifact storage path is invalid for this task")

        s3_object = object_storage.head_object(storage_path)
        if not s3_object:
            return contracts.StagedArtifactFinalizeResult(error="Artifact upload not found in object storage")

        content_length = s3_object.get("ContentLength")
        if not isinstance(content_length, int):
            return contracts.StagedArtifactFinalizeResult(error="Artifact upload metadata is unavailable")

        safe_name = get_safe_artifact_name(artifact["name"])
        content_type = artifact.get("content_type") or s3_object.get("ContentType") or ""
        max_size_bytes = get_task_run_artifact_max_size_bytes(safe_name, content_type, artifact.get("type"))
        if content_length > max_size_bytes:
            return contracts.StagedArtifactFinalizeResult(
                error=build_task_run_artifact_size_error(safe_name, max_size_bytes)
            )

        finalized.append(
            build_task_artifact_entry(
                artifact_id=artifact_id,
                name=safe_name,
                artifact_type=artifact["type"],
                source=artifact.get("source") or "",
                size=content_length,
                content_type=content_type,
                storage_path=storage_path,
                metadata=artifact.get("metadata"),
            )
        )

    for entry in finalized:
        cache_task_staged_artifact(task, entry)
        tag_task_artifact(entry["storage_path"], ttl_days=STAGED_ARTIFACT_TTL_DAYS, team_id=task.team_id)

    return contracts.StagedArtifactFinalizeResult(artifacts=finalized)


def resolve_team_github_integration_id(team_id: int, github_integration_id: int) -> int | None:
    """Return the integration id only if it is a GitHub integration owned by this team.

    Re-scoping guard for the collection-level warm endpoint, which accepts a bare PK with
    no serializer team context. Returns ``None`` for any id that doesn't belong to the team —
    the caller treats that as "skip warming" (the submit later falls through to a cold create+run).
    """
    exists = Integration.objects.filter(id=github_integration_id, team_id=team_id, kind="github").exists()
    return github_integration_id if exists else None


def _find_idling_warm_run(
    team_id: int,
    user_id: int | None,
    *,
    repository: str | None,
    branch: str | None,
    runtime_adapter: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> TaskRun | None:
    """Most-recent idling pre-warmed Run matching this user's cloud composing selection, or ``None``.

    A warm Run is a non-terminal ``USER_CREATED`` Run for the same repo+branch still awaiting its
    first user message (the ``await_user_message`` state marker). This is the backend's single source
    of truth for the warm pool: it dedupes warm provisioning (so a repeated ``warm`` call reuses the
    live Run instead of spawning a second) and lets the normal create+run path transparently reuse a
    warm Run on submit. Team + user scoped; branch compared as ``None``-normalized exact match.

    Reuse also requires the warm Run's ``runtime_adapter``/``model``/``reasoning_effort`` to match the
    requested selection (each ``None``-normalized); a mismatch returns ``None`` so the caller cold-creates
    on the correct runtime. The repo/branch/``await_user_message`` predicates stay in the query; the
    runtime selection is matched in Python over the small candidate set.
    """
    if user_id is None or not repository:
        return None
    candidates = (
        TaskRun.objects.filter(  # nosemgrep: idor-lookup-without-team — team_id filter applied via the task FK below
            task__team_id=team_id,
            task__created_by_id=user_id,
            task__origin_product=Task.OriginProduct.USER_CREATED,
            task__repository__iexact=repository,
            task__deleted=False,
            state__await_user_message=True,
            branch=branch or None,
        )
        .exclude(status__in=_TERMINAL_TASK_RUN_STATUSES)
        .select_related("task")
        .order_by("-created_at")[:20]
    )
    wanted = (runtime_adapter or None, model or None, reasoning_effort or None)
    for run in candidates:
        state = run.state or {}
        have = (state.get("runtime_adapter") or None, state.get("model") or None, state.get("reasoning_effort") or None)
        if have == wanted:
            return run
    return None


def _idling_warm_run_for_task(task: Task) -> TaskRun | None:
    """The task's latest run iff it is an idling pre-warmed Run (non-terminal, awaiting first message)."""
    run = task.latest_run
    if run is None or run.is_terminal:
        return None
    if not (run.state or {}).get("await_user_message"):
        return None
    return run


def _attach_staged_artifacts_to_run(
    run: TaskRun, task: Task, *, staged_artifacts: list[dict], artifact_ids: list[str]
) -> None:
    from products.tasks.backend.logic.services.staged_artifacts import (  # noqa: PLC0415 — keep storage deps off the api import path
        RUN_ARTIFACT_TTL_DAYS,
        build_task_staged_artifact_cache_key,
        tag_task_artifact,
    )
    from products.tasks.backend.redis import get_tasks_cache  # noqa: PLC0415

    manifest = list(run.artifacts or [])
    for staged_artifact in staged_artifacts:
        storage_path = str(staged_artifact["storage_path"])
        if _find_artifact_manifest_entry(manifest, str(staged_artifact.get("id")), storage_path):
            continue
        tag_task_artifact(storage_path, ttl_days=RUN_ARTIFACT_TTL_DAYS, team_id=task.team_id)
        manifest.append(dict(staged_artifact))
    _save_artifact_manifest(run, manifest)
    get_tasks_cache().delete_many(
        [build_task_staged_artifact_cache_key(str(task.id), artifact_id) for artifact_id in artifact_ids]
    )


def _activate_warm_run(
    run: TaskRun,
    task: Task,
    team_id: int,
    *,
    message: str | None,
    artifact_ids: list[str],
    description: str | None = None,
    auto_publish: bool | None = None,
) -> None:
    """Activate an idling warm Run: set the draft Task's visible description from raw task text,
    forward the first message to the already-running agent, and drop the ``await_user_message`` marker
    so the Run leaves the warm pool. Mirrors ``message_routing._handle_first_message``; no fresh agent
    start.

    ``auto_publish`` is persisted into the Run's state before the message signal: the already-running
    agent-server can't take it as a launch flag, so it re-reads run state when the forwarded first
    message arrives (and resumes read it from carried state)."""
    from products.tasks.backend.metrics import (  # noqa: PLC0415 — keep prometheus deps off the api import path
        observe_prewarmed_activated,
    )

    if description and not (task.description or "").strip():
        task.description = description
        task.save(update_fields=["description", "updated_at"])
    if auto_publish is not None:
        # Before the signal: the agent-server re-reads run state when the forwarded
        # first message arrives, so the choice must already be persisted by then.
        TaskRun.update_state_atomic(run.id, updates={"auto_publish": auto_publish})
    signal_task_run_user_message(run.id, task.id, team_id, content=message, artifact_ids=artifact_ids)
    TaskRun.update_state_atomic(run.id, remove_keys=["await_user_message"])
    # Only count activations of Runs that actually carry the prewarmed marker, so the activation
    # numerator stays consistent with the workflow_start{prewarmed="true"} denominator — otherwise
    # warm Runs provisioned before this ships (await_user_message set, prewarmed absent) would push
    # the hit rate above 1 during the deploy transition.
    if (run.state or {}).get("prewarmed"):
        observe_prewarmed_activated(run)


def warm_task_sandbox(
    team_id: int,
    user_id: int,
    *,
    repository: str,
    github_integration_id: int,
    branch: str | None,
    runtime_adapter: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> contracts.WarmTaskDTO | None:
    """Warm a full idling Run for a Code-app cloud task while the user composes.

    Births a draft Task (``USER_CREATED``), then ``SandboxWarmer.warm()`` provisions an interactive
    Run that boots + clones + checks out ``branch`` + starts the agent on the selected
    ``runtime_adapter``/``model``/``reasoning_effort`` (carried on the Run state and read by the
    agent-server at launch, so the sandbox boots on the right runtime), then idles awaiting the first
    ``user_message``. The Run is dispatched with ``create_pr=True`` so that, once activated on submit,
    it completes autonomously and opens a PR like a normal Code-app cloud task.

    Best-effort: returns ``None`` (not an HTTP error) when warming is gated — over quota
    (``QuotaLimitExceeded``), product not enabled (``PermissionDenied``), or the warm pool is full
    (``Throttled``). The caller treats ``None`` as "no warm run; fall through to a cold create+run".

    ``github_integration_id`` must already be re-scoped to ``team_id`` by the caller
    (see :func:`resolve_team_github_integration_id`).
    """
    from rest_framework.exceptions import (  # noqa: PLC0415 — keep DRF exception types off the api import path
        PermissionDenied,
        Throttled,
    )

    from posthog.exceptions import QuotaLimitExceeded  # noqa: PLC0415 — keep billing deps off the api import path
    from posthog.models import Team  # noqa: PLC0415

    from products.tasks.backend.logic.services.warm import (
        SandboxWarmer,  # noqa: PLC0415 — keep warming deps off the api import path
    )
    from products.tasks.backend.temporal.process_task.utils import (  # noqa: PLC0415 — keep temporalio off the api import path
        RuntimeAdapter,
        get_provider_for_runtime_adapter,
    )

    existing = _find_idling_warm_run(
        team_id,
        user_id,
        repository=repository,
        branch=branch,
        runtime_adapter=runtime_adapter,
        model=model,
        reasoning_effort=reasoning_effort,
    )
    if existing is not None:
        return contracts.WarmTaskDTO(task_id=existing.task_id, run_id=existing.id)

    team = Team.objects.get(id=team_id)
    github_integration = Integration.objects.filter(id=github_integration_id, team_id=team_id, kind="github").first()
    if github_integration is None:
        return None

    task = Task.create_without_run(
        team=team,
        title="",
        description="",
        origin_product=Task.OriginProduct.USER_CREATED,
        user_id=user_id,
        repository=repository,
    )
    assert task.created_by is not None  # create_without_run always sets created_by from user_id

    provider = get_provider_for_runtime_adapter(runtime_adapter)
    initial_permission_mode = "auto" if runtime_adapter == RuntimeAdapter.CODEX.value else "default"
    extra_state: dict = {
        "branch": branch,
        "initial_permission_mode": initial_permission_mode,
        "use_modal_network_allowlist": False,
    }
    for key, value in {
        "runtime_adapter": runtime_adapter,
        "provider": provider.value if provider is not None else None,
        "model": model,
        "reasoning_effort": reasoning_effort,
    }.items():
        if value is not None:
            extra_state[key] = value

    try:
        result = SandboxWarmer(task, user=task.created_by).warm(
            mode="interactive",
            extra_state=extra_state,
            create_pr=True,
        )
    except (Throttled, PermissionDenied, QuotaLimitExceeded):
        task.soft_delete()
        return None

    return contracts.WarmTaskDTO(task_id=task.id, run_id=result.run.id)


# --- Task run (the ``run`` action) ---


def run_task(
    task_id: str | UUID, team_id: int, user_id: int | None, *, validated_data: dict
) -> contracts.TaskRunResult | None:
    """Create a run for a task and kick off its workflow, mirroring ``TaskViewSet.run``.

    Returns ``None`` if the task isn't found/visible (the view raises 404). Otherwise a
    ``TaskRunResult`` carrying the refreshed task detail DTO or a structured error. The usage
    gate (429) is applied by the view before calling this.
    """
    from products.tasks.backend.logic.services.staged_artifacts import get_task_staged_artifacts  # noqa: PLC0415
    from products.tasks.backend.temporal.process_task.utils import (  # noqa: PLC0415 — keep temporalio off the api import path
        PrAuthorshipMode,
        RunSource,
        cache_github_user_token,
        get_provider_for_runtime_adapter,
        get_reasoning_effort_error,
        parse_run_state,
    )

    task = _visible_task_qs(team_id, user_id, for_control=True).filter(id=task_id).first()
    if task is None:
        return None

    mode = validated_data.get("mode", "background")
    branch = validated_data.get("branch")
    resume_from_run_id = validated_data.get("resume_from_run_id")
    pending_user_message = validated_data.get("pending_user_message")
    pending_user_artifact_ids = validated_data.get("pending_user_artifact_ids") or []

    if not resume_from_run_id:
        warm_run = _idling_warm_run_for_task(task)
        if warm_run is not None and (branch or None) == (warm_run.branch or None):
            warm_state = warm_run.state or {}
            warm_runtime_matches = (
                warm_state.get("runtime_adapter") or None,
                warm_state.get("model") or None,
                warm_state.get("reasoning_effort") or None,
            ) == (
                validated_data.get("runtime_adapter") or None,
                validated_data.get("model") or None,
                validated_data.get("reasoning_effort") or None,
            )
            if warm_runtime_matches:
                warm_staged_artifacts, warm_missing_artifact_ids = (
                    get_task_staged_artifacts(task, pending_user_artifact_ids)
                    if pending_user_artifact_ids
                    else ([], [])
                )
                if not warm_missing_artifact_ids:
                    if warm_staged_artifacts:
                        _attach_staged_artifacts_to_run(
                            warm_run,
                            task,
                            staged_artifacts=warm_staged_artifacts,
                            artifact_ids=pending_user_artifact_ids,
                        )
                    _activate_warm_run(
                        warm_run,
                        task,
                        team_id,
                        message=pending_user_message or (task.description or None),
                        description=task.description or None,
                        artifact_ids=pending_user_artifact_ids,
                        auto_publish=validated_data.get("auto_publish"),
                    )
                    return contracts.TaskRunResult(task=get_task_detail(task.id, team_id, user_id))
    sandbox_environment_id = validated_data.get("sandbox_environment_id")
    sandbox_environment_id_supplied_by_user = sandbox_environment_id is not None
    custom_image_id = validated_data.get("custom_image_id")
    custom_image_id_supplied_by_user = custom_image_id is not None
    pr_authorship_mode = validated_data.get("pr_authorship_mode")
    auto_publish = validated_data.get("auto_publish")
    run_source = validated_data.get("run_source")
    signal_report_id = validated_data.get("signal_report_id")
    runtime_adapter = validated_data.get("runtime_adapter")
    model = validated_data.get("model")
    reasoning_effort = validated_data.get("reasoning_effort")
    github_user_token = validated_data.get("github_user_token")
    initial_permission_mode = validated_data.get("initial_permission_mode")
    if run_source == RunSource.SIGNAL_REPORT:
        pr_authorship_mode = PrAuthorshipMode.BOT

    runtime_state_fields = {
        "pr_authorship_mode": pr_authorship_mode,
        "auto_publish": auto_publish,
        "run_source": run_source,
        "signal_report_id": signal_report_id,
        "runtime_adapter": runtime_adapter,
        "model": model,
        "reasoning_effort": reasoning_effort,
    }

    extra_state: dict | None = None
    if pending_user_message is not None:
        extra_state = {"pending_user_message": pending_user_message}
    if pending_user_artifact_ids:
        extra_state = extra_state or {}
        extra_state["pending_user_artifact_ids"] = pending_user_artifact_ids
    if initial_permission_mode is not None:
        extra_state = extra_state or {}
        extra_state["initial_permission_mode"] = initial_permission_mode

    if resume_from_run_id:
        previous_run = task.runs.filter(id=resume_from_run_id).first()
        if not previous_run:
            return contracts.TaskRunResult(
                error=contracts.TaskValidationError(kind="detail", detail="Invalid resume_from_run_id")
            )

        prev_state = parse_run_state(previous_run.state)
        extra_state = extra_state or {}
        extra_state["resume_from_run_id"] = str(resume_from_run_id)
        extra_state.update(prev_state.resume_snapshot_carry_state())

        # The resumed agent still pushes the head branch baked into the original prompt, so the
        # PR webhook must be able to match this run, not the terminal predecessor.
        prev_wizard_head_branch = (previous_run.state or {}).get("wizard_head_branch")
        if prev_wizard_head_branch:
            extra_state["wizard_head_branch"] = prev_wizard_head_branch

        if prev_state.sandbox_environment_id and sandbox_environment_id is None:
            sandbox_environment_id = prev_state.sandbox_environment_id

        if custom_image_id is None:
            custom_image_id = (previous_run.state or {}).get("custom_image_id")

        for field_name in runtime_state_fields:
            if runtime_state_fields[field_name] is None:
                runtime_state_fields[field_name] = getattr(prev_state, field_name)

        pr_authorship_mode = runtime_state_fields["pr_authorship_mode"]
        auto_publish = runtime_state_fields["auto_publish"]
        run_source = runtime_state_fields["run_source"]
        signal_report_id = runtime_state_fields["signal_report_id"]
        runtime_adapter = runtime_state_fields["runtime_adapter"]
        model = runtime_state_fields["model"]
        reasoning_effort = runtime_state_fields["reasoning_effort"]
        if branch is None and prev_state.pr_base_branch is not None:
            branch = prev_state.pr_base_branch

    provider = get_provider_for_runtime_adapter(runtime_adapter)

    for key, value in {
        "pr_base_branch": branch,
        "pr_authorship_mode": pr_authorship_mode,
        "auto_publish": auto_publish,
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
        return contracts.TaskRunResult(
            error=contracts.TaskValidationError(
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
        return contracts.TaskRunResult(
            error=contracts.TaskValidationError(
                kind=validation_error.kind,
                detail=validation_error.detail,
                code=validation_error.code,
                attr=validation_error.attr,
            )
        )
    if pr_authorship_mode is not None:
        extra_state = extra_state or {}
        extra_state["pr_authorship_mode"] = (
            pr_authorship_mode.value if hasattr(pr_authorship_mode, "value") else pr_authorship_mode
        )

    if credential_source := _github_credential_source_extra_state(pr_authorship_mode, github_user_token):
        extra_state = extra_state or {}
        extra_state.update(credential_source)

    if custom_image_id is not None:
        custom_image = SandboxCustomImage.get_accessible_for_task(
            image_id=custom_image_id, team_id=task.team_id, task_created_by_id=task.created_by_id
        )
        if custom_image is None:
            if custom_image_id_supplied_by_user:
                return contracts.TaskRunResult(
                    error=contracts.TaskValidationError(kind="detail", detail="Invalid custom_image_id")
                )
        elif not custom_image.is_ready:
            if custom_image_id_supplied_by_user:
                return contracts.TaskRunResult(
                    error=contracts.TaskValidationError(
                        kind="detail", detail=f"Custom image is not ready (status: {custom_image.status})"
                    )
                )
        else:
            extra_state = extra_state or {}
            extra_state["custom_image_id"] = str(custom_image.id)

    if sandbox_environment_id is not None:
        sandbox_environment = SandboxEnvironment.get_accessible_for_task(
            environment_id=sandbox_environment_id,
            team_id=task.team_id,
            task_created_by_id=task.created_by_id,
        )
        if sandbox_environment is None:
            if sandbox_environment_id_supplied_by_user:
                return contracts.TaskRunResult(
                    error=contracts.TaskValidationError(kind="detail", detail="Invalid sandbox_environment_id")
                )
        else:
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

    staged_artifacts: list[dict] = []
    if pending_user_artifact_ids:
        staged_artifacts, missing_artifact_ids = get_task_staged_artifacts(task, pending_user_artifact_ids)
        if missing_artifact_ids:
            return contracts.TaskRunResult(
                error=contracts.TaskValidationError(
                    kind="detail",
                    detail="Some pending_user_artifact_ids are invalid or expired",
                    missing_artifact_ids=missing_artifact_ids,
                )
            )

    logger.info("Creating task run for task %s with mode=%s, branch=%s", task.id, mode, branch)
    task_run = task.create_run(mode=mode, branch=branch, extra_state=extra_state)

    if pending_user_artifact_ids:
        _attach_staged_artifacts_to_run(
            task_run, task, staged_artifacts=staged_artifacts, artifact_ids=pending_user_artifact_ids
        )

    if github_user_token and pr_authorship_mode == PrAuthorshipMode.USER:
        cache_github_user_token(str(task_run.id), github_user_token)

    logger.info("Triggering workflow for task %s, run %s", task.id, task_run.id)
    _trigger_task_processing_workflow(task, task_run, user_id, raise_on_error=False)

    return contracts.TaskRunResult(task=get_task_detail(task.id, team_id, user_id))


# --- Task presence beacons ---


def beacon_task_presence(task_id: str | UUID, team_id: int, user_id: int | None, *, device_id) -> str:
    """Idempotent upsert of a presence row for a device watching a task.

    Returns ``"not_found"`` (task not visible or device_id doesn't match the caller's push
    token), or ``"ok"``. Mirrors ``TaskViewSet._presence_beacon``.
    """
    from posthog.models.user_push_token import UserPushToken  # noqa: PLC0415

    from products.tasks.backend.models import TASK_PRESENCE_TTL_SECONDS, TaskPresence  # noqa: PLC0415

    if user_id is None:
        return "not_found"
    task = _visible_task_qs(team_id, user_id).filter(id=task_id).first()
    if task is None:
        return "not_found"
    push_token = UserPushToken.objects.filter(user_id=user_id, id=device_id).first()
    if push_token is None:
        return "not_found"

    now = django_timezone.now()
    # nosemgrep: idor-lookup-without-team — team scope is enforced by TaskScopedManager
    # and via the `task` FK whose row is fetched (visibility-gated) above.
    TaskPresence.objects.update_or_create(
        task=task,
        push_token=push_token,
        defaults={
            "team": task.team,
            "user_id": user_id,
            "expires_at": now + timedelta(seconds=TASK_PRESENCE_TTL_SECONDS),
        },
    )
    return "ok"


def leave_task_presence(task_id: str | UUID, team_id: int, user_id: int | None, *, device_id) -> str:
    """Best-effort delete of a presence row. ``"not_found"`` if the task isn't visible, else ``"ok"``.

    No 404 on missing presence rows — leave runs from blur/background handlers. Mirrors
    ``TaskViewSet._presence_leave``.
    """
    from products.tasks.backend.models import TaskPresence  # noqa: PLC0415

    if user_id is None:
        return "not_found"
    task = _visible_task_qs(team_id, user_id).filter(id=task_id).first()
    if task is None:
        return "not_found"
    TaskPresence.objects.filter(task=task, push_token_id=device_id, user_id=user_id).delete()
    return "ok"


# --- Slack thread context (internal debug) ---


def _temporal_workflow_url(workflow_id: str | None) -> str | None:
    from django.conf import settings  # noqa: PLC0415

    if not workflow_id:
        return None
    base = getattr(settings, "TEMPORAL_UI_HOST", None)
    namespace = getattr(settings, "TEMPORAL_NAMESPACE", None)
    if not base or not namespace:
        return None
    return f"{base.rstrip('/')}/namespaces/{namespace}/workflows/{workflow_id}"


def _slack_repo_research_dto(
    team_id: int, state: dict, repo_research_runs_by_id: dict, *, build_task_view_url
) -> contracts.SlackThreadContextRepoResearchDTO | None:
    from posthog.storage import object_storage  # noqa: PLC0415

    research_task_id = state.get("repo_research_task_id")
    research_run_id = state.get("repo_research_run_id")
    if not research_task_id or not research_run_id:
        return None
    research_run = repo_research_runs_by_id.get(research_run_id)
    sandbox_url = None
    log_url = None
    run_status = None
    if research_run is not None:
        sandbox_url = (research_run.state if isinstance(research_run.state, dict) else {}).get("sandbox_url")
        run_status = research_run.status
        try:
            log_url = object_storage.get_presigned_url(research_run.log_url, expiration=3600)
        except Exception:
            logger.exception("slack_thread_context_research_log_presign_failed", extra={"run_id": research_run_id})
            log_url = None
    workflow_id = TaskRun.get_workflow_id(research_task_id, research_run_id)
    return contracts.SlackThreadContextRepoResearchDTO(
        task_id=research_task_id,
        run_id=research_run_id,
        status=run_status,
        task_processing_workflow_id=workflow_id,
        task_processing_workflow_url=_temporal_workflow_url(workflow_id),
        sandbox_url=sandbox_url,
        task_view_url=build_task_view_url(
            f"/project/{team_id}/tasks/{research_task_id}?runId={research_run_id}&ph_debug=true"
        ),
        log_url=log_url,
    )


def resolve_slack_thread_context(
    team_id: int, *, channel: str, thread_ts: str, url: str, build_url
) -> contracts.SlackThreadContextResult:
    """Resolve a parsed Slack permalink to its task, runs, and Temporal workflow handles.

    Caller passes the already-parsed ``(channel, thread_ts)`` and a ``build_url`` callable
    (``request.build_absolute_uri``) so the facade stays request-agnostic. Caller also enforces
    the internal-debug gate before calling. Mirrors ``TaskViewSet.slack_thread_context``.
    """
    from posthog.storage import object_storage  # noqa: PLC0415

    from products.slack_app.backend.models import (  # noqa: PLC0415 — cross-product import kept off the api import path
        SlackThreadTaskMapping,
    )

    mapping = (
        SlackThreadTaskMapping.objects.select_related("task", "task__created_by")
        .filter(channel=channel, thread_ts=thread_ts)
        .first()
    )
    if mapping is None:
        return contracts.SlackThreadContextResult(
            outcome="no_mapping",
            no_mapping_thread=contracts.SlackThreadContextThreadDTO(
                url=url,
                channel=channel,
                thread_ts=thread_ts,
                slack_workspace_id=None,
                mentioning_slack_user_id=None,
            ),
        )

    task = mapping.task
    runs = list(TaskRun.objects.filter(task=task).order_by("created_at", "id"))
    repo_research_run_ids = [
        rid for run in runs if (rid := (run.state if isinstance(run.state, dict) else {}).get("repo_research_run_id"))
    ]
    repo_research_runs_by_id = (
        {str(r.id): r for r in TaskRun.objects.filter(team=task.team, id__in=repo_research_run_ids)}
        if repo_research_run_ids
        else {}
    )
    task_url = build_url(f"/project/{task.team_id}/tasks/{task.id}?ph_debug=true")

    run_dtos: list[contracts.SlackThreadContextRunDTO] = []
    for run in runs:
        state = run.state if isinstance(run.state, dict) else {}
        output = run.output if isinstance(run.output, dict) else {}
        task_processing_workflow_id = TaskRun.get_workflow_id(task.id, run.id)
        mention_workflow_id = state.get("slack_mention_workflow_id")
        try:
            presigned_log_url = object_storage.get_presigned_url(run.log_url, expiration=3600)
        except Exception:
            logger.exception("slack_thread_context_log_presign_failed", extra={"run_id": str(run.id)})
            presigned_log_url = None
        run_dtos.append(
            contracts.SlackThreadContextRunDTO(
                id=str(run.id),
                status=run.status,
                created_at=run.created_at,
                completed_at=run.completed_at,
                sandbox_url=state.get("sandbox_url"),
                pr_url=output.get("pr_url"),
                error_message=run.error_message,
                task_processing_workflow_id=task_processing_workflow_id,
                task_processing_workflow_url=_temporal_workflow_url(task_processing_workflow_id),
                mention_workflow_id=mention_workflow_id,
                mention_workflow_url=_temporal_workflow_url(mention_workflow_id),
                task_view_url=build_url(f"/project/{task.team_id}/tasks/{task.id}?runId={run.id}&ph_debug=true"),
                log_url=presigned_log_url,
                repo_research=_slack_repo_research_dto(
                    task.team_id, state, repo_research_runs_by_id, build_task_view_url=build_url
                ),
            )
        )

    context = contracts.SlackThreadContextDTO(
        thread=contracts.SlackThreadContextThreadDTO(
            url=url,
            channel=channel,
            thread_ts=thread_ts,
            slack_workspace_id=mapping.slack_workspace_id,
            mentioning_slack_user_id=mapping.mentioning_slack_user_id,
        ),
        task=contracts.SlackThreadContextTaskDTO(
            id=str(task.id),
            team_id=task.team_id,
            title=task.title,
            repository=task.repository,
            origin_product=task.origin_product,
            created_at=task.created_at,
            url=task_url,
        ),
        runs=run_dtos,
    )
    return contracts.SlackThreadContextResult(outcome="ok", context=context)


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
                quick_action=t.get("quick_action"),
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


# --- Channels & task threads ---


def normalize_channel_name(name: str) -> str:
    """Slack-style channel key: lowercase, whitespace collapsed to dashes.

    Channels are resolved by name from client-side surfaces (folder names), so the
    stored key must be canonical for the (team, name) uniqueness to mean anything.
    """
    return re.sub(r"\s+", "-", name.strip().lower())[:128]


def _channel_to_dto(channel: Channel) -> contracts.ChannelDTO:
    return contracts.ChannelDTO(
        id=channel.id,
        name=channel.name,
        channel_type=channel.channel_type,
        created_at=channel.created_at,
        created_by=_user_basic_info(channel.created_by if channel.created_by_id else None),
    )


def _ensure_personal_channel(team_id: int, user_id: int) -> Channel:
    # select_related so _channel_to_dto doesn't lazy-load created_by per call.
    try:
        channel, _ = Channel.objects.select_related("created_by").get_or_create(
            team_id=team_id,
            created_by_id=user_id,
            channel_type=Channel.ChannelType.PERSONAL,
            deleted=False,
            defaults={"name": Channel.PERSONAL_CHANNEL_NAME},
        )
    except IntegrityError:
        channel = Channel.objects.select_related("created_by").get(
            team_id=team_id,
            created_by_id=user_id,
            channel_type=Channel.ChannelType.PERSONAL,
            deleted=False,
        )
    return channel


def list_channels(team_id: int, user_id: int | None) -> list[contracts.ChannelDTO]:
    """All live public channels plus the requester's personal channel (provisioned lazily),
    personal first, then by name."""
    channels: list[Channel] = []
    if user_id is not None:
        channels.append(_ensure_personal_channel(team_id, user_id))
    channels.extend(
        Channel.objects.filter(team_id=team_id, channel_type=Channel.ChannelType.PUBLIC, deleted=False)
        .select_related("created_by")
        .order_by("name")
    )
    return [_channel_to_dto(channel) for channel in channels]


def resolve_channel(team_id: int, user_id: int | None, *, name: str) -> contracts.ChannelDTO | None:
    """Resolve-or-create a public channel by (normalized) name. ``None`` for empty names."""
    normalized = normalize_channel_name(name)
    if not normalized:
        return None
    try:
        channel, _ = Channel.objects.select_related("created_by").get_or_create(
            team_id=team_id,
            name=normalized,
            channel_type=Channel.ChannelType.PUBLIC,
            deleted=False,
            defaults={"created_by_id": user_id},
        )
    except IntegrityError:
        channel = Channel.objects.select_related("created_by").get(
            team_id=team_id, name=normalized, channel_type=Channel.ChannelType.PUBLIC, deleted=False
        )
    return _channel_to_dto(channel)


def rename_channel(channel_id: str | UUID, team_id: int, *, name: str) -> contracts.ChannelDTO | str:
    """Rename a public channel. Returns the DTO, or an error kind: ``not_found`` /
    ``invalid_name`` / ``personal`` / ``name_taken``."""
    channel = Channel.objects.filter(id=channel_id, team_id=team_id, deleted=False).first()
    if channel is None:
        return "not_found"
    if channel.channel_type == Channel.ChannelType.PERSONAL:
        return "personal"
    normalized = normalize_channel_name(name)
    if not normalized:
        return "invalid_name"
    channel.name = normalized
    try:
        channel.save(update_fields=["name", "updated_at"])
    except IntegrityError:
        return "name_taken"
    return _channel_to_dto(channel)


def delete_channel(channel_id: str | UUID, team_id: int) -> str:
    """Soft-delete a public channel. Returns ``ok`` / ``not_found`` / ``personal``."""
    channel = Channel.objects.filter(id=channel_id, team_id=team_id, deleted=False).first()
    if channel is None:
        return "not_found"
    if channel.channel_type == Channel.ChannelType.PERSONAL:
        return "personal"
    channel.deleted = True
    channel.save(update_fields=["deleted", "updated_at"])
    return "ok"


def _thread_message_to_dto(message: TaskThreadMessage) -> contracts.TaskThreadMessageDTO:
    return contracts.TaskThreadMessageDTO(
        id=message.id,
        task=message.task_id,
        content=message.content,
        created_at=message.created_at,
        author=_user_basic_info(message.author if message.author_id else None),
        forwarded_to_agent_at=message.forwarded_to_agent_at,
        forwarded_by=_user_basic_info(message.forwarded_by if message.forwarded_by_id else None),
    )


def _visible_task(task_id: str | UUID, team_id: int, user_id: int | None) -> Task | None:
    return _visible_task_qs(team_id, user_id).filter(id=task_id).first()


def list_thread_messages(
    task_id: str | UUID, team_id: int, user_id: int | None
) -> list[contracts.TaskThreadMessageDTO] | None:
    """A task's thread, ascending. ``None`` when the task isn't visible to the user."""
    if _visible_task(task_id, team_id, user_id) is None:
        return None
    messages = (
        TaskThreadMessage.objects.filter(task_id=task_id, team_id=team_id)
        .select_related("author", "forwarded_by")
        .order_by("created_at", "id")
    )
    return [_thread_message_to_dto(message) for message in messages]


def create_thread_message(
    task_id: str | UUID, team_id: int, user_id: int | None, *, content: str
) -> contracts.TaskThreadMessageDTO | None:
    """Add a thread message as the requester. ``None`` when the task isn't visible."""
    if _visible_task(task_id, team_id, user_id) is None:
        return None
    message = TaskThreadMessage.objects.create(team_id=team_id, task_id=task_id, author_id=user_id, content=content)
    try:
        _index_thread_message_mentions(message)
    except Exception:
        # Mentions are best-effort: an indexing failure must never fail message creation.
        logger.exception("Failed to index thread message mentions", extra={"message_id": str(message.id)})
    # Fresh message: forwarded_by is None (no query) and author lazy-loads once.
    return _thread_message_to_dto(message)


def _index_thread_message_mentions(message: TaskThreadMessage) -> None:
    """Create mention index rows for @[Name](email) tokens in the message content.

    Emails resolve case-insensitively, only to members of the team's organization;
    self-mentions are skipped (they are never notifications).
    """
    mentioned_user_ids = resolve_mentioned_user_ids(
        User, message.content, team_id=message.team_id, author_id=message.author_id
    )
    TaskThreadMessageMention.objects.bulk_create(
        [
            TaskThreadMessageMention(
                team_id=message.team_id,
                message_id=message.id,
                task_id=message.task_id,
                mentioned_user_id=mentioned_user_id,
                created_at=message.created_at,
            )
            for mentioned_user_id in mentioned_user_ids
        ],
        ignore_conflicts=True,
    )


def list_mentions(
    team_id: int, user_id: int | None, *, since: datetime | None = None, limit: int = 100
) -> list[contracts.TaskMentionDTO]:
    """Thread-message mentions of the requester across tasks they can see, newest first."""
    if user_id is None:
        return []
    qs = TaskThreadMessageMention.objects.filter(
        team_id=team_id,
        mentioned_user_id=user_id,
        # task__in keeps the visibility rules single-sourced in _visible_task_qs.
        task__in=_visible_task_qs(team_id, user_id),
    )
    if since is not None:
        qs = qs.filter(created_at__gt=since)
    mentions = qs.select_related("message__author", "task__channel").order_by("-created_at")[:limit]
    return [
        contracts.TaskMentionDTO(
            id=mention.id,
            message_id=mention.message_id,
            task_id=mention.task_id,
            task_title=mention.task.title,
            channel_id=mention.task.channel_id,
            channel_name=mention.task.channel.name if mention.task.channel else None,
            content=mention.message.content,
            created_at=mention.created_at,
            author=_user_basic_info(mention.message.author if mention.message.author_id else None),
        )
        for mention in mentions
    ]


def delete_thread_message(message_id: str | UUID, task_id: str | UUID, team_id: int, user_id: int | None) -> str:
    """Delete own thread message. Returns ``ok`` / ``not_found`` / ``forbidden``."""
    message = TaskThreadMessage.objects.filter(id=message_id, task_id=task_id, team_id=team_id).first()
    if message is None or _visible_task(task_id, team_id, user_id) is None:
        return "not_found"
    if message.author_id != user_id:
        return "forbidden"
    message.delete()
    return "ok"


def forward_thread_message(
    message_id: str | UUID, task_id: str | UUID, team_id: int, user_id: int | None
) -> tuple[str, contracts.TaskThreadMessageDTO | None]:
    """Send a thread message to the task's agent. Task-author only.

    Returns ``(kind, dto)`` where kind is ``ok`` / ``not_found`` / ``forbidden`` /
    ``already_forwarded`` / ``no_run`` / ``signal_failed``.
    """
    task = _visible_task(task_id, team_id, user_id)
    if task is None:
        return "not_found", None
    if task.created_by_id != user_id:
        return "forbidden", None

    # Lock the message row so concurrent forwards of the same message can't
    # both pass the forwarded_to_agent_at check and double-signal the agent.
    with transaction.atomic():
        # of=("self",) locks only the message row: FOR UPDATE cannot span the nullable
        # outer joins that select_related on author/forwarded_by introduces.
        message = (
            TaskThreadMessage.objects.select_for_update(of=("self",))
            .select_related("author", "forwarded_by")
            .filter(id=message_id, task_id=task_id, team_id=team_id)
            .first()
        )
        if message is None:
            return "not_found", None
        if message.forwarded_to_agent_at is not None:
            return "already_forwarded", _thread_message_to_dto(message)
        run = task.latest_run
        if run is None or run.status in (TaskRun.Status.COMPLETED, TaskRun.Status.FAILED, TaskRun.Status.CANCELLED):
            return "no_run", None

        author = message.author
        author_name = (author.get_full_name() or author.email) if author else "A teammate"
        content = f"[Thread comment from {author_name}] {message.content}"
        signal_result = signal_task_run_user_message(run.id, task.id, team_id, content=content, artifact_ids=[])
        if not signal_result:
            return "signal_failed", None

        message.forwarded_to_agent_at = django_timezone.now()
        message.forwarded_by_id = user_id
        message.forwarded_run = run
        message.save(update_fields=["forwarded_to_agent_at", "forwarded_by", "forwarded_run"])
    return "ok", _thread_message_to_dto(message)
