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
import time
import hashlib
import logging
from collections.abc import Collection, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import UUID, uuid4

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import (
    Case,
    CharField,
    Count,
    DateTimeField,
    Exists,
    F,
    Func,
    IntegerField,
    Min,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Value,
    When,
)
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Coalesce
from django.utils import timezone as django_timezone
from django.utils.http import content_disposition_header

import posthoganalytics

from posthog.event_usage import groups
from posthog.models import Team, User
from posthog.models.integration import Integration
from posthog.models.oauth import OAuthAccessToken, OAuthRefreshToken
from posthog.utils import absolute_uri

from products.posthog_ai.backend.task_ownership import detach_conversations_for_task_handoff
from products.tasks.backend.constants import (
    AGENT_OTEL_TELEMETRY_STATE_KEY,
    AGENT_PEER_MESSAGING_FEATURE_FLAG,
    ANALYSIS_TARGET_IMAGE_ID_STATE_KEY,
    ANALYSIS_TARGET_IMAGE_NAME_STATE_KEY,
    ANALYSIS_TARGET_REPOSITORY_STATE_KEY,
    ANALYSIS_TARGET_RUN_ID_STATE_KEY,
    ANALYSIS_TARGET_TASK_ID_STATE_KEY,
    CI_STATUSES as CI_STATUSES,  # re-exported for presentation
    MAX_CUSTOM_IMAGES_PER_TEAM,
    MAX_CUSTOM_IMAGES_PER_USER,
    PI_CLOUD_RUNTIME_FEATURE_FLAG,
    PR_STATES as PR_STATES,  # re-exported for presentation
    RESERVED_SANDBOX_ENVIRONMENT_VARIABLE_KEYS,
    TASK_ANALYSIS_FEATURE_FLAG,
    TASK_ANALYSIS_INSIGHTS_STATE_KEY,
    TASK_SESSION_MAX_SIZE_BYTES,
    get_required_model_flag,
    is_blocked_sandbox_env_key,
)
from products.tasks.backend.error_telemetry import truncate_error_message
from products.tasks.backend.feature_flags import get_model_access_error, is_workflow_dispatch_shadow_enabled
from products.tasks.backend.github_repository_access import (
    inaccessible_repositories_via_integration as _inaccessible_repositories_via_integration,
)
from products.tasks.backend.logic.services.image_builder import (
    ensure_image_builder_task,
    is_custom_images_enabled,
    read_spec_from_builder_sandbox,
)
from products.tasks.backend.logic.services.network_policy import (
    MAX_SANDBOX_ALLOWED_DOMAINS,
    normalize_requested_domains,
)
from products.tasks.backend.mentions import resolve_mentioned_user_ids
from products.tasks.backend.models import (
    MCP_CREDENTIAL_OWNER_STATE_KEY,
    TASK_OWNERSHIP_VERSION_STATE_KEY,
    Channel,
    ChannelContextGeneration,
    ChannelFeedMessage,
    ChannelInstructions,
    ChannelStar,
    CodeInvite,
    CodeInviteRedemption,
    DesktopBetaTermsAcceptance,
    MCPBuiltInAgentKey,
    SandboxCustomImage,
    SandboxEnvironment,
    SandboxSession,
    SandboxSnapshot,
    Task,
    TaskActivity,
    TaskArtifact,
    TaskClientProvenance,
    TaskCommentActivity,
    TaskOwnershipChangedError,
    TaskPin,
    TaskRun,
    TaskSearchDocument,
    TaskSession,
    TaskThreadMessage,
    TaskThreadMessageMention,
    TaskWorkflowDispatch,
)
from products.tasks.backend.pr_urls import merge_pr_output
from products.tasks.backend.prompts import build_wizard_pr_agent_prompt, generate_wizard_head_branch
from products.tasks.backend.visibility import (
    TEAM_READABLE_ORIGIN_PRODUCTS,
    task_control_q,
    task_run_visibility_q,
    task_visibility_q,
)

from . import contracts

logger = logging.getLogger(__name__)

_TASK_LOG_READ_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="task-log-read")

# --- Enum re-exports ---
# Value types (not ORM models), safe to expose. External callers compare against the
# string-valued ``.status`` / ``.environment`` / ``.origin_product`` fields on the DTOs.
TaskRunStatus = TaskRun.Status
TaskRunEnvironment = TaskRun.Environment
TaskOriginProduct = Task.OriginProduct
TaskRuntime = Task.Runtime
SandboxNetworkAccessLevel = SandboxEnvironment.NetworkAccessLevel
SandboxSnapshotStatus = SandboxSnapshot.Status

# --- Code-invite redeem outcomes ---
# Returned on ``CodeInviteRedeemResult.outcome``; the presentation layer maps each to an
# HTTP response. ``REDEEMED`` covers both a fresh redemption and the idempotent no-op when
# the user already redeemed this code (both surface as success).
CODE_INVITE_REDEEMED = "redeemed"
CODE_INVITE_INVALID_CODE = "invalid_code"
CODE_INVITE_NOT_REDEEMABLE = "not_redeemable"

WIZARD_PR_READY_EMAIL_FEATURE_FLAG = "wizard-cloud-run-pr-ready-email-enabled"

# Runtime posture for a setup-wizard cloud run, applied in create_wizard_cloud_run. The model is
# pinned because these runs route to the unbilled `onboarding` gateway product, which allowlists a
# narrow model set; the string form avoids pulling the temporal RuntimeAdapter enum onto this path.
WIZARD_CLOUD_RUN_RUNTIME_ADAPTER = "claude"
WIZARD_CLOUD_RUN_MODEL = "claude-sonnet-5"
WIZARD_CLOUD_RUN_AI_STAGE = "wizard_pr_agent"

__all__ = [
    "CODE_INVITE_INVALID_CODE",
    "CODE_INVITE_NOT_REDEEMABLE",
    "CODE_INVITE_REDEEMED",
    "SandboxNetworkAccessLevel",
    "SandboxSnapshotStatus",
    "TaskOriginProduct",
    "TaskRuntime",
    "TaskRunEnvironment",
    "TaskRunStatus",
    "append_task_run_log",
    "apply_task_run_model_config",
    "ensure_task_run_session",
    "beacon_task_presence",
    "bootstrap_task_run",
    "can_mint_readonly_github_token",
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
    "create_channel_task",
    "create_task",
    "create_task_without_run",
    "create_task_run_connection_token",
    "create_task_run_living_artifact",
    "create_task_run_stream_read_token",
    "resolve_stream_base_url",
    "claim_and_fail_stale_run",
    "delete_sandbox_custom_image",
    "delete_sandbox_environment",
    "ensure_personal_channel_id",
    "ensure_sandbox_custom_image_builder_task",
    "edit_task_run_living_artifact",
    "enqueue_comment_activity_retry",
    "complete_idle_local_task_run",
    "fail_task_run",
    "finalize_task_run_artifact_uploads",
    "finalize_task_staged_artifacts",
    "get_active_wizard_cloud_run",
    "get_conversation_task_dtos",
    "get_latest_pr_url_by_task",
    "get_merged_pr_task_ids",
    "get_latest_run_by_task",
    "get_resume_snapshot_carry_state",
    "get_sandbox_custom_image",
    "get_sandbox_environment",
    "get_sandbox_snapshot",
    "get_stale_prewarmed_queued_task_run_ids",
    "get_stale_terminal_prewarmed_task_run_ids",
    "get_stale_queued_task_run_ids",
    "filter_uncovered_workflow_dispatch_run_ids",
    "maintain_workflow_dispatch_outbox",
    "get_task_detail",
    "get_task_id_for_run",
    "get_task_run",
    "get_task_run_session",
    "sync_task_run_session",
    "get_task_run_detail",
    "get_task_run_sandbox_connection",
    "get_task_run_living_artifact",
    "capture_relay_command_telemetry",
    "get_task_run_stream_info",
    "get_task_summaries",
    "is_internal_debug_team",
    "is_task_controllable_by_user",
    "is_valid_sandbox_env_var_key",
    "latest_task_run_pr_merged_subquery",
    "latest_task_run_pr_url_subquery",
    "leave_task_presence",
    "list_sandbox_custom_images",
    "list_sandbox_environments",
    "sandbox_custom_images_enabled",
    "agent_peer_messaging_enabled",
    "list_task_run_living_artifacts",
    "list_task_run_peers",
    "list_task_repositories",
    "list_task_runs",
    "list_tasks",
    "pi_cloud_runtime_enabled",
    "prepare_task_run_artifact_uploads",
    "prepare_task_staged_artifacts",
    "presign_task_run_artifact",
    "presign_task_run_artifact_download",
    "read_task_run_artifact",
    "read_task_run_logs",
    "record_comment_activity",
    "signal_task_run_client_activity",
    "redeem_code_invite",
    "redispatch_task_run",
    "relay_task_run_message",
    "resolve_slack_thread_context",
    "resume_task_run_in_cloud",
    "run_task",
    "send_cancel",
    "select_repository_for_message",
    "set_task_run_output",
    "set_task_title",
    "slack_actor_state_updates",
    "signal_report_queryset",
    "signal_task_run_peer_message",
    "signal_task_run_user_message",
    "signal_workflow_completion",
    "soft_delete_task",
    "start_task_run",
    "task_accessible_for_run_view",
    "task_channel_id",
    "task_exempt_from_code_access",
    "task_exists",
    "task_ids_with_pr_url_subquery",
    "task_run_has_slack_mapping",
    "task_run_is_terminal",
    "task_run_matches_current_ownership",
    "task_runtime",
    "task_visible",
    "visible_tasks_q",
    "task_comment_mentions_allowed",
    "list_task_artifacts",
    "list_task_comments",
    "retrieve_task_comment",
    "update_sandbox_environment",
    "update_task",
    "update_task_run",
    "update_task_run_state",
    "upsert_internal_sandbox_env",
    "validate_set_output",
    "validate_task_run_sandbox_token",
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

_TASK_RUN_PUBLIC_STATE_KEYS = frozenset(
    {
        "ai_stage",
        "auto_publish",
        "context_window",
        "custom_image_id",
        "fast_mode",
        "initial_permission_mode",
        "mode",
        "model",
        "pending_user_artifact_ids",
        "pending_user_message",
        "pending_user_message_id",
        "pr_authorship_mode",
        "pr_base_branch",
        "prewarmed",
        "provider",
        "reasoning_effort",
        "repositories",
        "repository",
        "resume_from_run_id",
        "rtk_enabled",
        "run_source",
        "runtime_adapter",
        "sandbox_environment_id",
        "slack_artifact_delivery",
        "slack_chart_delivery",
        "slack_thread_url",
    }
)

# Served only to the run's own task-bound sandbox, which reads them to build the agent's
# first message; without them it silently falls back to `task.description`. Withheld from
# human readers: a workflow task is team-readable, and its boot prompt embeds the triggering
# event wholesale, which for a Slack trigger can be a private channel's message content.
_TASK_RUN_AGENT_STATE_KEYS = frozenset({"initial_prompt_override"})


def _public_task_run_state(state: dict | None, *, include_agent_keys: bool = False) -> dict:
    allowed = _TASK_RUN_PUBLIC_STATE_KEYS
    if include_agent_keys:
        allowed = allowed | _TASK_RUN_AGENT_STATE_KEYS
    return {key: value for key, value in (state or {}).items() if key in allowed}


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


def _task_run_detail_to_dto(run: TaskRun, *, include_agent_state: bool = False) -> contracts.TaskRunDetailDTO:
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
        state=_public_task_run_state(run.state, include_agent_keys=include_agent_state),
        artifacts=run.artifacts or [],
        created_at=run.created_at,
        updated_at=run.updated_at,
        completed_at=run.completed_at,
    )


class _LatestRunUnset:
    pass


_LATEST_RUN_UNSET = _LatestRunUnset()


def _task_slack_thread_references(task: Task) -> list[contracts.SlackThreadReferenceDTO]:
    references: list[contracts.SlackThreadReferenceDTO] = []
    for item in (task.state or {}).get("slack_thread_references", []):
        if not isinstance(item, dict):
            continue
        channel = item.get("channel")
        thread_ts = item.get("thread_ts")
        if not isinstance(channel, str) or not isinstance(thread_ts, str):
            continue
        references.append(
            contracts.SlackThreadReferenceDTO(
                url=f"https://slack.com/archives/{channel}/p{thread_ts.replace('.', '')}",
                channel=channel,
                created_at=item.get("created_at") if isinstance(item.get("created_at"), str) else None,
            )
        )
    return references


def get_task_for_slack_unfurl(task_id: str | UUID, team_id: int, user_id: int) -> contracts.TaskSlackUnfurlDTO | None:
    task = (
        _visible_task_qs(team_id, user_id)
        .filter(id=task_id, internal=False)
        .only("id", "title", "created_by_id")
        .first()
    )
    if task is None:
        return None
    latest_run = task.runs.order_by("-created_at").only("status").first()
    return contracts.TaskSlackUnfurlDTO(
        id=task.id,
        title=task.title,
        created_by_id=task.created_by_id,
        latest_run_status=latest_run.get_status_display() if latest_run else None,
    )


def attach_slack_thread_reference(
    *,
    task_id: str | UUID,
    team_id: int,
    slack_workspace_id: str,
    channel: str,
    thread_ts: str,
    shared_by_slack_user_id: str,
) -> None:
    reference = {
        "slack_workspace_id": slack_workspace_id,
        "channel": channel,
        "thread_ts": thread_ts,
        "shared_by_slack_user_id": shared_by_slack_user_id,
        "created_at": django_timezone.now().isoformat(),
    }
    with transaction.atomic():
        task = Task.objects.select_for_update().get(id=task_id, team_id=team_id)
        state = dict(task.state or {})
        references = list(state.get("slack_thread_references") or [])
        if any(
            item.get("slack_workspace_id") == slack_workspace_id
            and item.get("channel") == channel
            and item.get("thread_ts") == thread_ts
            for item in references
            if isinstance(item, dict)
        ):
            return
        references.append(reference)
        # Keep a rolling window to bound task state and API response size.
        state["slack_thread_references"] = references[-30:]
        task.state = state
        task.save(update_fields=["state", "updated_at"])


def has_slack_thread_reference(
    *, task_id: str | UUID, team_id: int, slack_workspace_id: str, channel: str, thread_ts: str
) -> bool:
    task = Task.objects.filter(id=task_id, team_id=team_id).only("state").first()
    if task is None:
        return False
    return any(
        item.get("slack_workspace_id") == slack_workspace_id
        and item.get("channel") == channel
        and item.get("thread_ts") == thread_ts
        for item in (task.state or {}).get("slack_thread_references", [])
        if isinstance(item, dict)
    )


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
        runtime=task.runtime,
        repository=task.repository,
        repositories=task.repositories or ([task.repository] if task.repository else []),
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
        last_activity_at=task.last_activity_at or task.updated_at,
        created_by=_user_basic_info(task.created_by if task.created_by_id else None),
        latest_run_id=latest_run_id,
        channel=task.channel_id,
        slack_thread_references=_task_slack_thread_references(task),
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


def find_signal_implementation_run(
    *, team_id: int, repository: str, head_branch: str | None
) -> contracts.SignalImplementationRunDTO | None:
    """The signals-origin implementation run that produced this PR, if any.

    Matches the PR's head branch against ``state.self_driving_head_branch``, the branch name the
    server generated at run creation (signals' auto_start) and stamped into PATCH-protected run
    state. That stamp is the only end of the run->PR link no caller can write: ``output.pr_url``
    and ``output.head_branch`` are settable by any team member with task access, so matching on
    them would let one member aim the approve-first review carve-out at an App-authored PR whose
    contents they chose. The head branch itself comes from GitHub (webhook payload or REST fetch),
    so both ends of the join are attested.

    Callers (stamphog's inbox carve-out) pass the repository the PR event came from and own fork
    safety: pass ``head_branch`` only for a repo-native head, never a fork's (a fork's head ref is
    attacker-controlled). Dropping failed and cancelled runs and soft-deleted tasks stops a dead
    or disowned run from keeping the carve-out alive on later pushes. A COMPLETED run still
    matches: success flips the run to COMPLETED right after it opens the PR, so excluding it
    would end re-reviews the moment the implementation finishes.
    """
    # TODO(security): the run->PR link is only as strong as the branch NAME, and the name is not a
    # secret. state.self_driving_head_branch is unforgeable, but the name it holds is readable by any
    # team member (auto_start writes it into the task description, and TaskRunDetailSerializer exposes
    # `state`) and low-entropy. A run that finishes WITHOUT opening a PR keeps its stamp yet leaves its
    # branch unclaimed, so a member can read the name, have their own task's agent push an App-authored
    # repo-native PR from that exact branch, then set_output the original run's pr_url to fire the
    # carve-out: the head ref genuinely belongs to this run, so an approve-first review lands on a PR
    # whose contents they chose. The real fix is to bind on the head SHA the sandbox actually pushed
    # (recorded server-side into protected state) rather than the branch name, because a run that never
    # pushed has no SHA to bind, which removes the unclaimed-branch surface entirely; re-reviews then
    # pin to the PR identity once the first attested SHA establishes it. It is a heavy change (sandbox
    # has to report the pushed SHA back, and the re-review path needs the PR-identity pin), so it is
    # deferred. The exposure is intra-tenant and gated behind an opt-in toggle that defaults off, which
    # makes it an accepted residual for the current internal rollout; close it before any external one.
    if not head_branch:
        return None
    run = (
        TaskRun.objects.filter(
            team_id=team_id,
            state__self_driving_head_branch=head_branch,
            task__repository__iexact=repository.strip(),
            task__deleted=False,
        )
        .exclude(status__in=(TaskRun.Status.FAILED, TaskRun.Status.CANCELLED))
        .order_by("-created_at")
        .select_related("task")
        .first()
    )
    if run is None or run.team_id != team_id:
        return None
    task = run.task
    # Belt and braces: only signals' auto_start stamps the branch key today, but the ai_stage and
    # signal-report checks keep a future writer of the key from silently widening the carve-out.
    if task.signal_report_id is None or (run.state or {}).get("ai_stage") != "implementation":
        return None
    return contracts.SignalImplementationRunDTO(
        run_id=run.id,
        task_id=task.id,
        team_id=run.team_id,
        signal_report_id=task.signal_report_id,
        task_created_by_id=task.created_by_id,
    )


def get_wizard_pr_ready_email_context(run_id: str | UUID) -> contracts.WizardPrReadyEmailContextDTO | None:
    """Data ``send_wizard_pr_ready_email`` needs for a run, or ``None`` if the run has no PR URL yet."""
    run = TaskRun.objects.select_related("task").filter(id=run_id).first()
    if run is None:
        return None
    pr_url = (run.output or {}).get("pr_url") if isinstance(run.output, dict) else None
    if not pr_url:
        return None
    task = run.task
    return contracts.WizardPrReadyEmailContextDTO(
        task_id=task.id,
        run_id=run.id,
        team_id=run.team_id,
        origin_product=task.origin_product,
        pr_url=pr_url,
        repository=task.repository,
        branch=run.branch,
        created_by_id=task.created_by_id,
        already_sent=task.pr_ready_email_sent_at is not None,
    )


def mark_task_pr_ready_email_sent(task_id: str | UUID, pr_url: str) -> None:
    """Record confirmed PR-ready email delivery for a task, if it still exists."""
    task = Task.objects.filter(id=task_id).first()
    if task is not None:
        task.mark_pr_ready_email_sent(pr_url)


def get_task_id_for_run(run_id: str | UUID, team_id: int) -> UUID | None:
    """The parent task id for a run, team-scoped. ``None`` if the run isn't found for the team.

    A lightweight ``task_run_id -> task_id`` resolution (no DTO build) for callers that only
    need to deep-link a run to its task.
    """
    return TaskRun.objects.filter(id=run_id, team_id=team_id).values_list("task_id", flat=True).first()


def task_exists(task_id: str | UUID, team_id: int) -> bool:
    """Whether a (non-deleted) task exists for the team."""
    return Task.objects.filter(id=task_id, team_id=team_id, deleted=False).exists()


def task_channel_id(task_id: str | UUID, team_id: int) -> UUID | None:
    """The channel a (non-deleted) task is filed in, or None."""
    return Task.objects.filter(id=task_id, team_id=team_id, deleted=False).values_list("channel_id", flat=True).first()


def task_owned_by_user(task_id: str | UUID, team_id: int, user_id: int) -> bool:
    return Task.objects.filter(id=task_id, team_id=team_id, created_by_id=user_id).exists()


def task_exempt_from_code_access(task_id: str | UUID, team_id: int) -> bool:
    """Whether this task's cloud runs are entitled outside PostHog Desktop.

    The run/command endpoints gate on Desktop access (``code_access_required_response``) but
    also serve the generally-available Inbox, whose tasks must run without the waitlist. Only
    server-verifiable Inbox shapes qualify:

    - ``SIGNAL_REPORT`` linked to a report in this team and repo-less (Inbox "Discuss").
      Reports are minted by scouts and the link is team-scoped by the write serializer, so a
      caller can't forge one. Acting on a report is entitled through self-driving
      (`product-autonomy`). Repository-backed report tasks require Desktop access.
    - ``SIGNALS_CHAT`` (Inbox scout chat), reserved for server-side creation by the signals
      scout-chat endpoint; the write serializer rejects it from API callers. Only while
      repo-less: chat tasks are minted without repositories, and attaching one via update
      would turn the exemption into ungated cloud code work.

    A bare ``SIGNAL_REPORT`` origin without a report link deliberately does not qualify:
    ``origin_product`` is client input, so an FK-less claim would be a one-field waitlist
    bypass. The report's own team is re-checked here even though the write serializer
    already enforces it, so a future write path can't silently widen the exemption.
    """
    return Task.objects.filter(
        Q(
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
            signal_report__team_id=team_id,
            repository__isnull=True,
            repositories=[],
            github_integration__isnull=True,
            github_user_integration__isnull=True,
        )
        | Q(
            origin_product=Task.OriginProduct.SIGNALS_CHAT,
            repository__isnull=True,
            repositories=[],
            github_integration__isnull=True,
            github_user_integration__isnull=True,
        ),
        id=task_id,
        team_id=team_id,
    ).exists()


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


def task_ids_with_pr_url_subquery(team_id: int, *conditions: Q) -> QuerySet[TaskRun, Any]:
    """A ``values('task_id')`` queryset of ``team_id``'s tasks that produced a non-empty ``output.pr_url``,
    narrowed by any extra ``Q`` ``conditions`` on the run.

    For embedding in a caller's ``task_id__in=...`` lookup so the report→PR correlation can be
    *decorrelated*: instead of a per-report ``Exists`` over runs, the caller drives off this small,
    index-backed set (served by the partial ``task_run_output_pr_url_idx``) and joins outward to its
    own report-association tables. Returns a query expression — no ORM instances cross the boundary.

    Scoped to ``team_id`` so the set stays bounded to the request's tenant rather than scanning every
    team's PR-bearing runs — associated runs are always same-team, so this drops no valid matches.
    """
    return (
        TaskRun.objects.filter(*conditions, team_id=team_id, output__pr_url__isnull=False)
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


def latest_task_run_pr_merged_subquery(*conditions: Q, **task_run_filter) -> Subquery:
    """``Subquery`` of the webhook-attested merge flag on the same run ``latest_task_run_pr_url_subquery``
    resolves for the same correlation — so a caller displaying that PR can say whether it merged rather
    than inferring it. Same filter and ordering, so the two always describe one run. NULL when no
    PR-bearing run matches; treat that as "not merged"."""
    return Subquery(
        TaskRun.objects.filter(*conditions, output__pr_url__isnull=False, **task_run_filter)
        .exclude(output__pr_url="")
        .order_by("-created_at")
        .annotate(output_pr_merged_flag=KeyTextTransform("pr_merged", "output"))
        .values("output_pr_merged_flag")[:1],
        output_field=CharField(),
    )


def get_merged_pr_task_ids(task_ids: Iterable[str | UUID]) -> set[str]:
    """Of the supplied tasks, those whose latest PR-bearing run has a webhook-attested merged PR.

    Batched counterpart to ``latest_task_run_pr_merged_subquery``, matching ``get_latest_pr_url_by_task``
    run-for-run so the merge flag describes the PR URL that helper returns.
    """
    ids = [str(t) for t in task_ids]
    if not ids:
        return set()
    rows = (
        TaskRun.objects.filter(task_id__in=ids, output__pr_url__isnull=False)
        .exclude(output__pr_url="")
        .order_by("task_id", "-created_at", "-id")
        .annotate(output_pr_merged_flag=KeyTextTransform("pr_merged", "output"))
        .values("task_id", "output_pr_merged_flag")
        .distinct("task_id")
    )
    return {str(row["task_id"]) for row in rows if row["output_pr_merged_flag"] in ("true", "True")}


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


def get_active_wizard_cloud_run(team_id: int) -> contracts.WizardCloudRunDTO | None:
    """The team's active onboarding wizard cloud run, for rehydrating the setup FAB.

    The drop flow starts the wizard cloud run server-side (``create_wizard_cloud_run``),
    so a freshly-signed-in user has no client-side handle. Returns the most recent run
    across the team's onboarding (``ORIGIN_PRODUCT == ONBOARDING``) tasks that's still
    running, or completed within the last day (so we can show "PostHog is wired up" +
    the PR); otherwise ``None``. Team-scoped.
    """
    onboarding_task_ids = Task.objects.filter(
        team_id=team_id, origin_product=Task.OriginProduct.ONBOARDING, archived=False
    ).values_list("id", flat=True)
    fresh_after = django_timezone.now() - timedelta(days=1)
    # Scan runs newest-first and surface the first that qualifies: picking the newest task up front
    # would let a newer onboarding task with no live run hide an older task's still-running one.
    # Both the task set and the run are scoped by team_id so a mismatched/legacy run row can't leak
    # another team's handle back to the requester.
    #
    # ``origin_product == ONBOARDING`` is caller-settable, so it alone can't tell a genuine
    # server-started wizard run from one a project member planted through the normal task APIs.
    # Also require the immutable markers ``create_wizard_cloud_run`` stamps: a cloud environment
    # and the ``wizard_config`` state key (a protected key callers cannot set, see the run PATCH
    # allowlist), so we never hand a provisioned user someone else's attacker-controlled handle.
    runs = TaskRun.objects.filter(
        task_id__in=onboarding_task_ids,
        team_id=team_id,
        environment=TaskRun.Environment.CLOUD,
        state__has_key="wizard_config",
    ).order_by("-created_at", "-id")
    for run in runs:
        # Non-terminal runs always surface; terminal ones only while the result is still
        # fresh enough to be worth showing on first landing.
        if run.is_terminal:
            anchor = run.updated_at or run.created_at
            if anchor is None or anchor < fresh_after:
                continue
        return contracts.WizardCloudRunDTO(
            task_id=run.task_id,
            run_id=run.id,
            status=run.status,
            started_at=run.created_at,
        )
    return None


def get_stale_queued_task_run_ids(
    older_than: timedelta,
    limit: int,
    *,
    created_hard_cap: timedelta | None = None,
    hard_cap_min_queued: timedelta = timedelta(hours=1),
    environment: str | None = None,
    exclude_covered_dispatches: bool = False,
) -> list[UUID]:
    """Ids of runs stuck in QUEUED, by ``updated_at`` age or an optional ``created_at`` backstop.

    ``environment`` restricts the sweep to runs of that environment. A QUEUED cloud run is
    awaiting a workflow that should have started, but a local (desktop) run sits in QUEUED by
    design while the desktop agent drives it — so sweep callers must scope themselves and act
    per environment: dispatch recovery must only touch cloud runs (cloud-dispatching a local
    run hijacks the user's live local session), and the janitor fails stale cloud runs but
    quietly completes stale local ones.

    Intentionally cross-team — the janitor sweep runs without a team context.
    """
    now = django_timezone.now()
    stale = Q(updated_at__lt=now - older_than)
    if created_hard_cap is not None:
        stale |= Q(created_at__lt=now - created_hard_cap, updated_at__lt=now - hard_cap_min_queued)
    queryset = TaskRun.objects.filter(status=TaskRun.Status.QUEUED)  # nosemgrep: celery-task-team-scope-audit
    if environment is not None:
        queryset = queryset.filter(environment=environment)
    if exclude_covered_dispatches:
        queryset = queryset.exclude(
            workflow_dispatches__status__in=(TaskWorkflowDispatch.Status.PENDING, TaskWorkflowDispatch.Status.CLAIMED)
        )
    elif environment == TaskRun.Environment.CLOUD:
        queryset = queryset.exclude(
            workflow_dispatches__status__in=("pending", "claimed"),
            workflow_dispatches__enqueued_at__gte=now
            - timedelta(seconds=settings.TASKS_DISPATCHER_MAX_DISPATCH_AGE_SECONDS),
        )
    return list(queryset.filter(stale).order_by("updated_at").values_list("id", flat=True)[:limit])


def filter_uncovered_workflow_dispatch_run_ids(candidate_ids: list[UUID]) -> list[UUID]:
    from products.tasks.backend.metrics import WORKFLOW_DISPATCH_MISSING_INTENT_TOTAL  # noqa: PLC0415

    live_dispatch_run_ids = set(
        TaskWorkflowDispatch.objects.unscoped()
        .filter(
            task_run_id__in=candidate_ids,
            status__in=(TaskWorkflowDispatch.Status.PENDING, TaskWorkflowDispatch.Status.CLAIMED),
        )
        .values_list("task_run_id", flat=True)
    )
    uncovered_ids = [run_id for run_id in candidate_ids if run_id not in live_dispatch_run_ids]
    if not is_workflow_dispatch_shadow_enabled():
        return uncovered_ids
    runs = {
        run.id: run
        for run in TaskRun.objects.filter(
            id__in=uncovered_ids
        ).select_related(  # nosemgrep: celery-task-team-scope-audit
            "task"
        )
    }
    dispatch_run_ids = set(
        TaskWorkflowDispatch.objects.unscoped()
        .filter(task_run_id__in=uncovered_ids)
        .values_list("task_run_id", flat=True)
    )
    for run_id in uncovered_ids:
        run = runs.get(run_id)
        state = run.state if run and isinstance(run.state, dict) else {}
        has_legacy_intent = bool(state.get("pending_dispatch"))
        awaiting_restart_rollout = bool(state.get("handoff_resumed"))
        if run_id not in dispatch_run_ids and not has_legacy_intent and not awaiting_restart_rollout:
            WORKFLOW_DISPATCH_MISSING_INTENT_TOTAL.inc()
            logger.warning(
                "workflow_dispatch_missing_intent",
                extra={
                    "run_id": str(run_id),
                    "task_id": str(run.task_id) if run else None,
                    "team_id": run.team_id if run else None,
                    "origin_product": run.task.origin_product if run else None,
                },
            )
    return uncovered_ids


def maintain_workflow_dispatch_outbox() -> None:
    now = django_timezone.now()
    TaskWorkflowDispatch.objects.unscoped().filter(
        status=TaskWorkflowDispatch.Status.PENDING,
    ).exclude(task_run__status=TaskRun.Status.QUEUED).update(
        status=TaskWorkflowDispatch.Status.ACCEPTED,
        accepted_at=now,
        last_error="resolved: run left QUEUED",
    )
    TaskWorkflowDispatch.objects.unscoped().filter(
        status=TaskWorkflowDispatch.Status.CLAIMED,
        lease_expires_at__lt=now - timedelta(minutes=10),
    ).update(
        status=TaskWorkflowDispatch.Status.PENDING,
        claimed_by="",
        lease_expires_at=None,
        next_attempt_at=now,
    )
    accepted_ids = list(
        TaskWorkflowDispatch.objects.unscoped()
        .filter(status=TaskWorkflowDispatch.Status.ACCEPTED, accepted_at__lt=now - timedelta(days=14))
        .order_by("accepted_at")
        .values_list("id", flat=True)[:1000]
    )
    TaskWorkflowDispatch.objects.unscoped().filter(id__in=accepted_ids).delete()
    dead_ids = list(
        TaskWorkflowDispatch.objects.unscoped()
        .filter(status=TaskWorkflowDispatch.Status.DEAD, updated_at__lt=now - timedelta(days=30))
        .order_by("updated_at")
        .values_list("id", flat=True)[:1000]
    )
    TaskWorkflowDispatch.objects.unscoped().filter(id__in=dead_ids).delete()


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


def get_stale_terminal_prewarmed_task_run_ids(older_than: timedelta, limit: int) -> list[UUID]:
    now = django_timezone.now()
    return list(
        TaskRun.objects.filter(  # nosemgrep: celery-task-team-scope-audit
            status__in=[TaskRun.Status.COMPLETED, TaskRun.Status.FAILED, TaskRun.Status.CANCELLED],
            state__prewarmed=True,
            state__await_user_message=True,
            task__deleted=False,
            task__title="",
            task__description="",
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

    A QUEUED run's age counts from ``queued_at``, not from row creation:
    ``prepare_for_cloud_handoff`` re-queues an existing run without resetting ``created_at``,
    so a desktop-to-cloud handoff would otherwise report the whole prior run's lifetime as
    queue wait. Rows queued before ``queued_at`` existed fall back to ``created_at``, which is
    exact for a run that was only ever queued once. Every other non-terminal status counts
    from creation, where elapsed lifetime is the useful age.
    """
    now = django_timezone.now()
    window_start = now - timedelta(seconds=window_seconds)
    age_anchor = Case(
        When(status=TaskRun.Status.QUEUED, then=Coalesce(F("queued_at"), F("created_at"))),
        default=F("created_at"),
        output_field=DateTimeField(),
    )
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
            .annotate(oldest_waiting_since=Min(age_anchor)),
            "oldest_waiting_since",
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
    channel_id: str | UUID | None = None,
    **extra,
) -> contracts.CreatedTaskDTO:
    """Create a task and (optionally) kick off its processing workflow.

    Thin wrapper over ``Task.create_and_run`` that returns ids + the created run as a DTO
    instead of leaking the ORM ``Task``. ``team`` is a core ``posthog.Team`` (not a tasks
    model). Less-common keyword arguments are forwarded verbatim via ``**extra``.

    ``channel_id`` files the task into a channel's feed; left NULL for non-channel surfaces.
    An id the creator can't file into (see ``_visible_channel``) is ignored rather than
    raising — feed placement must never break task creation.
    """
    # create_pr=False sessions (research, repo selection, custom agents) can never open the
    # billable PR, so the quota gate must not block them.
    if origin_product == Task.OriginProduct.SIGNAL_REPORT and create_pr:
        # Distinct stage from create_task's `manual_create`: the main caller here is the
        # auto-start pipeline, whose over-quota hits must not pollute the manual-path
        # dark-launch bucket.
        enforce_self_driving_pr_quota(team, report_id=signal_report_id, stage="task_create")
    channel = _visible_channel(channel_id, team.id, user_id) if channel_id is not None else None
    if channel is None and not internal and origin_product not in TEAM_READABLE_ORIGIN_PRODUCTS:
        channel = _ensure_personal_channel(team.id, user_id)[0]
    task = Task.create_and_run(
        team=team,
        title=title,
        description=description,
        origin_product=origin_product,
        user_id=user_id,
        repository=repository,
        channel=channel,
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

    The model is pinned rather than left to the agent's default because these runs bill to nobody:
    they route to the unbilled ``onboarding`` gateway product, whose model allowlist is narrow, and
    PostHog absorbs the cost. Keep the pin inside that allowlist or the run fails at the gateway.
    """
    head_branch = generate_wizard_head_branch()
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
        runtime_adapter=WIZARD_CLOUD_RUN_RUNTIME_ADAPTER,
        model=WIZARD_CLOUD_RUN_MODEL,
        ai_stage=WIZARD_CLOUD_RUN_AI_STAGE,
        # The agent server boots idle; this is the message that actually kicks it off once ready
        # (delivered by forward_pending_user_message). Without it the run stalls after "Started agent".
        pending_user_message=prompt,
    )


def recent_wizard_cloud_run_times(user_id: int, since: datetime) -> list[datetime]:
    """Creation times of a user's recent wizard cloud runs that still count against their quota.

    Backs the outcome-aware cloud_run throttles: failed and cancelled runs are excluded so a
    user whose run broke (or who cancelled a stuck one) can start another without waiting out
    the window. The hard ceiling on total attempts lives in the cloud_run view as an atomic
    cache reservation, not here.

    The filter trusts only PATCH-immutable markers: ``created_by`` (set at creation) and the
    protected ``wizard_config`` state key that only ``create_wizard_cloud_run`` stamps (see
    ``_PROTECTED_RUN_STATE_KEYS``). Mutable fields like the run's ``environment`` are
    deliberately NOT filtered — a run PATCHed from cloud to local must keep consuming quota,
    or flipping it would launder sandbox boots out of the limits.

    Deliberately user-scoped across teams: the throttle is per user, and a user can run the
    wizard on projects in different teams. Returns only timestamps, no run data.
    """
    return list(
        TaskRun.objects.filter(
            task__created_by_id=user_id,
            state__has_key="wizard_config",
            created_at__gte=since,
        )
        .exclude(status__in=[TaskRun.Status.FAILED, TaskRun.Status.CANCELLED])
        .order_by("created_at")
        .values_list("created_at", flat=True)
    )


def create_task_without_run(
    *,
    team,
    user_id: int,
    origin_product: "Task.OriginProduct",
    title: str = "",
    description: str = "",
    repository: str | None = None,
    mcp_builtin_agent_key: MCPBuiltInAgentKey | None = None,
    channel: Channel | None = None,
) -> UUID:
    """Create a Task row with no initial run, returning its id.

    For callers that own run creation themselves — e.g. the sandbox warm path, which boots the first
    run via the warming facade. ``team`` is a core ``posthog.Team`` (not a tasks model).
    """
    if channel is None:
        channel = (
            None if origin_product in TEAM_READABLE_ORIGIN_PRODUCTS else _ensure_personal_channel(team.id, user_id)[0]
        )
    task = Task.create_without_run(
        team=team,
        title=title,
        description=description,
        origin_product=origin_product,
        user_id=user_id,
        repository=repository,
        channel=channel,
        mcp_builtin_agent_key=mcp_builtin_agent_key,
    )
    return task.id


def create_channel_task(team_id: int, user_id: int, channel_id: str | UUID, *, title: str, description: str) -> UUID:
    """Create a task filed into a channel, as the user — for product surfaces
    (canvas actions) that file work into their own channel. No initial run:
    the channel's feed shows it and the user drives it from there.
    """
    channel = (
        Channel.objects.for_team(team_id).filter(Channel.visible_to_q(user_id), id=channel_id, deleted=False).first()
    )
    if channel is None:
        raise ValueError("Channel not found in this team.")
    return create_task_without_run(
        team=Team.objects.get(id=team_id),
        user_id=user_id,
        origin_product=Task.OriginProduct.USER_CREATED,
        title=title,
        description=description,
        channel=channel,
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


def signal_task_run_client_activity(run_id: str | UUID, task_id: str | UUID, team_id: int) -> None:
    """Best-effort: tell the run's workflow a client command landed, so the idle timer resets."""
    try:
        run = TaskRun.objects.filter(id=run_id, task_id=task_id, team_id=team_id).only("id", "task_id", "state").first()
        if run is not None:
            run.signal_client_activity()
    except Exception:
        logger.warning("Failed to signal client activity for task run %s", run_id)


def slack_actor_state_updates(*, user_id: int, slack_user_id: str | None = None) -> dict[str, Any]:
    """Run-state updates recording the Slack user currently steering a run.

    Credential resolution and reply tagging read the keys this builds, so every
    writer must go through here rather than assembling the dict inline.
    """
    from products.tasks.backend.logic.services.run_actor import (  # noqa: PLC0415 — keep tasks internals off the api import path
        slack_actor_state_updates as _slack_actor_state_updates,
    )

    return _slack_actor_state_updates(user_id=user_id, slack_user_id=slack_user_id)


def set_task_run_created_at_for_seeding(
    run_id: str | UUID, task_id: str | UUID, team_id: int, *, created_at: datetime
) -> None:
    """Backdate a run's ``created_at`` — DEBUG-only escape hatch for dev seeding.

    Signals' billing/refund seeding needs runs whose billable moment falls on an earlier UTC
    day; ``created_at`` is deliberately not writable through the PATCH surface, so the hatch
    lives here rather than callers reaching into the ORM.
    """
    if not settings.DEBUG:
        raise RuntimeError("set_task_run_created_at_for_seeding is DEBUG-only")
    TaskRun.objects.filter(pk=run_id, task_id=task_id, team_id=team_id).update(created_at=created_at)


def fail_task_run(run_id: str | UUID, error: str, error_type: str | None = None) -> bool:
    """Mark a QUEUED run as failed. Returns whether a run was acted on.

    Refetches filtered on ``status=QUEUED`` so a run that left the queue between the
    candidate scan and this call is skipped. Intentionally cross-team (janitor sweep).
    """
    run = TaskRun.objects.filter(
        pk=run_id, status=TaskRun.Status.QUEUED
    ).first()  # nosemgrep: celery-task-team-scope-audit
    if run is None:
        return False
    run.mark_failed(error, error_type=error_type)
    run.task.soft_delete_if_unclaimed_prewarm(run)
    return True


def soft_delete_unclaimed_prewarm_task(run_id: str | UUID) -> bool:
    run = TaskRun.objects.select_related("task").filter(pk=run_id).first()  # nosemgrep: celery-task-team-scope-audit
    return run.task.soft_delete_if_unclaimed_prewarm(run) if run is not None else False


def complete_idle_local_task_run(run_id: str | UUID) -> bool:
    """Quietly finalize a local (desktop-driven) run left idling in QUEUED. Returns whether
    a run was acted on.

    Local runs never get a cloud workflow, so QUEUED is their steady state while the desktop
    drives the session — once the desktop goes away, nothing else ever terminalizes the row.
    An idle session that ended is the run's normal end state, so it finalizes as COMPLETED,
    and without a push notification: pinging a user a day after they closed their session is
    noise, not signal.

    Compare-and-set claim (like ``claim_and_fail_stale_run``): the conditional update flips the
    run only while it is still QUEUED *and* local, so a run that left the queue — or was handed
    off to cloud (handoff keeps status QUEUED) — between the candidate scan and this call is
    skipped rather than terminalized under its just-dispatched workflow. The winner finalizes
    via ``mark_completed`` (``completed_at``, stream + analytics). Intentionally cross-team
    (janitor sweep).
    """
    claimed = TaskRun.objects.filter(
        pk=run_id, status=TaskRun.Status.QUEUED, environment=TaskRun.Environment.LOCAL
    ).update(status=TaskRun.Status.COMPLETED)  # nosemgrep: celery-task-team-scope-audit
    if not claimed:
        return False
    run = TaskRun.objects.filter(pk=run_id).first()  # nosemgrep: celery-task-team-scope-audit
    if run is not None:
        run.mark_completed(notify=False, analytics_properties={"finalized_by": "stale_local_queued_sweep"})
    return True


def claim_and_fail_stale_run(run_id: str | UUID, error: str, error_type: str | None = None) -> bool:
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
        run.mark_failed(error, error_type=error_type)
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

    Only rows already carrying the requested ``internal`` flag are matched for reuse: users
    can create environments with arbitrary names through the sandbox environment API, and a
    same-named user row must never be adopted (or deleted) by internal provisioning — the
    internal env is created alongside it instead. Reasserted policy covers the whole
    execution surface, not just network: the user-controllable ``custom_image``,
    ``environment_variables``, and ``repositories`` fields are cleared on every call, so
    nothing a person set on a row (before or after it became internal) can ride into an
    internally provisioned run.

    ``SandboxEnvironment`` has no unique constraint on ``(team_id, name)``, so concurrent
    callers can both INSERT. We dedupe on ``MultipleObjectsReturned`` by keeping the oldest
    matching row and deleting the rest.
    """
    defaults: dict = {
        "network_access_level": network_access_level,
        "private": private,
        "custom_image": None,
        "environment_variables": {},
        "repositories": [],
    }
    if allowed_domains is not None:
        defaults["allowed_domains"] = normalize_sandbox_allowed_domains(allowed_domains)
        defaults["include_default_domains"] = include_default_domains
    try:
        env, _ = SandboxEnvironment.objects.update_or_create(
            team_id=team_id, name=name, internal=internal, defaults=defaults
        )
        return env.id
    except SandboxEnvironment.MultipleObjectsReturned:
        with transaction.atomic():
            dupes = list(
                SandboxEnvironment.objects.filter(team_id=team_id, name=name, internal=internal).order_by("created_at")
            )
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


# --- Desktop invites ---


def get_desktop_beta_terms_acceptance(organization_id: UUID) -> contracts.DesktopBetaTermsAcceptanceDTO:
    return contracts.DesktopBetaTermsAcceptanceDTO(
        is_desktop_beta_terms_accepted=DesktopBetaTermsAcceptance.objects.filter(
            organization_id=organization_id
        ).exists()
    )


def accept_desktop_beta_terms(organization_id: UUID, user_id: int) -> contracts.DesktopBetaTermsAcceptanceDTO:
    DesktopBetaTermsAcceptance.objects.get_or_create(
        organization_id=organization_id,
        defaults={"accepted_by_user_id": user_id},
    )
    return contracts.DesktopBetaTermsAcceptanceDTO(is_desktop_beta_terms_accepted=True)


def redeem_code_invite(code: str, user_id: int) -> contracts.CodeInviteRedeemResult:
    """Redeem a PostHog Desktop invite for a user.

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


def normalize_sandbox_allowed_domains(allowed_domains: list[str]) -> list[str]:
    if len(allowed_domains) > MAX_SANDBOX_ALLOWED_DOMAINS:
        raise ValueError(f"You can allow up to {MAX_SANDBOX_ALLOWED_DOMAINS} domains")
    return list(normalize_requested_domains(allowed_domains))


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
    normalized_allowed_domains = normalize_sandbox_allowed_domains(allowed_domains)
    env = SandboxEnvironment.objects.create(
        team_id=team_id,
        created_by_id=user_id,
        name=name,
        network_access_level=network_access_level,
        allowed_domains=normalized_allowed_domains,
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
    if "allowed_domains" in fields:
        fields["allowed_domains"] = normalize_sandbox_allowed_domains(fields["allowed_domains"])
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
    from products.tasks.backend.metrics import (
        observe_custom_image_build,  # noqa: PLC0415 — keep prometheus deps off the api import path
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

    updated = (
        _accessible_custom_images(team_id, user_id)
        .filter(id=image.id)
        .exclude(status__in=(SandboxCustomImage.Status.SCANNING, SandboxCustomImage.Status.BUILDING))
        .update(
            spec=spec.model_dump(),
            status=SandboxCustomImage.Status.SCANNING,
            error="",
            updated_at=django_timezone.now(),
        )
    )
    if not updated:
        raise ValueError("A build is already in progress for this image")

    observe_custom_image_build("started")
    execute_build_sandbox_image_workflow(str(image.id), team_id)
    return _reload_image_dto(image.pk)


def update_sandbox_custom_image(
    image_id: str | UUID,
    team_id: int,
    user_id: int,
    *,
    name: str | None = None,
    description: str | None = None,
) -> contracts.SandboxCustomImageDTO | None:
    """Rename (and optionally re-describe) a visible custom image.

    Only mutable metadata (`name`, `description`) is editable here — the build spec,
    status, and published image reference are managed by the build/scan flow. Returns
    ``None`` when the image is not visible to the caller.
    """
    updates: dict[str, str] = {}
    if name is not None:
        updates["name"] = name
    if description is not None:
        updates["description"] = description
    if not updates:
        return get_sandbox_custom_image(image_id, team_id, user_id)

    updated = (
        _accessible_custom_images(team_id, user_id)
        .filter(id=image_id)
        .update(**updates, updated_at=django_timezone.now())
    )
    if not updated:
        return None
    # Re-read through get_sandbox_custom_image rather than _reload_image_dto: if a
    # concurrent delete removes the row between the update above and this read,
    # `.first()` returns None (→ 404) instead of .get() raising DoesNotExist (→ 500).
    return get_sandbox_custom_image(image_id, team_id, user_id)


def delete_sandbox_custom_image(image_id: str | UUID, team_id: int, user_id: int) -> bool:
    """Delete a visible custom image. Environments referencing it fall back to the default base (SET_NULL)."""
    image = _accessible_custom_images(team_id, user_id).filter(id=image_id).first()
    if image is None:
        return False
    image.delete()
    return True


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
#   - use_modal_vm_sandbox is reserved for trusted server-created runs such as image builders;
#     a caller could otherwise force the VM runtime while the feature flag or custom-image gate is off.
#   - snapshot_external_id / snapshot_kind / snapshot_mount_path control which Modal image is
#     restored on resume and where directory snapshots are mounted.
#   - workflow_id is the run's Temporal workflow address (``TaskRun.workflow_id`` prefers it over
#     the derived id); a caller could otherwise repoint their run at another team's workflow and
#     signal or terminate-and-restart it.
#   - pending_external_followups / pending_external_followups_generation are the workflow-owned
#     durable queue; a caller could otherwise inject actor identity into a restored follow-up.
#   - timed_out_inactivity / timed_out_wall_clock / sandbox_gone are the workflow's terminal reason
#     markers, written only by the update_task_run_status activity. Slack reads them to decide that
#     a FAILED run was a timeout and stays quiet (post_slack_update._post_failure_or_timeout), so a
#     caller could otherwise stamp one on a genuine failure and suppress its error card.
# These keys are reserved for server-owned run state, never PATCH input.
_PROTECTED_RUN_STATE_KEYS = frozenset(
    {
        "github_credential_source",
        TASK_OWNERSHIP_VERSION_STATE_KEY,
        "pr_authorship_mode",
        "repositories",
        "verified_pr_urls",
        "sandbox_id",
        "sandbox_cpu_cores",
        "sandbox_memory_gb",
        "sandbox_ttl_seconds",
        "inactivity_timeout_seconds",
        "wizard_config",
        "wizard_head_branch",
        "use_modal_directory_resume_snapshots",
        "use_modal_vm_sandbox",
        # Rollout stamps written once at dispatch by _capture_run_feature_flags; a PATCHable
        # value would let a task controller bypass the org feature flags (for telemetry, that
        # means injecting the internal OTLP capture token into their sandbox and re-enabling
        # the run-log mirror with the rollout off).
        AGENT_OTEL_TELEMETRY_STATE_KEY,
        "sandbox_event_ingest_enabled",
        "snapshot_external_id",
        "snapshot_kind",
        "snapshot_mount_path",
        "workflow_id",
        "pending_dispatch",
        # Written once at loop fire time; seeding copies these storage paths into the
        # run's artifact prefix, so a PATCHable value would be an arbitrary
        # object-storage read (and write-location) primitive.
        "skill_bundle_seeds",
        "cancel_requested_at",
        "cancel_requested_by_user_id",
        "cancel_source",
        "cancel_fallback_cleanup_complete",
        "pending_external_followups",
        "pending_external_followups_generation",
        # Terminal reason markers owned by the workflow (see the note above). Spelled as literals
        # rather than imported from the update_task_run_status activity, which would pull temporalio
        # onto this module's import path; the workflow writes them through
        # TaskRun.update_state_atomic, which does not go through this filter.
        "timed_out_inactivity",
        "timed_out_wall_clock",
        "sandbox_gone",
        TASK_ANALYSIS_INSIGHTS_STATE_KEY,
        ANALYSIS_TARGET_TASK_ID_STATE_KEY,
        ANALYSIS_TARGET_RUN_ID_STATE_KEY,
        # Server-stamped at analysis creation (task_analysis._target_context_state) and read back
        # at insight-report time to attribute the captured event to a repository and sandbox
        # image. A PATCHable value would let the sandbox agent forge that attribution.
        ANALYSIS_TARGET_REPOSITORY_STATE_KEY,
        ANALYSIS_TARGET_IMAGE_ID_STATE_KEY,
        ANALYSIS_TARGET_IMAGE_NAME_STATE_KEY,
        # Credential grant decided at Task.create_and_run time by server-owned callers (the scout
        # runner); a PATCHable key would let any task controller mint a GitHub token onto a
        # queued repo-less run.
        "github_read_access",
        # Loop provenance is stamped once at run creation (see loop_runs._create_loop_task_and_run)
        # and drives loop bookkeeping in handle_loop_run_terminal. The completion marker prevents
        # terminal bookkeeping from running twice. A caller must not be able to forge either.
        "loop_id",
        "loop_trigger_id",
        "trigger_context",
        "config_snapshot",
        "loop_terminal_bookkeeping_complete",
        # Stamped once at run creation. The review carve-outs read ai_stage="implementation" as proof
        # a run is self-driving, so a PATCHable value would forge that and unlock the bot/draft bypass.
        # is_interactive_signals_run reads its presence the same way, to tell a pipeline-started
        # signals run from one a person started; forging it would move the run off the interactive
        # budget and out of its per-run spend ceiling.
        "ai_stage",
        # The server-generated head branch the run->PR link is keyed on (find_signal_implementation_run).
        # A PATCHable value would let a caller re-aim the approve-first carve-out at any App-authored
        # PR, which is the exact forgery the stamp exists to prevent.
        "self_driving_head_branch",
        # The run's model posture, chosen at creation by the server-owned caller and read back out
        # of state when the run dispatches. It decides what the run costs, and for a run routed to
        # an unbilled gateway product (create_wizard_cloud_run pins claude-sonnet-5 for the
        # `onboarding` product) it is the only thing keeping the run off the more expensive models
        # that product still allowlists. Every writer is server-side, so nothing legitimate PATCHes
        # these.
        "runtime_adapter",
        "provider",
        "model",
        "reasoning_effort",
    }
)

_TERMINAL_TASK_RUN_STATUSES = (TaskRun.Status.COMPLETED, TaskRun.Status.FAILED, TaskRun.Status.CANCELLED)

# `output.pr_merged` is GitHub's word, recorded by the PR webhook (`_record_run_pr_merged`) — never
# the caller's. Signals reads it to decide refund finality (billing.report_pr_is_merged): a report
# whose PR merged keeps its resolved status through a refund instead of being suppressed and having
# its PR closed. Any caller-writable path to this flag would let a `task:write` holder mark an open
# PR merged, resolve the report, and refund it while keeping the work — so every output writer has to
# go through `_merge_caller_output`, not merge caller output directly.
_WEBHOOK_ATTESTED_RUN_OUTPUT_KEYS = frozenset({"pr_merged"})


def _apply_caller_output(stored: object, incoming: dict, merged: dict) -> dict:
    """Enforce the webhook-attested keys on a caller's output write.

    `merged` is whatever the writer built from `incoming` (a wholesale replacement for
    `set_task_run_output`, a merge over stored output for the PATCH path); this drops any attested
    key the caller supplied and restores the stored one. The attestation is bound to the PR it was
    made about, so when the caller points the run at a different `pr_url` the stored flag described
    the old PR and is dropped rather than silently transferred onto the new one.
    """
    existing = stored if isinstance(stored, dict) else {}
    same_pr = not incoming.get("pr_url") or incoming["pr_url"] == existing.get("pr_url")
    for key in _WEBHOOK_ATTESTED_RUN_OUTPUT_KEYS:
        merged.pop(key, None)
        if same_pr and existing.get(key):
            merged[key] = existing[key]
    return merged


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


def _get_peer_sender_run(run_id: str | UUID, task_id: str | UUID, team_id: int) -> TaskRun | None:
    return (
        _task_run_queryset()
        .filter(
            pk=run_id,
            team_id=team_id,
            task_id=task_id,
            environment=TaskRun.Environment.CLOUD,
            status=TaskRun.Status.IN_PROGRESS,
            task__runtime=Task.Runtime.PI,
            task__deleted=False,
        )
        .first()
    )


def task_run_exists(run_id: str | UUID, task_id: str | UUID, team_id: int) -> bool:
    """Precheck so callers can 404 before doing expensive work (e.g. a render)."""
    try:
        return TaskRun.objects.filter(pk=run_id, team_id=team_id, task_id=task_id).exists()
    except (ValueError, TypeError, DjangoValidationError):
        return False


def task_run_matches_current_ownership(run_id: str | UUID, task_id: str | UUID, team_id: int) -> bool:
    try:
        run = _task_run_queryset().filter(pk=run_id, team_id=team_id, task_id=task_id).first()
    except (ValueError, TypeError, DjangoValidationError):
        return False
    return run is not None and run.matches_task_ownership()


def _shared_slack_thread_q() -> Q:
    """Slack tasks whose thread is not a direct message.

    Phrased as "not private" rather than "is a channel" so a mapping we never classified — a
    row predating the column, or a lookup Slack refused — keeps the team-wide read access it
    has today instead of silently narrowing to the thread starter.

    The ``origin_product`` test leads so the subquery is only reached for Slack tasks; every
    other task short-circuits on an indexed column before touching the mapping table.
    """
    from products.slack_app.backend.models import (  # noqa: PLC0415 — cross-product import kept off the api import path
        PRIVATE_CONVERSATION_TYPES,
        SlackThreadTaskMapping,
    )

    private_thread = SlackThreadTaskMapping.objects.filter(
        task_id=OuterRef("pk"),
        conversation_type__in=sorted(PRIVATE_CONVERSATION_TYPES),
    )
    return Q(origin_product=Task.OriginProduct.SLACK) & Q(~Exists(private_thread))


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

    Task-bound sandbox callers set ``bypass_visibility`` only after the view verifies that
    the OAuth token's ``sandbox_task_id`` matches this task.

    Tasks from a shared Slack conversation are readable by the whole team. Such a thread is
    multiplayer: every member of the conversation already sees the agent's replies and follows
    the links in them, so gating those links on the one person who opened the thread makes the
    reply unusable for everyone else. The task itself is filed in its creator's personal space,
    so ``task_visibility_q`` alone would hide it. Read-only on purpose — driving the run stays
    with the creator, whose credentials the sandbox runs under.

    Threads from a direct message are excluded: a DM has no audience beyond its author, so
    there is nobody the widened read is for. See ``PRIVATE_CONVERSATION_TYPES``.
    """
    task_filter = Task.objects.filter(id=task_id, team_id=team_id, deleted=False)
    if not bypass_visibility:
        scope_q = task_control_q(user_id) if for_control else task_visibility_q(user_id) | _shared_slack_thread_q()
        task_filter = task_filter.filter(scope_q)
    return task_filter.exists()


def list_task_runs(task_id: str | UUID, team_id: int) -> list[contracts.TaskRunDetailDTO]:
    """All runs for a task, team-scoped. Caller enforces task visibility."""
    runs = _task_run_queryset().filter(team_id=team_id, task_id=task_id)
    return [_task_run_detail_to_dto(run) for run in runs]


def get_task_run_detail(
    run_id: str | UUID, task_id: str | UUID, team_id: int, *, include_agent_state: bool = False
) -> contracts.TaskRunDetailDTO | None:
    """A single run as a detail DTO, scoped to its task + team.

    ``include_agent_state`` is for the run's own task-bound sandbox only: it adds the
    boot-prompt keys that are withheld from human readers.
    """
    run = _get_visible_run(run_id, task_id, team_id)
    return _task_run_detail_to_dto(run, include_agent_state=include_agent_state) if run is not None else None


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


def _is_wizard_pr_ready_email_enabled(run: TaskRun) -> bool:
    user = run.task.created_by
    if user is None or not user.distinct_id:
        return False
    try:
        team = Team.objects.only("id", "uuid", "organization_id").get(id=run.team_id)
        organization_id = str(team.organization_id)
        return bool(
            posthoganalytics.feature_enabled(
                WIZARD_PR_READY_EMAIL_FEATURE_FLAG,
                user.distinct_id,
                groups={"organization": organization_id},
                group_properties={"organization": {"id": organization_id}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.exception("wizard_pr_ready_email_feature_flag_check_failed", extra={"run_id": str(run.id)})
        return False


def _is_github_pull_request_url_for_repository(pr_url: str, repository: str | None) -> bool:
    if not repository:
        return False
    try:
        parsed_url = urlparse(pr_url)
    except ValueError:
        return False

    if parsed_url.scheme != "https" or parsed_url.netloc != "github.com":
        return False
    if parsed_url.params or parsed_url.query or parsed_url.fragment:
        return False

    path_parts = parsed_url.path.strip("/").split("/")
    repository_parts = repository.strip("/").split("/")
    if len(path_parts) != 4 or len(repository_parts) != 2:
        return False

    return (
        path_parts[0].lower() == repository_parts[0].lower()
        and path_parts[1].lower() == repository_parts[1].lower()
        and path_parts[2] == "pull"
        and path_parts[3].isdigit()
    )


def _send_wizard_pr_ready_email_for_pr(run: TaskRun) -> None:
    pr_url = (run.output or {}).get("pr_url") if isinstance(run.output, dict) else None
    if not pr_url or run.task.origin_product != Task.OriginProduct.ONBOARDING:
        return
    if run.task.created_by_id is None:
        return
    if not _is_github_pull_request_url_for_repository(pr_url, run.task.repository):
        logger.warning(
            "wizard_pr_ready_email_invalid_pr_url",
            extra={"run_id": str(run.id), "task_id": str(run.task_id), "repository": run.task.repository},
        )
        return
    if not _is_wizard_pr_ready_email_enabled(run):
        return

    if not run.task.mark_pr_ready_email_queued(pr_url):
        return

    from posthog.tasks.email import send_wizard_pr_ready_email  # noqa: PLC0415 - keep email task import lazy

    transaction.on_commit(lambda: send_wizard_pr_ready_email.delay(str(run.id)))


def _refresh_self_driving_quota_for_pr(run: TaskRun, old_pr_url: str | None) -> None:
    """Queue an org-level self-driving quota re-evaluation when a self-driving-origin run records its first
    PR URL. That write is the report's billable moment (products/signals/backend/billing.py), so
    re-evaluating now lets the quota limiter flag the org within seconds of the PR that crosses
    its limit (for runs created the same UTC day; `refresh_org_self_driving_quota` documents the
    cross-midnight gap); the 15-minute quota cron only re-reads usage on its next tick. Dispatched
    on commit so the task reads the committed pr_url; best-effort because the cron is the backstop.
    Never raises: the callers signal workflow completion and run other PR side effects right after,
    and a refresh hiccup must not abort those or turn an already-committed run write into a 500.
    """
    try:
        if old_pr_url:
            return
        new_pr_url = (run.output or {}).get("pr_url") if isinstance(run.output, dict) else None
        if not new_pr_url or run.task.origin_product != Task.OriginProduct.SIGNAL_REPORT:
            return
        # Billing only ever counts GitHub PR URLs (billing.py validates the same prefix), so a
        # recompute for any other output.pr_url string is a guaranteed no-op; don't let arbitrary
        # client-written values enqueue org-wide refreshes. Literal kept local because tasks code
        # must not import signals internals.
        if not new_pr_url.startswith("https://github.com/"):
            return
        organization_id = Team.objects.filter(id=run.task.team_id).values_list("organization_id", flat=True).first()
        if organization_id is None:
            return
        from ee.tasks.quota_limiting import (
            refresh_org_self_driving_quota_task,  # noqa: PLC0415 — keep billing deps off the api import path
        )

        def _dispatch() -> None:
            try:
                refresh_org_self_driving_quota_task.delay(str(organization_id))
            except Exception:
                logger.warning(
                    "self_driving_quota_refresh_dispatch_failed", extra={"run_id": str(run.id)}, exc_info=True
                )

        transaction.on_commit(_dispatch)
    except Exception:
        logger.warning("self_driving_quota_refresh_failed", extra={"run_id": str(run.id)}, exc_info=True)


def enforce_self_driving_pr_quota(team: Team, *, report_id: str | None = None, stage: str = "manual_create") -> None:
    """Refuse to create a PR-opening self-driving task while the team's org is over its self-driving
    credits quota with enforcement on. The implementation task is the step that leads to the
    billable PR, so the manual create-from-report path must respect the same limit as the pipeline
    auto-start gate (products/signals/backend/auto_start.py). Emits `signal_report_quota_paused`
    at ``stage`` whenever the org is limited, so each caller's gate stays measurable during the
    dark launch like every other gate. Raises ``QuotaLimitExceeded`` (402).
    """
    from posthog.exceptions import QuotaLimitExceeded  # noqa: PLC0415 — keep billing deps off the api import path

    from products.signals.backend.quota import (  # noqa: PLC0415 — cross-product read kept off the api import path
        capture_signal_report_quota_paused,
        self_driving_quota_gate,
    )

    gate = self_driving_quota_gate(team)
    if gate.limited:
        capture_signal_report_quota_paused(team, report_id=report_id, stage=stage, enforced=gate.enforced)
    if gate.enforced:
        raise QuotaLimitExceeded(
            "Your organization reached its self-driving pull request limit. "
            "Increase the limit from the Inbox usage widget, or ask an org admin to do so."
        )


def update_task_run(
    run_id: str | UUID,
    task_id: str | UUID,
    team_id: int,
    *,
    validated_data: dict,
    only_if_non_terminal: bool = False,
    caller_is_agent: bool = False,
) -> contracts.TaskRunDetailDTO | None:
    """Apply a PATCH to a run: merge output/state, set completion, then dispatch side effects.

    Mirrors ``TaskRunViewSet.partial_update`` byte-for-byte: protected state keys are stripped,
    output/state merges take a row lock, terminal transitions signal Temporal + dispatch
    push/Slack updates after commit, and a cloud→local transition cancels the workflow.
    """
    from products.tasks.backend.logic.services.loop_runs import (  # noqa: PLC0415 (keep temporalio off the api import path)
        handle_loop_run_terminal,
    )
    from products.tasks.backend.metrics import (  # noqa: PLC0415 — keep prometheus deps off the api import path
        observe_agent_turn_failed,
        observe_wizard_run_unbound,
    )

    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return None

    validated_data = dict(validated_data)
    if (
        "status" in validated_data
        and not caller_is_agent
        and run.task.origin_product == Task.OriginProduct.TASK_ANALYSIS
    ):
        # A human-driven status write on an analysis run is a way to buy another funded analysis:
        # marking it failed or cancelled frees the per-run idempotency slot. The workflow and the
        # run's own agent write status through paths that do not pass through here.
        validated_data.pop("status")

    has_output_merge = "output" in validated_data and isinstance(validated_data["output"], dict)
    has_state_merge = "state" in validated_data and isinstance(validated_data["state"], dict)
    if has_state_merge:
        validated_data["state"] = {
            k: v for k, v in validated_data["state"].items() if k not in _PROTECTED_RUN_STATE_KEYS
        }
    state_remove_keys = [
        k for k in (validated_data.get("state_remove_keys") or []) if k not in _PROTECTED_RUN_STATE_KEYS
    ]
    raw_state_append = validated_data.get("state_append")
    state_append = (
        {k: v for k, v in raw_state_append.items() if k not in _PROTECTED_RUN_STATE_KEYS}
        if isinstance(raw_state_append, dict)
        else {}
    )
    has_state_mutation = has_state_merge or bool(state_remove_keys) or bool(state_append)
    update_fields: set[str] = set()

    with transaction.atomic():
        if has_output_merge or has_state_mutation or only_if_non_terminal:
            run = TaskRun.objects.select_for_update().get(pk=run.pk)
        if only_if_non_terminal and run.is_terminal:
            return _task_run_detail_to_dto(run)
        old_status = run.status
        old_environment = run.environment
        old_pr_url = (run.output or {}).get("pr_url") if isinstance(run.output, dict) else None
        old_commit_head = _commit_push_head_sha(run.output)

        for key, value in validated_data.items():
            if key == "output" and isinstance(value, dict):
                existing_output = run.output if isinstance(run.output, dict) else {}
                # Same attested-key policy as set_task_run_output — this PATCH surface is
                # caller-controlled too, so it can't be a back door to output.pr_merged.
                merged_output = merge_pr_output(existing_output, value)
                setattr(run, key, _apply_caller_output(existing_output, value, merged_output))
                update_fields.add(key)
                continue
            if key in ("state_remove_keys", "state_append"):
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

        if state_append:
            next_state = dict(run.state) if isinstance(run.state, dict) else {}
            for append_key, item in state_append.items():
                current = next_state.get(append_key)
                if isinstance(current, list):
                    next_state[append_key] = [*current, item]
                elif current is None:
                    next_state[append_key] = [item]
                else:
                    # Appending to a key that holds a scalar used to drop the scalar. Keeping it as
                    # the first element loses nothing, and this path has no way to return a 400.
                    next_state[append_key] = [current, item]
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

    # Only on the actual transition: a repeat PATCH with the same terminal status, or an
    # output-only PATCH on an already-terminal run, must not re-run loop bookkeeping
    # (consecutive_failures would double-count). The workflow's status-update activity
    # applies the same guard on its side.
    if new_status in _TERMINAL_TASK_RUN_STATUSES and old_status != new_status:
        handle_loop_run_terminal(run)

    if new_status in _TERMINAL_TASK_RUN_STATUSES and old_status != new_status:
        if new_status == TaskRun.Status.FAILED:
            observe_agent_turn_failed(run)
            # This PATCH performed the DB transition, so it owns the task_run_failed
            # capture. The workflow's status-update activity sees the row already
            # FAILED and skips its own capture, keeping the event single-emitted.
            run.capture_event(
                "task_run_failed",
                {
                    "error_message": truncate_error_message(run.error_message),
                    "error_type": "agent_reported",
                    "duration_seconds": run._duration_seconds(),
                },
            )
        observe_wizard_run_unbound(run)
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
        _refresh_self_driving_quota_for_pr(run, old_pr_url)
        _post_slack_update_for_pr(run)
        _send_wizard_pr_ready_email_for_pr(run)
        post_pr_created_thread_update(run, new_pr_url)
        # Surface the PR in the run's progress timeline the moment the agent reports it, so the install
        # UI advances past "Started agent" instead of waiting on the 15-min CI follow-up loop to emit
        # these. Steps coalesce by id with the workflow's own pr/ci emissions (frontend mergeProgressStep),
        # so the double-emit is harmless. Tolerant: a logging/stream hiccup must not fail the PATCH.
        try:
            run.emit_progress_event("pr", "completed", "Opened pull request", "setup", detail=new_pr_url)
            run.emit_progress_event("ci", "in_progress", "Keeping CI green", "setup")
        except Exception:
            logger.warning("task_run.pr_progress_emit_failed", extra={"run_id": str(run.id)}, exc_info=True)

    new_commit_head = _commit_push_head_sha(run.output)
    if caller_is_agent and isinstance(run.output, dict) and new_commit_head and new_commit_head != old_commit_head:
        post_commits_pushed_thread_update(run, run.output["commit_push"])

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
    # Preserve PR facts a webhook may have written concurrently: this assignment is wholesale,
    # so a bare `= output` would drop output.pr_url recorded out of band.
    existing = run.output if isinstance(run.output, dict) else {}
    merged = merge_pr_output(existing, output)
    run.output = _apply_caller_output(existing, output, merged)
    run.save(update_fields=["output", "updated_at"])
    _refresh_self_driving_quota_for_pr(run, existing.get("pr_url"))
    if task.json_schema:
        signal_workflow_completion(run.id, TaskRun.Status.COMPLETED, None)
    run.publish_stream_state_event()
    _post_slack_update_for_pr(run)
    _send_wizard_pr_ready_email_for_pr(run)
    if merged.get("pr_url"):
        post_pr_created_thread_update(run, merged["pr_url"])
    return _task_run_detail_to_dto(run)


def _entries_show_agent_activity(entries: list[dict]) -> bool:
    """Classify a log batch as agent activity, but only judge batches that speak ACP.

    Within an ACP batch, only ``session/*`` notifications count as the agent doing work.
    Infra frames (``_posthog/console``, credential-refresh notices, errors) must not reset
    the workflow's inactivity timeout: the workflow's own periodic credential refresh makes
    the sandbox log a line, so counting every frame lets a run whose agent went silent keep
    itself alive forever.

    Batches with no ACP frame at all are not sandbox chatter, they come from callers that
    only ever post generic ``{type, message}`` entries. Those runs have always relied on the
    append itself as their heartbeat, so they keep the old behaviour rather than silently
    losing their inactivity extension.
    """
    saw_acp_frame = False
    for entry in entries:
        notification = entry.get("notification")
        if not isinstance(notification, dict):
            continue
        saw_acp_frame = True
        method = notification.get("method")
        if isinstance(method, str) and method.startswith("session/"):
            return True
    return bool(entries) and not saw_acp_frame


def append_task_run_log(
    run_id: str | UUID, task_id: str | UUID, team_id: int, *, entries: list[dict]
) -> contracts.TaskRunDetailDTO | None:
    """Append log entries to a run's S3 log and heartbeat its workflow.

    The heartbeat only reports the agent as active when the entries show real agent
    activity; sandbox infra frames are still appended but heartbeat with
    ``agent_active=False``, which the workflow's signal handler ignores.
    """
    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return None
    run.append_log(entries)
    run.heartbeat_workflow(agent_active=_entries_show_agent_activity(entries))
    return _task_run_detail_to_dto(run)


def clear_task_run_conversation(
    run_id: str | UUID, task_id: str | UUID, team_id: int
) -> tuple[Literal["cleared", "not_found", "not_terminal"], contracts.TaskRunDetailDTO | None]:
    """Write a `/clear` boundary into a finished run's log, for the next run to resume from.

    Only for a finished run: a live one has a sandbox that owns the clear (and a writer
    streaming into the same log object, which this read-modify-write append would race),
    so the caller sends `/clear` to it as an ordinary message instead.
    """
    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return "not_found", None
    with transaction.atomic():
        # Hold the row lock across the append: resume_task_run_in_cloud locks this same
        # row to flip a finished run back to QUEUED, so locking here keeps the terminal
        # check true while the boundary is written, and serializes concurrent clears so
        # the dedup in emit_conversation_cleared holds. The block writes nothing to
        # Postgres; the lock is mutual exclusion only.
        run = _task_run_queryset().select_for_update(of=("self",)).get(pk=run.pk)
        if not run.is_terminal:
            return "not_terminal", None
        run.emit_conversation_cleared()
    return "cleared", _task_run_detail_to_dto(run)


def ensure_task_run_session(run_id: str | UUID) -> UUID:
    with transaction.atomic():
        run = TaskRun.objects.select_for_update(of=("self",)).select_related("task__team").get(id=run_id)
        if run.active_task_session_id is not None:
            return run.active_task_session_id

        task_session = TaskSession.create_for_task(run.task)
        run.active_task_session = task_session
        run.save(update_fields=["active_task_session", "updated_at"])
        return task_session.id


def get_task_run_session(
    run_id: str | UUID, task_id: str | UUID, team_id: int
) -> tuple[UUID, str | None, str | None] | None:
    from posthog.storage import object_storage  # noqa: PLC0415

    run = _get_visible_run(run_id, task_id, team_id)
    if run is None or run.active_task_session_id is None:
        return None
    task_session = TaskSession.objects.unscoped().get(id=run.active_task_session_id)
    if task_session.object_storage_key is None:
        return task_session.id, None, None
    download_url = object_storage.get_presigned_url(task_session.object_storage_key, expiration=3600)
    if not download_url:
        raise RuntimeError("Unable to prepare task session download")
    return task_session.id, download_url, task_session.content_sha256


def _validate_task_session_content(content: bytes) -> None:
    if not content or len(content) > TASK_SESSION_MAX_SIZE_BYTES:
        raise ValueError("The task session content size is invalid")


def _get_open_sandbox_session(run_id: UUID, sandbox_id: str) -> SandboxSession | None:
    return (
        SandboxSession.objects.unscoped()
        .filter(
            task_run_id=run_id,
            sandbox_id=sandbox_id,
            ended_at__isnull=True,
        )
        .first()
    )


def _delete_task_session_object(task_session_id: UUID, object_storage_key: str) -> None:
    from posthog.storage import object_storage  # noqa: PLC0415

    try:
        object_storage.delete(object_storage_key)
    except Exception as error:
        logger.warning(
            "task_session.failed_to_delete_object",
            extra={
                "task_session_id": str(task_session_id),
                "object_storage_key": object_storage_key,
                "error": str(error),
            },
        )


def validate_task_run_sandbox_token(
    token: str,
    run_id: str | UUID,
    task_id: str | UUID,
    team_id: int,
    sandbox_id: str,
) -> bool:
    from jwt import InvalidTokenError  # noqa: PLC0415

    from products.tasks.backend.logic.services.connection_token import (  # noqa: PLC0415
        validate_sandbox_event_ingest_token,
    )

    try:
        claims = validate_sandbox_event_ingest_token(token)
    except (InvalidTokenError, ValueError):
        return False
    return (
        claims.run_id == str(run_id)
        and claims.task_id == str(task_id)
        and claims.team_id == team_id
        and claims.sandbox_id == sandbox_id
    )


def sync_task_run_session(
    run_id: str | UUID,
    task_id: str | UUID,
    team_id: int,
    *,
    sandbox_id: str,
    expected_content_sha256: str | None,
    content: bytes,
) -> tuple[UUID, str] | None:
    from posthog.storage import object_storage  # noqa: PLC0415

    visible_run = _get_visible_run(run_id, task_id, team_id)
    if visible_run is None or visible_run.active_task_session_id is None:
        return None
    _validate_task_session_content(content)
    if _get_open_sandbox_session(visible_run.id, sandbox_id) is None:
        raise ValueError("The task session writer is not the active sandbox")

    content_sha256 = hashlib.sha256(content).hexdigest()
    object_storage_key = (
        f"task-sessions/{visible_run.task.team.organization_id}/{visible_run.task_id}/"
        f"{visible_run.active_task_session_id}/{uuid4()}.jsonl"
    )
    object_storage.write(object_storage_key, content)

    previous_object_storage_key: str | None = None
    try:
        with transaction.atomic():
            locked_run = TaskRun.objects.select_for_update(of=("self",)).get(id=visible_run.id)
            if locked_run.active_task_session_id != visible_run.active_task_session_id:
                raise ValueError("The task session sync is stale")
            if _get_open_sandbox_session(locked_run.id, sandbox_id) is None:
                raise ValueError("The task session writer is not the active sandbox")

            task_session = TaskSession.objects.unscoped().select_for_update().get(id=locked_run.active_task_session_id)
            if task_session.content_sha256 == content_sha256:
                transaction.on_commit(lambda: _delete_task_session_object(task_session.id, object_storage_key))
                return task_session.id, content_sha256
            if task_session.content_sha256 != expected_content_sha256:
                raise ValueError("The task session content is stale")

            previous_object_storage_key = task_session.object_storage_key
            task_session.object_storage_key = object_storage_key
            task_session.content_sha256 = content_sha256
            task_session.size = len(content)
            task_session.save(update_fields=["object_storage_key", "content_sha256", "size", "updated_at"])
            if previous_object_storage_key is not None:
                transaction.on_commit(lambda: _delete_task_session_object(task_session.id, previous_object_storage_key))
        task_session.tag_object()
        return task_session.id, content_sha256
    except Exception:
        _delete_task_session_object(visible_run.active_task_session_id, object_storage_key)
        raise


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


def _build_artifact_download_path(run: TaskRun, artifact_id: str) -> str:
    return f"/api/projects/{run.team_id}/tasks/{run.task_id}/runs/{run.id}/artifacts/{artifact_id}/download/"


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
    run_id: str | UUID,
    task_id: str | UUID,
    team_id: int,
    *,
    artifacts: list[dict],
    uploaded_by: Literal["agent", "user"] | None = None,
) -> tuple[list[dict], list[dict]] | None:
    """Write artifact bytes to S3 and append them to the run manifest.

    Returns ``(uploaded, manifest)`` — the entries created for ``artifacts`` and the full
    manifest including them, each carrying a ``url`` — or ``None`` when the run isn't visible.

    An artifact may carry an explicit ``id``; entries with that id are upserted into the
    manifest (same-id S3 writes overwrite the same key), so callers that derive ids
    deterministically get idempotent uploads under retries. Without an ``id`` each call
    appends a fresh entry.
    """
    import uuid as uuid_module  # noqa: PLC0415

    from posthog.storage import object_storage  # noqa: PLC0415 — keep storage deps off the api import path

    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return None

    uploaded: list[dict] = []
    for artifact in artifacts:
        artifact_id = str(artifact.get("id") or uuid_module.uuid4().hex)
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
        uploaded_ids = {entry["id"] for entry in uploaded}
        manifest = [entry for entry in (run.artifacts or []) if entry.get("id") not in uploaded_ids]
        manifest.extend(uploaded)
        _save_artifact_manifest(run, manifest)

    if uploaded_by == "agent":
        _announce_agent_artifact_uploads(run, uploaded, manifest)

    # Same download URL the finalize-upload path returns, so a caller that reaches storage
    # through this endpoint instead of a presigned POST still gets a link to surface. Built
    # after the save so it stays off the persisted manifest.
    response_manifest = [
        {**entry, "url": absolute_uri(_build_artifact_download_path(run, entry["id"]))}
        if entry.get("id") and entry.get("storage_path")
        else dict(entry)
        for entry in manifest
    ]

    return uploaded, response_manifest


# Each request is capped by the serializer, but entries accumulate across requests on
# one TaskRun.artifacts JSON value; without a total budget a caller could grow that row
# (and every later read of it) without bound.
MAX_RUN_REFERENCE_ARTIFACTS = 100


def register_task_run_posthog_references(
    run_id: str | UUID,
    task_id: str | UUID,
    team_id: int,
    *,
    references: list[dict[str, Any]],
    caller_is_agent: bool = False,
    acting_user_id: int | None = None,
) -> list[dict[str, Any]] | None:
    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return None

    # Only the task-bound sandbox identity is a verified agent; every other
    # caller is recorded as themselves and posts no agent-authored thread event.
    attribute_as_agent = caller_is_agent

    created: list[dict[str, Any]] = []
    with transaction.atomic():
        run = TaskRun.objects.select_for_update().get(pk=run.pk)
        manifest = [dict(entry) for entry in (run.artifacts or []) if isinstance(entry, dict)]
        by_id = {str(entry.get("id")): entry for entry in manifest if entry.get("id")}
        reference_count = sum(1 for entry in manifest if entry.get("type") == "reference")
        now = django_timezone.now().isoformat()

        for reference in references:
            object_kind = str(reference["object_kind"])
            object_id = str(reference["object_id"])
            source_message_id = str(reference["source_message_id"])
            digest = hashlib.sha256(f"{object_kind}\0{object_id}".encode()).hexdigest()[:24]
            artifact_id = f"phref_{digest}"
            existing = by_id.get(artifact_id)
            if existing is not None:
                metadata = dict(existing.get("metadata") or {})
                source_message_ids = list(metadata.get("source_message_ids") or [])
                if source_message_id in source_message_ids or len(source_message_ids) >= 100:
                    continue
                source_message_ids.append(source_message_id)
                metadata["source_message_ids"] = source_message_ids
                metadata["occurrence_count"] = len(source_message_ids)
                existing["metadata"] = metadata
                continue

            if reference_count >= MAX_RUN_REFERENCE_ARTIFACTS:
                continue
            reference_count += 1
            name = re.sub(r"[\[\]\n]", " ", str(reference["name"])).strip()[:255] or object_id[:255]
            entry = {
                "id": artifact_id,
                "name": name,
                "type": "reference",
                "source": "posthog_object",
                "uploaded_at": now,
                "uploaded_by": "agent" if attribute_as_agent else "user",
                **({} if attribute_as_agent or acting_user_id is None else {"uploaded_by_user_id": acting_user_id}),
                "metadata": {
                    "reference_type": "posthog_object",
                    "object_kind": object_kind,
                    "object_id": object_id,
                    "source_message_ids": [source_message_id],
                    "occurrence_count": 1,
                },
            }
            manifest.append(entry)
            by_id[artifact_id] = entry
            created.append(entry)

        _save_artifact_manifest(run, manifest)

    for entry in created if attribute_as_agent else []:
        reference_metadata = entry.get("metadata")
        if not isinstance(reference_metadata, dict):
            continue
        post_artifact_thread_update(
            run,
            {
                "id": entry["id"],
                "name": entry["name"],
                "artifact_type": entry["type"],
                "reference_type": reference_metadata["reference_type"],
                "object_kind": reference_metadata["object_kind"],
                "current_version": 1,
            },
            revised=False,
        )

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
    run_id: str | UUID,
    task_id: str | UUID,
    team_id: int,
    *,
    artifacts: list[dict],
    uploaded_by: Literal["agent", "user"],
    uploaded_by_user_id: int | None,
) -> tuple[list[dict] | None, str | None]:
    """Verify directly-uploaded S3 objects and attach them to the run manifest.

    ``uploaded_by`` is server-derived and authoritative. ``source`` remains a client-declared organizational hint.

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
    new_entries: list[dict] = []
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
        entry["uploaded_by"] = uploaded_by
        if uploaded_by == "user" and uploaded_by_user_id is not None:
            entry["uploaded_by_user_id"] = uploaded_by_user_id
        manifest.append(entry)
        new_entries.append(entry)
        finalized_entries.append(entry)
        new_storage_paths.append(storage_path)

    if new_entries:
        # Re-read the manifest under the row lock rather than writing back the snapshot taken
        # above: verifying the uploads does S3 I/O, and a dismissal that commits in that window
        # would be silently reverted by a blind whole-array write.
        with transaction.atomic():
            locked_run = TaskRun.objects.select_for_update().get(pk=run.pk)
            new_ids = {entry["id"] for entry in new_entries}
            merged = [entry for entry in (locked_run.artifacts or []) if entry.get("id") not in new_ids]
            merged.extend(new_entries)
            _save_artifact_manifest(locked_run, merged)
        # Count versions from the locked merge, or a concurrent same-named finalize is missed.
        manifest = merged

    for storage_path in new_storage_paths:
        _tag_artifact_object(run, storage_path)

    if uploaded_by == "agent":
        _announce_agent_artifact_uploads(run, new_entries, manifest)

    # Attach a download URL per response entry so the caller (e.g. the upload_artifact
    # tool) can surface a link to the file. The app URL redirects to a fresh presigned
    # URL on each request, so unlike a raw presigned URL it stays short and works for
    # the artifact's full retention window rather than one presign TTL; it is attached
    # to the response only and never written back to the manifest.
    response_entries: list[dict] = []
    for entry in finalized_entries:
        entry_id = entry.get("id")
        response_entries.append(
            {**entry, "url": absolute_uri(_build_artifact_download_path(run, entry_id))} if entry_id else dict(entry)
        )

    return response_entries, None


def list_task_run_living_artifacts(run_id: str | UUID, task_id: str | UUID, team_id: int) -> list[dict] | None:
    from products.tasks.backend.logic.services.living_artifacts import (  # noqa: PLC0415 — keep storage deps off the api import path
        get_task_artifacts_for_run,
        serialize_task_artifact,
    )

    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return None
    return [serialize_task_artifact(artifact) for artifact in get_task_artifacts_for_run(run)]


def get_task_run_living_artifact(
    run_id: str | UUID, task_id: str | UUID, team_id: int, *, artifact_id: str | UUID
) -> dict | None:
    from products.tasks.backend.logic.services.living_artifacts import (  # noqa: PLC0415 — keep storage deps off the api import path
        get_task_artifact_for_run,
        open_task_artifact,
        serialize_task_artifact,
    )

    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return None
    artifact = get_task_artifact_for_run(run, artifact_id)
    if artifact is None:
        return None
    serialized = serialize_task_artifact(artifact)
    serialized["content"] = open_task_artifact(artifact)
    return serialized


def create_task_run_living_artifact(
    run_id: str | UUID,
    task_id: str | UUID,
    team_id: int,
    *,
    artifact: dict,
    caller_is_agent: bool = False,
) -> tuple[dict | None, str | None]:
    from products.tasks.backend.logic.services.living_artifacts import (  # noqa: PLC0415 — keep storage deps off the api import path
        create_living_artifact,
        serialize_task_artifact,
    )

    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return None, None
    try:
        created = create_living_artifact(run=run, **artifact)
    except Exception as exc:
        logger.warning("Failed to create living artifact for task run %s: %s", run.id, exc)
        return None, str(exc)
    serialized = serialize_task_artifact(created)
    if caller_is_agent:
        post_artifact_thread_update(run, serialized, revised=False)
    return serialized, None


def edit_task_run_living_artifact(
    run_id: str | UUID,
    task_id: str | UUID,
    team_id: int,
    *,
    caller_is_agent: bool = False,
    artifact_id: str | UUID,
    content: str | None = None,
    content_bytes: bytes | None = None,
    content_type: str | None = None,
    source_artifact_id: str | None = None,
    source_storage_path: str | None = None,
    name: str | None = None,
    metadata: dict | None = None,
) -> tuple[dict | None, str | None]:
    from products.tasks.backend.logic.services.living_artifacts import (  # noqa: PLC0415 — keep storage deps off the api import path
        edit_living_artifact,
        get_task_artifact_for_run,
        serialize_task_artifact,
    )

    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return None, None
    artifact = get_task_artifact_for_run(run, artifact_id)
    if artifact is None:
        return None, "not_found"
    try:
        updated = edit_living_artifact(
            artifact=artifact,
            run=run,
            content=content,
            content_bytes=content_bytes,
            content_type=content_type,
            source_artifact_id=source_artifact_id,
            source_storage_path=source_storage_path,
            name=name,
            metadata=metadata,
        )
    except Exception as exc:
        logger.warning("Failed to edit living artifact %s for task run %s: %s", artifact_id, run.id, exc)
        return None, str(exc)
    serialized = serialize_task_artifact(updated)
    if caller_is_agent:
        post_artifact_thread_update(run, serialized, revised=True)
    return serialized, None


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


def _without_dismissal(entry: dict) -> dict:
    return {key: value for key, value in entry.items() if key != "dismissed_at"}


def set_task_run_artifacts_dismissed(
    run_id: str | UUID, task_id: str | UUID, team_id: int, *, artifact_ids: list[str], dismissed: bool
) -> tuple[list[dict] | None, str | None]:
    """Mark run artifacts as dismissed, or bring them back.

    Dismissal is a ``dismissed_at`` stamp on the manifest entry rather than a delete: the object
    stays in storage until its TTL expires, so a file dismissed by mistake can be restored.

    Returns ``(manifest, error)``: ``(None, None)`` when the run isn't found, ``(None, "not_found")``
    when an id isn't on the run, else ``(updated_manifest, None)``.
    """
    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return None, None

    with transaction.atomic():
        locked_run = TaskRun.objects.select_for_update().get(pk=run.pk)
        manifest = list(locked_run.artifacts or [])
        requested = set(artifact_ids)
        if not requested.issubset({entry.get("id") for entry in manifest}):
            return None, "not_found"

        # Restoring drops the key rather than nulling it, so a manifest entry only ever carries
        # ``dismissed_at`` while it is dismissed and the response shape stays a plain optional.
        dismissed_at = django_timezone.now().isoformat()
        manifest = [
            (
                ({**entry, "dismissed_at": dismissed_at} if dismissed else _without_dismissal(entry))
                if entry.get("id") in requested
                else entry
            )
            for entry in manifest
        ]
        _save_artifact_manifest(locked_run, manifest)

    return manifest, None


def presign_task_run_artifact_download(
    run_id: str | UUID, task_id: str | UUID, team_id: int, *, artifact_id: str
) -> tuple[str | None, str | None]:
    """Presign a download URL for an artifact addressed by its manifest id.

    Returns ``(url, error)``: ``(None, None)`` if the run isn't found, ``(None, "not_found")`` if
    the artifact isn't on the run, ``(None, "unavailable")`` if presigning fails, else ``(url, None)``.
    """
    from posthog.storage import object_storage  # noqa: PLC0415 — keep storage deps off the api import path

    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return None, None

    entry = next((a for a in run.artifacts or [] if a.get("id") == artifact_id), None)
    # Reference entries carry no file, so there is nothing to download for them.
    if entry is None or not entry.get("storage_path"):
        return None, "not_found"

    filename = str(entry.get("name") or "artifact")
    url = object_storage.get_presigned_url(
        entry["storage_path"],
        content_type=str(entry.get("content_type") or "") or None,
        content_disposition=content_disposition_header(as_attachment=True, filename=filename) or "attachment",
    )
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


def analyze_task_run(run_id: str | UUID, task_id: str | UUID, team_id: int, *, user_id: int) -> tuple[str, bool] | None:
    """Create (or return the existing) PostHog-funded analysis task for a run.

    Returns ``(analysis_task_id, created)``, or ``None`` when the run is not visible.
    Raises ``TaskAnalysisError`` with a caller-safe message when the run cannot be analyzed
    (for example, it has no log yet).
    """
    from products.tasks.backend.logic.services.task_analysis import (  # noqa: PLC0415 — keep storage/temporal deps off the api import path
        create_task_analysis,
    )

    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return None
    task = Task.objects.filter(id=run.task_id, team_id=team_id).first()
    if task is None:
        return None
    analysis_task, created = create_task_analysis(team=task.team, user_id=user_id, target_task=task, target_run=run)
    return str(analysis_task.id), created


def report_task_analysis_insight(run_id: str | UUID, task_id: str | UUID, team_id: int, *, insight: dict) -> int | None:
    """Append one validated analysis finding to a run. Returns its index, or ``None`` if not visible."""
    from products.tasks.backend.logic.services.task_analysis import (  # noqa: PLC0415 — keep storage deps off the api import path
        append_analysis_insight,
    )

    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return None
    return append_analysis_insight(run=run, insight=insight)


def read_task_run_logs(run_id: str | UUID, task_id: str | UUID, team_id: int) -> str | None:
    """Concatenated JSONL logs across the run's resume chain (oldest ancestor first)."""
    from posthog.storage import object_storage  # noqa: PLC0415 — keep storage deps off the api import path

    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return None

    resume_chain = run.get_resume_chain()
    chunks: Iterable[str]
    if len(resume_chain) == 1:
        chunks = [object_storage.read(resume_chain[0].log_url, missing_ok=True) or ""]
    else:
        chunks = _TASK_LOG_READ_EXECUTOR.map(
            lambda ancestor: object_storage.read(ancestor.log_url, missing_ok=True) or "", resume_chain
        )

    parts: list[str] = []
    for chunk in chunks:
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


def task_uses_pi_runtime(task_id: str | UUID, team_id: int) -> bool:
    return Task.objects.filter(id=task_id, team_id=team_id, runtime=Task.Runtime.PI).exists()


def task_is_one_shot_analysis(task_id: str | UUID, team_id: int) -> bool:
    """Whether this task is a server-created analysis, which accepts no further runs.

    Analysis generations are excluded from the customer's credit rollup by their task origin,
    so a second run under the same task would be unbilled model time for any prompt its owner
    sends. The run the server created is the whole task.
    """
    return Task.objects.filter(id=task_id, team_id=team_id, origin_product=Task.OriginProduct.TASK_ANALYSIS).exists()


def task_created_by_user(task_id: str | UUID, team_id: int, user_id: int) -> bool:
    """Whether the task exists on the team and was created by this user. The peers
    endpoints gate on it: peer visibility and attribution derive entirely from the
    task creator, so broader task access must not extend to them."""
    return Task.objects.filter(id=task_id, team_id=team_id, created_by_id=user_id).exists()


def resolve_stream_base_url(*, distinct_id: str, organization_id: str | UUID, force_proxy: bool = False) -> str | None:
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
    if settings.DEBUG or force_proxy:
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
    run_id: str | UUID,
    task_id: str | UUID,
    team_id: int,
    *,
    content: str | None,
    artifact_ids: list[str],
    actor_user_id: int | None = None,
    message_id: str | None = None,
    actor_slack_user_id: str | None = None,
    steer: bool = False,
) -> bool | None:
    """Queue a user_message follow-up signal on the run's workflow.

    Returns ``True`` on success, ``False`` when the target workflow is gone
    (completed or evicted — a terminal outcome), ``None`` when the run isn't
    found. Transient signalling failures propagate so a calling Temporal
    activity retries rather than reporting a dead end to the user.
    """
    from temporalio.service import RPCError, RPCStatusCode  # noqa: PLC0415 — keep temporalio off the api import path

    from products.tasks.backend.temporal.client import (  # noqa: PLC0415 — keep temporalio off the api import path
        signal_task_followup_message,
    )

    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return None
    from products.tasks.backend.exceptions import (
        ComputeBillingLimitError,  # noqa: PLC0415 — keep temporalio off the api import path
    )
    from products.tasks.backend.logic.services.compute_quota import get_compute_quota_denial_reason  # noqa: PLC0415

    if reason := get_compute_quota_denial_reason(run.task):
        raise ComputeBillingLimitError({"team_id": team_id, "task_id": str(task_id), "run_id": str(run_id)}, reason)
    try:
        context = {"actor_slack_user_id": actor_slack_user_id} if actor_slack_user_id else None
        signal_task_followup_message(
            run.workflow_id,
            content,
            artifact_ids,
            message_id,
            actor_user_id,
            context,
            steer=steer,
        )
    except RPCError as e:
        if e.status == RPCStatusCode.NOT_FOUND:
            logger.warning("Follow-up signal target workflow gone for task run %s", run.id)
            return False
        raise
    return True


# --- Agent peer messaging (docs: logic/services/peer_messages.py) ---


def agent_peer_messaging_enabled(team: Team, user: User) -> bool:
    """Whether agent-to-agent peer messaging is enabled for this team/user. v1
    callers additionally require the Pi runtime on the sender task."""
    distinct_id = user.distinct_id or f"user_{user.id}"
    organization_id = str(team.organization_id)
    try:
        return bool(
            posthoganalytics.feature_enabled(
                AGENT_PEER_MESSAGING_FEATURE_FLAG,
                distinct_id,
                groups={"organization": organization_id},
                group_properties={"organization": {"id": organization_id}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.exception("agent peer messaging flag check failed; treating as disabled")
        return False


def list_task_run_peers(run_id: str | UUID, task_id: str | UUID, team_id: int) -> list[contracts.TaskRunPeerDTO] | None:
    """Peer agent runs the given run may message. ``None`` when the sender isn't eligible.

    Discovery and send validation share one visibility policy
    (``peer_messages.visible_peer_runs``), so an agent can only message what it can
    list; the per-entry ``sendable`` flag is the liveness contract — clients never
    infer eligibility from status labels.
    """
    from products.tasks.backend.logic.services import (
        peer_messages,  # noqa: PLC0415 — keep storage deps off the api import path
    )

    run = _get_peer_sender_run(run_id, task_id, team_id)
    if run is None:
        return None
    return [contracts.TaskRunPeerDTO(**entry) for entry in peer_messages.list_peer_run_entries(run)]


def signal_task_run_peer_message(
    run_id: str | UUID,
    task_id: str | UUID,
    team_id: int,
    *,
    target_run_id: str,
    content: str,
    artifact_ids: list[str],
) -> contracts.PeerMessageSendResultDTO | None:
    """Send a peer message from one agent run to another. ``None`` when the sender
    isn't eligible.

    Unlike ``signal_task_run_user_message`` this composes the signal context
    entirely server-side (``kind``/``peer_message_id``/``from_run_id``/``from_task_id``,
    never reserved actor keys, never merged from agent input) and carries no
    ``actor_user_id`` — the delivery activity's peer mode preserves the recipient's
    already-bound credential identity. The synchronous result means ``accepted``,
    never "delivered": the sandbox handoff happens later inside the target workflow,
    which records the delivery outcome on the message row.
    """
    from temporalio.service import RPCError, RPCStatusCode  # noqa: PLC0415 — keep temporalio off the api import path

    from products.tasks.backend.logic.services import (
        peer_messages,  # noqa: PLC0415 — keep storage deps off the api import path
    )
    from products.tasks.backend.models import AgentPeerMessage  # noqa: PLC0415
    from products.tasks.backend.temporal.client import (  # noqa: PLC0415 — keep temporalio off the api import path
        signal_task_followup_message,
    )

    sender_run = _get_peer_sender_run(run_id, task_id, team_id)
    if sender_run is None:
        return None

    prepared = peer_messages.validate_and_prepare_peer_message(sender_run, target_run_id, content, artifact_ids)
    if isinstance(prepared, peer_messages.PeerMessageRejection):
        return contracts.PeerMessageSendResultDTO(result="rejected", detail=prepared.detail)
    message = prepared.message
    target_artifact_ids = prepared.artifact_ids
    target_run = prepared.target_run

    envelope = peer_messages.compose_peer_envelope(sender_run, content)
    context = peer_messages.build_peer_message_context(message)
    # Statuses where the server may have accepted the signal before the client saw
    # the error. Re-signaling with the same message id is safe end-to-end (the
    # sandbox dedupes deliveries by message_id), so these retry inline; if they
    # still fail, the row must NOT terminalize — see the handler below.
    transient_statuses = (
        RPCStatusCode.UNAVAILABLE,
        RPCStatusCode.DEADLINE_EXCEEDED,
        RPCStatusCode.CANCELLED,
    )
    signal_attempts = 3
    try:
        for attempt in range(1, signal_attempts + 1):
            try:
                signal_task_followup_message(
                    target_run.workflow_id,
                    envelope,
                    target_artifact_ids,
                    str(message.id),
                    None,
                    context,
                    steer=False,
                )
                break
            except RPCError as retry_error:
                if retry_error.status in transient_statuses and attempt < signal_attempts:
                    time.sleep(0.2 * attempt)
                    continue
                raise
    except RPCError as e:
        if e.status == RPCStatusCode.NOT_FOUND:
            peer_messages.mark_peer_message_outcome(
                str(message.id),
                AgentPeerMessage.Outcome.TARGET_FINISHED,
                failure_phase="signal",
                failure_detail="target workflow gone",
            )
            return contracts.PeerMessageSendResultDTO(
                result="target_finished",
                detail="The target run has already finished; it can no longer receive messages.",
                message_id=str(message.id),
            )
        if e.status in transient_statuses:
            # At-least-once ambiguity: the signal may have landed, so a terminal
            # outcome here could contradict a later successful delivery. Leave the
            # row non-terminal — delivery marks it delivered if the signal landed,
            # and otherwise it ages out of queue capacity after the delivery window.
            logger.warning(
                "peer message signal hit a transient error; leaving row non-terminal",
                extra={"peer_message_id": str(message.id), "status": str(e.status)},
            )
            return contracts.PeerMessageSendResultDTO(
                result="rejected",
                detail=(
                    "Signaling the target run hit a transient error; the message may still "
                    "be delivered. If it does not arrive, try again in a few minutes."
                ),
                message_id=str(message.id),
            )
        peer_messages.mark_peer_message_outcome(
            str(message.id),
            AgentPeerMessage.Outcome.DELIVERY_FAILED,
            failure_phase="signal",
            failure_detail=str(e),
        )
        return contracts.PeerMessageSendResultDTO(
            result="rejected",
            detail="Signaling the target run failed. Try again shortly.",
            message_id=str(message.id),
        )
    except Exception as e:
        # Terminalize before surfacing: an accepted row left behind would hold the
        # target's queue capacity for the whole delivery window.
        peer_messages.mark_peer_message_outcome(
            str(message.id),
            AgentPeerMessage.Outcome.DELIVERY_FAILED,
            failure_phase="signal",
            failure_detail=str(e),
        )
        return contracts.PeerMessageSendResultDTO(
            result="rejected",
            detail="Signaling the target run failed. Try again shortly.",
            message_id=str(message.id),
        )

    peer_messages.mark_peer_message_signaled(str(message.id))
    return contracts.PeerMessageSendResultDTO(
        result="accepted",
        detail="Message accepted for delivery. It will reach the target as a queued turn; delivery is not confirmed synchronously.",
        message_id=str(message.id),
    )


def apply_task_run_model_config(
    run_id: str | UUID,
    task_id: str | UUID,
    team_id: int,
    *,
    model: str | None = None,
    reasoning_effort: str | None = None,
    actor_user_id: int | None = None,
) -> bool:
    """Switch a live run's model and/or reasoning effort on its agent server.

    The runtime adapter is not switchable — it is the harness process the sandbox was
    started with — so the model has to belong to the adapter the run is already on; the
    agent-server rejects anything else outright. Returns whether every requested change
    landed, and writes the ones that did back to ``state`` so readers of the run agree
    with what the sandbox is actually running.

    Model first, then effort: which efforts exist depends on the model, and the
    agent-server rebuilds its effort options the moment the model changes.
    """
    from products.tasks.backend.logic.services.agent_command import (  # noqa: PLC0415 — keep sandbox deps off the api import path
        send_set_config_option,
    )
    from products.tasks.backend.logic.services.connection_token import (  # noqa: PLC0415 — keep sandbox deps off the api import path
        create_sandbox_connection_token,
    )
    from products.tasks.backend.logic.services.run_actor import (  # noqa: PLC0415 — keep sandbox deps off the api import path
        get_actor_distinct_id,
    )

    # (agent-server option id, value, run-state key), in the order they must be sent.
    requested = [
        (config_id, value, state_key)
        for config_id, value, state_key in (("model", model, "model"), ("effort", reasoning_effort, "reasoning_effort"))
        if value
    ]
    if not requested:
        return False

    run = _get_visible_run(run_id, task_id, team_id)
    if run is None:
        return False

    actor = User.objects.filter(id=actor_user_id).first() if actor_user_id else None
    distinct_id = get_actor_distinct_id(actor) if actor else None
    if model and get_model_access_error(model, distinct_id=distinct_id) is not None:
        # The entitlement check the run-create path applies, so a follow-up can't reach a
        # gated model the caller could not have started the run on.
        logger.warning("Model access denied switching task run %s to %s", run.id, model)
        return False

    auth_token = (
        create_sandbox_connection_token(run, user_id=actor.id, distinct_id=distinct_id)
        if actor and actor.id and distinct_id
        else None
    )

    applied: dict[str, Any] = {}
    for config_id, value, state_key in requested:
        result = send_set_config_option(run, config_id, value, auth_token=auth_token)
        if not result.success:
            logger.warning("Failed to set %s=%s on task run %s: %s", config_id, value, run.id, result.error)
            break
        applied[state_key] = value

    if applied:
        TaskRun.update_state_atomic(run.id, updates=applied)
    return len(applied) == len(requested)


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
    message_id: str | None = None,
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
            signal_agent_text_delta(run.workflow_id, trimmed)
        except Exception:
            logger.exception("task_run_relay_text_signal_failed", extra={"run_id": str(run.id)})
        return "skipped", None

    try:
        relay_id = execute_posthog_code_agent_relay_workflow(
            run_id=str(run.id),
            text=trimmed,
            delete_progress=True,
            message_id=message_id,
        )
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


def user_has_usable_personal_github(user_id: int) -> bool:
    """Whether the user's personal GitHub integration can produce a usable token, ignoring repo access.

    Mirrors the usability checks in `UserGitHubIntegration.get_usable_user_access_token`
    (missing user access token, expired refresh token) without the network refresh or the
    row deletion that path performs, so callers can gate before a run reaches the credential
    path rather than failing partway through it.
    """
    from products.tasks.backend.temporal.process_task.utils import (  # noqa: PLC0415 — keep temporalio off the api import path
        get_user_github_integration,
        user_github_integration_is_usable,
    )

    user = User.objects.filter(id=user_id).first()
    integration = get_user_github_integration(user, allow_refresh=False)
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
    if task.origin_product == Task.OriginProduct.TASK_ANALYSIS:
        return contracts.TaskRunCreateResult(
            error=contracts.TaskRunValidationError(
                kind="detail", detail="An analysis task runs once. Start a new analysis instead."
            )
        )
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
    context_window = validated_data.get("context_window")
    fast_mode = validated_data.get("fast_mode")
    github_user_token = validated_data.get("github_user_token")
    initial_permission_mode = validated_data.get("initial_permission_mode")
    imported_mcp_servers = validated_data.get("imported_mcp_servers")
    relayed_mcp_servers = validated_data.get("relayed_mcp_servers")
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
        "context_window": context_window,
        "fast_mode": fast_mode,
        "rtk_enabled": validated_data.get("rtk_enabled"),
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
    try:
        run = task.create_run(environment=environment, mode=mode, branch=branch, extra_state=extra_state)
    except TaskOwnershipChangedError:
        return None

    if imported_mcp_servers or relayed_mcp_servers:
        update_fields = ["updated_at"]
        if imported_mcp_servers:
            # Kept out of `state` (a plain JSONField) because header values carry credentials.
            run.imported_mcp_servers = imported_mcp_servers
            update_fields.append("imported_mcp_servers")
        if relayed_mcp_servers:
            run.relayed_mcp_servers = relayed_mcp_servers
            update_fields.append("relayed_mcp_servers")
        run.save(update_fields=update_fields)

    if github_user_token and pr_authorship_mode == PrAuthorshipMode.USER:
        cache_github_user_token(str(run.id), github_user_token)

    return contracts.TaskRunCreateResult(run=_task_run_detail_to_dto(_task_run_queryset().get(pk=run.pk)))


def _trigger_task_processing_workflow(
    task: Task,
    run: TaskRun,
    user_id: int | None,
    *,
    initial_message: str | None = None,
    initial_artifact_ids: list[str] | None = None,
    raise_on_error: bool = False,
) -> None:
    from products.tasks.backend.logic.services.workflow_dispatch import (  # noqa: PLC0415
        WorkflowDispatchOptions,
        enqueue_or_start_workflow,
    )
    from products.tasks.backend.temporal.process_task.utils import (  # noqa: PLC0415 — keep temporalio off the api import path
        RunSource,
        parse_run_state,
    )
    from products.tasks.backend.temporal.process_task.workflow import PendingFollowup  # noqa: PLC0415

    # SIGNAL_REPORT: implementation runs log their work on the report (notes, code references)
    # via the task:write artefact tools.
    full_mcp_run_sources = frozenset({None, RunSource.MANUAL, RunSource.SIGNAL_REPORT})
    run_source = parse_run_state(run.state).run_source
    posthog_mcp_scopes: Literal["read_only", "full"] = "full" if run_source in full_mcp_run_sources else "read_only"
    try:
        logger.info("Attempting to trigger task processing workflow for task %s, run %s", task.id, run.id)
        message = None
        if initial_message or initial_artifact_ids:
            message = PendingFollowup(
                message=initial_message,
                artifact_ids=initial_artifact_ids or [],
                actor_user_id=user_id,
                message_id=str(uuid4()),
            )
        enqueue_or_start_workflow(
            run,
            options=WorkflowDispatchOptions(
                user_id=user_id,
                posthog_mcp_scopes=posthog_mcp_scopes,
                initial_message=message,
            ),
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
    if task.runtime != Task.Runtime.PI:
        if pending_user_message is not None:
            state_updates["pending_user_message"] = pending_user_message
        if pending_user_artifact_ids:
            state_updates["pending_user_artifact_ids"] = pending_user_artifact_ids

    previous_state = dict(run.state or {})
    try:
        with transaction.atomic():
            task = Task.objects.select_for_update().get(id=task_id, team_id=team_id)
            run = (
                TaskRun.objects.select_for_update(of=("self",))
                .select_related("task", "task__team", "task__created_by")
                .get(id=run.id, task_id=task.id, team_id=team_id)
            )
            if not run.matches_task_ownership(task):
                return "ownership_changed", None
            if state_updates:
                TaskRun.update_state_atomic(run.id, updates=state_updates)
                run.refresh_from_db()
            logger.info("Triggering workflow for task %s, existing run %s", task.id, run.id)
            _trigger_task_processing_workflow(
                task,
                run,
                user_id,
                initial_message=(pending_user_message or task.description or None)
                if task.runtime == Task.Runtime.PI
                else None,
                initial_artifact_ids=pending_user_artifact_ids if task.runtime == Task.Runtime.PI else None,
                raise_on_error=True,
            )
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
    ``"already_active"`` (400), ``"ownership_changed"`` (400), ``"auth_error:<detail>"``
    (400, GitHub auth), ``"workflow_failed"`` (502), or ``"resumed"`` (run_dto set).
    Mirrors ``TaskRunViewSet.resume_in_cloud``.
    """
    from products.tasks.backend.facade.streams import reset_task_run_stream  # noqa: PLC0415
    from products.tasks.backend.redis import run_uses_dedicated_stream  # noqa: PLC0415
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

    from products.tasks.backend.feature_flags import is_workflow_dispatch_restart_enabled  # noqa: PLC0415
    from products.tasks.backend.logic.services.workflow_dispatch import (  # noqa: PLC0415
        RestartSnapshot,
        build_restart_payload,
        create_dispatch,
    )
    from products.tasks.backend.models import TaskWorkflowDispatch  # noqa: PLC0415

    distinct_id = run.task.created_by.distinct_id if run.task.created_by else str(run.id)
    restart_dispatch_enabled = is_workflow_dispatch_restart_enabled(
        str(run.task.team.organization_id), distinct_id or str(run.id)
    )
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
        task = Task.objects.select_for_update().get(id=task_id, team_id=team_id)
        run = (
            TaskRun.objects.select_for_update(of=("self",))
            .select_related("task", "task__created_by", "task__github_integration", "task__github_user_integration")
            .get(pk=run.pk, task_id=task.id, team_id=team_id)
        )
        if not run.matches_task_ownership(task):
            return "ownership_changed", None, None

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
        prior_queued_at = run.queued_at
        prior_state = dict(run.state or {})
        run.prepare_for_cloud_handoff()

        if restart_dispatch_enabled:
            snapshot = RestartSnapshot(
                status=prior_status,
                environment=prior_environment,
                completed_at=prior_completed_at.isoformat() if prior_completed_at else None,
                queued_at=prior_queued_at.isoformat() if prior_queued_at else None,
                state=prior_state,
            )
            create_dispatch(
                run,
                TaskWorkflowDispatch.Kind.RESTART,
                build_restart_payload(user_id, snapshot),
                run.workflow_id,
            )

    if restart_dispatch_enabled:
        return "resumed", _task_run_detail_to_dto(_task_run_queryset().get(pk=run.pk)), None

    logger.info("Resuming task run in cloud", extra={"task_run_id": str(run.id), "task_id": str(run.task_id)})

    try:
        if not reset_task_run_stream(
            str(run.id),
            use_dedicated=run_uses_dedicated_stream(run.state),
        ):
            raise RuntimeError("Failed to reset task run event stream")
        resume_task_in_cloud_workflow(str(run.id), run.workflow_id)
    except Exception as e:
        logger.exception("Failed to trigger handoff workflow", extra={"task_run_id": str(run.id), "error": str(e)})
        with transaction.atomic():
            run = TaskRun.objects.select_for_update().get(pk=run.pk)
            run.status = prior_status
            run.environment = prior_environment
            run.completed_at = prior_completed_at
            run.queued_at = prior_queued_at
            run.state = prior_state
            run.error_message = "Failed to start cloud workflow"
            run.save(
                update_fields=[
                    "status",
                    "environment",
                    "completed_at",
                    "queued_at",
                    "state",
                    "error_message",
                    "updated_at",
                ]
            )
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


def get_conversation_task_dtos(
    task_ids: Sequence[str | UUID], team_id: int, user_id: int | None
) -> dict[UUID, contracts.TaskDetailDTO]:
    """Visible task payloads for the Max conversation API, keyed by task id.

    ``latest_run`` stays excluded so conversation lists never presign per-row log URLs. A single
    ``latest_run_id`` subquery carries the id that the frontend needs to reconnect to sandbox logs.
    """
    if not task_ids:
        return {}

    latest_run_id_sq = (
        TaskRun.objects.filter(task=OuterRef("pk"), team_id=team_id).order_by("-created_at", "-id").values("id")[:1]
    )
    tasks = (
        Task.objects.filter(team_id=team_id, id__in=task_ids, deleted=False)
        .filter(task_visibility_q(user_id))
        .select_related("created_by", "team")
        .annotate(_latest_run_id=Subquery(latest_run_id_sq))
    )
    return {task.id: _task_detail_to_dto(task, include_latest_run=False) for task in tasks}


def pi_cloud_runtime_enabled(team: Team, user: User) -> bool:
    distinct_id = user.distinct_id or f"user_{user.id}"
    organization_id = str(team.organization_id)
    try:
        return bool(
            posthoganalytics.feature_enabled(
                PI_CLOUD_RUNTIME_FEATURE_FLAG,
                distinct_id,
                groups={"organization": organization_id},
                group_properties={"organization": {"id": organization_id}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.exception("pi-harness flag check failed; treating as disabled")
        return False


def task_analysis_enabled(team: Team, user: User) -> bool:
    """Rollout gate for the PostHog-funded analysis endpoint, fail-closed like the Pi gates."""
    distinct_id = user.distinct_id or f"user_{user.id}"
    organization_id = str(team.organization_id)
    try:
        return bool(
            posthoganalytics.feature_enabled(
                TASK_ANALYSIS_FEATURE_FLAG,
                distinct_id,
                groups={"organization": organization_id},
                group_properties={"organization": {"id": organization_id}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.exception("task-analysis flag check failed; treating as disabled")
        return False


def task_runtime(task_id: str | UUID, team_id: int, user_id: int | None, *, for_control: bool = False) -> str | None:
    return (
        _visible_task_qs(team_id, user_id, for_control=for_control)
        .filter(id=task_id)
        .values_list("runtime", flat=True)
        .first()
    )


def task_visible(task_id: str | UUID, team_id: int, user_id: int | None, *, for_control: bool = False) -> bool:
    """Whether a non-deleted task exists for the team and is visible to the user.

    Mirrors the existence gate ``TaskViewSet.get_object()`` applied (team + ``deleted=False`` +
    ``task_visibility_q``). Used by the ``run`` action to 404 before the usage gate, preserving
    the original ordering; the ``run`` action passes ``for_control`` since starting a run drives
    the task.
    """
    return _visible_task_qs(team_id, user_id, for_control=for_control).filter(id=task_id).exists()


def list_pinned_task_ids(team_id: int, user_id: int) -> list[UUID]:
    visible_tasks = _visible_task_qs(team_id, user_id).values("id")
    return list(
        TaskPin.objects.filter(user_id=user_id, task_id__in=Subquery(visible_tasks))
        .order_by("-pinned_at")
        .values_list("task_id", flat=True)
    )


def set_task_pinned(task_id: str | UUID, team_id: int, user_id: int, *, pinned: bool) -> bool | None:
    if not task_visible(task_id, team_id, user_id):
        return None
    if pinned:
        TaskPin.objects.get_or_create(user_id=user_id, task_id=task_id)
    else:
        TaskPin.objects.filter(user_id=user_id, task_id=task_id).delete()
    return pinned


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


#: Orderings the task list accepts, keyed by the value clients send. Both fall back to `-id` so a
#: page boundary can't drop or repeat a row when two tasks share a timestamp. A null
#: `last_activity_at` (rows written outside the ORM) sorts first under `DESC`, which is where a row
#: with no known activity belongs.
TASK_LIST_ORDERINGS: dict[str, tuple[str, ...]] = {
    "-last_activity_at": ("-last_activity_at", "-id"),
    "-created_at": ("-created_at", "-id"),
}
DEFAULT_TASK_LIST_ORDERING = "-created_at"


def _list_tasks_queryset(
    team_id: int, user_id: int | None, *, filters: dict, bypass_visibility: bool = False
) -> QuerySet[Task]:
    latest_run = TaskRun.objects.filter(task=OuterRef("pk"), team_id=team_id).order_by("-created_at", "-id")
    ordering = TASK_LIST_ORDERINGS.get(filters.get("ordering") or "", TASK_LIST_ORDERINGS[DEFAULT_TASK_LIST_ORDERING])
    qs = _visible_task_qs(team_id, user_id, bypass_visibility=bypass_visibility).order_by(*ordering)

    origin_product = filters.get("origin_product")
    if origin_product:
        qs = qs.filter(origin_product=origin_product)

    exclude_origin_product = filters.get("exclude_origin_product")
    if exclude_origin_product:
        qs = qs.exclude(origin_product=exclude_origin_product)

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

    # PR/CI state filters read the snapshot the PR webhook and the CI follow-up
    # loop persist onto the latest run's output (same latest-run subquery shape
    # as the status filter, so "the task's PR" means what the API's latest_run
    # shows). KeyTextTransform, so the comparison is text = text.
    pr_state = filters.get("pr_state")
    if pr_state:
        latest_run_pr_state = latest_run.annotate(_pr_state=KeyTextTransform("pr_state", "output")).values("_pr_state")[
            :1
        ]
        qs = qs.annotate(_latest_run_pr_state=Subquery(latest_run_pr_state))
        if pr_state == "merged":
            # Runs merged before pr_state existed only carry the older
            # pr_merged flag; honor both spellings.
            latest_run_pr_merged = latest_run.annotate(_pr_merged=KeyTextTransform("pr_merged", "output")).values(
                "_pr_merged"
            )[:1]
            qs = qs.annotate(_latest_run_pr_merged=Subquery(latest_run_pr_merged)).filter(
                Q(_latest_run_pr_state="merged") | Q(_latest_run_pr_merged="true")
            )
        else:
            qs = qs.filter(_latest_run_pr_state=pr_state)

    ci_status = filters.get("ci_status")
    if ci_status:
        latest_run_ci_status = latest_run.annotate(_ci_status=KeyTextTransform("ci_status", "output")).values(
            "_ci_status"
        )[:1]
        qs = qs.annotate(_latest_run_ci_status=Subquery(latest_run_ci_status)).filter(_latest_run_ci_status=ci_status)

    # Pins are per-user, so "pinned" means the requesting user's pins — and
    # without a user (service callers) nothing is pinned.
    if str(filters.get("pinned")).lower() == "true":
        if user_id is None:
            qs = qs.none()
        else:
            qs = qs.filter(Exists(TaskPin.objects.filter(task=OuterRef("pk"), user_id=user_id)))

    commented_by = filters.get("commented_by")
    if commented_by:
        qs = qs.filter(
            Exists(
                TaskThreadMessage.objects.for_team(team_id).filter(
                    task=OuterRef("pk"),
                    author_id=commented_by,
                    author_kind=TaskThreadMessage.AuthorKind.HUMAN,
                )
            )
        )

    mentions = filters.get("mentions")
    if mentions:
        qs = qs.filter(
            Exists(
                TaskThreadMessageMention.objects.for_team(team_id)
                .filter(task=OuterRef("pk"), mentioned_user_id=mentions)
                # Same rule as list_mentions: legacy turn_complete rows are hidden
                # from threads, so their indexed mentions must not match either.
                .exclude(message__event="turn_complete")
            )
        )

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


def search_tasks(
    team_id: int,
    user_id: int | None,
    query: str,
    *,
    limit: int = 20,
    bypass_visibility: bool = False,
) -> list[dict]:
    normalized = query.strip().lower()
    if not normalized:
        return []
    visible_task_ids = (
        _visible_task_qs(team_id, user_id, bypass_visibility=bypass_visibility).filter(internal=False).values("id")
    )
    visibility = Q(task_id__in=Subquery(visible_task_ids)) | (
        Q(task__isnull=True, channel__deleted=False) & Channel.visible_to_q(user_id, relation="channel")
    )
    identifiers = [normalized]
    pr_match = re.match(r"^https?://github\.com/([^/]+/[^/]+)/pull/(\d+)(?:[/?#].*)?$", normalized)
    if pr_match:
        repository, number = pr_match.groups()
        identifiers.extend(
            [f"https://github.com/{repository}/pull/{number}", f"{repository}#{number}", f"#{number}", number]
        )
    exact_match = Q()
    for identifier in identifiers:
        exact_match |= Q(exact_identifiers__contains=[identifier])
    matches = exact_match
    if len(normalized) >= 3:
        matches |= Q(search_text__icontains=normalized)
    documents = (
        TaskSearchDocument.objects.for_team(team_id)
        .filter(visibility)
        .filter(matches)
        .annotate(
            _rank=Case(
                When(exact_match, then=Value(0)),
                When(search_text__startswith=normalized, then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            )
        )
        .order_by("_rank", "-updated_at")[: min(limit, 50)]
    )
    return [
        {
            "id": str(document.id),
            "kind": document.kind,
            "title": document.title,
            "subtitle": document.subtitle,
            "task_id": str(document.task_id) if document.task_id else None,
            "task_run_id": str(document.task_run_id) if document.task_run_id else None,
            "channel_id": str(document.channel_id) if document.channel_id else None,
            "metadata": document.metadata,
        }
        for document in documents
    ]


def inaccessible_repositories_via_integration(team_id: int, integration_id: int, repositories: list[str]) -> list[str]:
    return _inaccessible_repositories_via_integration(team_id, integration_id, repositories)


def list_task_repositories(team_id: int, user_id: int | None) -> list[str]:
    """Distinct repositories used by non-deleted, non-internal visible tasks for the team."""
    tasks = Task.objects.filter(team_id=team_id, deleted=False, internal=False).filter(task_visibility_q(user_id))
    plural = (
        tasks.exclude(repositories=[])
        .annotate(repository_name=Func(F("repositories"), function="unnest", output_field=CharField()))
        .values_list("repository_name", flat=True)
        .distinct()
    )
    legacy = (
        tasks.filter(repositories=[])
        .exclude(repository__isnull=True)
        .exclude(repository="")
        .values_list("repository", flat=True)
        .distinct()
    )
    return sorted(set(plural) | {repository for repository in legacy if repository})


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


def create_task(
    team_id: int,
    user_id: int | None,
    *,
    validated_data: dict,
    client_provenance: TaskClientProvenance | None = None,
) -> contracts.TaskDetailDTO:
    """Create a task, mirroring ``TaskSerializer.create`` byte-for-byte.

    Absorbs the cross-product ``SignalReportTask`` linkage, ``generate_task_title``, and
    ``resolve_user_github_integration_for_task`` so no internal/other-product import leaks into
    presentation. ``validated_data`` carries the validated write fields (integrations already
    resolved to instances by the write serializer's PK fields).
    """
    from posthog.models import Team  # noqa: PLC0415

    from products.signals.backend.task_run_artefacts import (  # noqa: PLC0415 — cross-product write kept off the api import path
        enforce_report_task_cap,
        record_report_task,
    )
    from products.tasks.backend.logic.services.title_generator import generate_task_title  # noqa: PLC0415
    from products.tasks.backend.temporal.process_task.utils import (  # noqa: PLC0415 — keep temporalio off the api import path
        resolve_user_github_integration_for_task,
    )

    team = Team.objects.get(id=team_id)
    validated_data = dict(validated_data)
    validated_data["team"] = team
    validated_data.setdefault("origin_product", Task.OriginProduct.USER_CREATED)
    if (
        validated_data.get("channel") is None
        and user_id is not None
        and not validated_data.get("internal", False)
        and validated_data["origin_product"] not in TEAM_READABLE_ORIGIN_PRODUCTS
    ):
        validated_data["channel"] = _ensure_personal_channel(team_id, user_id)[0]
    validated_data["client_provenance"] = client_provenance
    warm_branch_provided = "branch" in validated_data
    warm_branch = validated_data.pop("branch", None)
    warm_runtime_adapter = validated_data.pop("runtime_adapter", None)
    warm_model = validated_data.pop("model", None)
    warm_reasoning_effort = validated_data.pop("reasoning_effort", None)
    warm_sandbox_environment_id = validated_data.pop("sandbox_environment_id", None)
    warm_custom_image_id = validated_data.pop("custom_image_id", None)
    pending_user_message = (validated_data.pop("pending_user_message", None) or "").strip() or None
    pending_user_artifact_ids = validated_data.pop("pending_user_artifact_ids", None) or []
    warm_auto_publish = validated_data.pop("auto_publish", None)
    # Names the task from the pasted content while `description` stays the bare prompt. Write-only,
    # never persisted, so it must be popped before `Task.objects.create(**validated_data)`.
    naming_source = (validated_data.pop("naming_source", None) or "").strip() or None
    channel = validated_data.get("channel")
    if (
        channel is not None
        and "repositories" not in validated_data
        and "repository" not in validated_data
        # A signal_report task's repo must come from the report (resolved below), never a
        # channel-carried one, or the code-access exemption runs against an attacker-picked repo.
        and validated_data["origin_product"] != Task.OriginProduct.SIGNAL_REPORT
    ):
        validated_data["repositories"] = channel.repositories
        validated_data["github_integration"] = channel.github_integration
    if "repositories" in validated_data:
        repositories = validated_data["repositories"]
        validated_data["repository"] = repositories[0] if repositories else None
    elif "repository" in validated_data:
        validated_data["repositories"] = [validated_data["repository"]] if validated_data["repository"] else []

    if user_id is not None:
        validated_data["created_by"] = User.objects.get(id=user_id)

    if validated_data.get("repository") and not validated_data.get("github_integration"):
        default_integration = Integration.objects.filter(team=team, kind="github").first()
        if default_integration:
            validated_data["github_integration"] = default_integration

    if (
        warm_branch_provided
        and validated_data["origin_product"] == Task.OriginProduct.USER_CREATED
        and user_id is not None
    ):
        warm_run = _find_idling_warm_run(
            team_id,
            user_id,
            repository=validated_data.get("repository"),
            repositories=validated_data.get("repositories", []),
            github_integration_id=getattr(validated_data.get("github_integration"), "id", None),
            branch=warm_branch,
            runtime_adapter=warm_runtime_adapter,
            model=warm_model,
            reasoning_effort=warm_reasoning_effort,
            sandbox_environment_id=warm_sandbox_environment_id,
            custom_image_id=warm_custom_image_id,
        )
        if warm_run is not None and not _warm_sandbox_selection_is_accessible(
            team_id=team_id,
            task_created_by_id=user_id,
            sandbox_environment_id=warm_sandbox_environment_id,
            custom_image_id=warm_custom_image_id,
        ):
            warm_run = None
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
            should_set_client_provenance = warm_task.client_provenance is None and client_provenance is not None
            if should_set_client_provenance:
                warm_task.client_provenance = client_provenance
            from products.tasks.backend.exceptions import (
                ComputeBillingLimitError,  # noqa: PLC0415 — keep temporalio off the api import path
            )
            from products.tasks.backend.logic.services.compute_quota import (  # noqa: PLC0415
                get_compute_quota_denial_reason,
            )

            if reason := get_compute_quota_denial_reason(warm_task):
                raise ComputeBillingLimitError(
                    {"team_id": team_id, "task_id": str(warm_task.id), "run_id": str(warm_run.id)}, reason
                )
            description = (validated_data.get("description") or "").strip()
            update_fields: list[str] = []
            if description and not (warm_task.title or "").strip():
                warm_task.title = generate_task_title(naming_source or description)
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
            if should_set_client_provenance:
                Task.objects.filter(id=warm_task.id, client_provenance__isnull=True).update(
                    client_provenance=client_provenance
                )
            _activate_warm_run(
                warm_run,
                warm_task,
                team_id,
                message=pending_user_message or description or None,
                description=description or None,
                artifact_ids=pending_user_artifact_ids,
                auto_publish=warm_auto_publish,
                reasoning_effort=warm_reasoning_effort,
            )
            return _task_detail_to_dto(_task_detail_queryset().get(pk=warm_task.pk))

    # The relationship the client asserted (validated by the serializer, which rejects `research`).
    # Popped so it isn't forwarded to the model; the link itself is recorded by record_report_task below.
    signal_report_task_relationship = validated_data.pop("signal_report_task_relationship", None)

    # Inbox "Create PR" / "Discuss" don't pre-select a repo, so resolve one here rather than
    # creating a report-linked task that can never open a PR.
    signal_report = validated_data.get("signal_report")
    if (
        signal_report is not None
        and not validated_data.get("repository")
        and validated_data.get("origin_product") == Task.OriginProduct.SIGNAL_REPORT
    ):
        from products.signals.backend.facade.api import (  # noqa: PLC0415 — cross-product read kept off the api import path
            persisted_repo_selection,
        )
        from products.tasks.backend.logic.repo_selection.cascade import (  # noqa: PLC0415 — keeps repo-selection agent imports lazy
            cascade_select_repository,
        )

        # The report's own selection is authoritative — including a scout's deliberate no-repo
        # (`repository=None`), which must not fall through to the cascade.
        selection = persisted_repo_selection(str(signal_report.id))
        resolved_repository = (
            selection.repository
            if selection is not None
            else cascade_select_repository(
                team_id,
                user_id,
                validated_data.get("description") or "",
                team=team,
                single_repo_wins=True,
                allow_refresh=False,
            )
        )
        if resolved_repository:
            validated_data["repository"] = resolved_repository

    if validated_data.get("repository") and not validated_data.get("github_integration"):
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
    if not title and (naming_source or validated_data.get("description")):
        validated_data["title"] = generate_task_title(naming_source or validated_data["description"])
        validated_data.setdefault("title_manually_set", False)
    elif title:
        validated_data.setdefault("title_manually_set", True)

    # The write serializer binds the report as `signal_report` (a PK field); direct callers may
    # pass `signal_report_id`. Either way this is the manual "start work from a report" path.
    # Gated regardless of the relationship label: the label is client-selected and manually
    # created tasks run PR-capable by default, so a "discussion" label must not dodge the limit.
    report_ref = validated_data.get("signal_report") or validated_data.get("signal_report_id")
    signal_report_id = (
        str(getattr(report_ref, "id", report_ref))
        if report_ref and validated_data.get("origin_product") == Task.OriginProduct.SIGNAL_REPORT
        else None
    )
    if signal_report_id:
        enforce_self_driving_pr_quota(team, report_id=signal_report_id)

    logger.info("Creating task with data: %s", validated_data)
    with transaction.atomic():
        if signal_report_id:
            # Locks the report row until commit, so concurrent creates (and auto-start, which
            # takes the same lock) serialize instead of both passing the count check.
            enforce_report_task_cap(
                team_id=team_id,
                report_id=signal_report_id,
                relationship=signal_report_task_relationship,
            )
        task = Task.objects.create(**validated_data)
        if task.signal_report_id and task.origin_product == Task.OriginProduct.SIGNAL_REPORT:
            # Record the task↔report association + work-log artefact for the asserted relationship
            # (defaults to implementation, which also writes the auto-start spend gate row) so a
            # manually-started task matches autostarted ones.
            record_report_task(
                team_id=task.team_id,
                report_id=str(task.signal_report_id),
                task_id=str(task.id),
                relationship=signal_report_task_relationship,
            )

    return _task_detail_to_dto(_task_detail_queryset().get(pk=task.pk))


def set_task_title(task_id: str | UUID, team_id: int, title: str) -> bool:
    """Set a task's title, team-scoped. For automated relabels — e.g. backfilling a Signals research
    task with ``"Research: <report title>"`` once research produces the title. Leaves
    ``title_manually_set`` untouched (this isn't a user edit) and clamps to the column length. Returns
    whether a row was updated.
    """
    task = Task.objects.filter(id=task_id, team_id=team_id).first()
    if task is None:
        return False
    task.title = title[:255]
    task.save(update_fields=["title"])
    return True


def update_task(
    task_id: str | UUID, team_id: int, user_id: int | None, *, validated_data: dict
) -> contracts.TaskDetailDTO | None:
    """Update a task, mirroring ``TaskSerializer.update``. ``None`` if not found/controllable."""
    validated_data = dict(validated_data)
    # origin_product controls visibility and signal_report is set once.
    validated_data.pop("signal_report", None)
    validated_data.pop("signal_report_task_relationship", None)
    validated_data.pop("origin_product", None)
    validated_data.pop("branch", None)

    with transaction.atomic():
        task = Task.objects.select_for_update().filter(id=task_id, team_id=team_id, deleted=False).first()
        if task is None or not Task.objects.filter(id=task.id).filter(task_control_q(user_id)).exists():
            return None

        # Repo is immutable for code-access-exempt tasks; a mutable repo reopens the gate (see task_exempt_from_code_access).
        if task.origin_product in (Task.OriginProduct.SIGNALS_CHAT, Task.OriginProduct.SIGNAL_REPORT):
            validated_data.pop("repository", None)
            validated_data.pop("repositories", None)
            validated_data.pop("github_integration", None)
            validated_data.pop("github_user_integration", None)
        if "repositories" in validated_data:
            repositories = validated_data["repositories"]
            validated_data["repository"] = repositories[0] if repositories else None
        elif "repository" in validated_data:
            if len(task.repositories) <= 1:
                validated_data["repositories"] = [validated_data["repository"]] if validated_data["repository"] else []
            else:
                validated_data.pop("repository")
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
    with transaction.atomic():
        task = Task.objects.select_for_update().filter(id=task_id, team_id=team_id, deleted=False).first()
        if task is None or not Task.objects.filter(id=task.id).filter(task_control_q(user_id)).exists():
            return False
        logger.info("Soft deleting task %s", task.id)
        task.soft_delete()
    return True


# --- Task handoff (transfer ownership to a colleague) ---


class TaskHandoffError(Exception):
    """A handoff request that reads as a client error rather than a missing task."""


def handoff_task(
    task_id: str | UUID, team_id: int, user_id: int | None, *, target_user_id: int
) -> contracts.TaskDetailDTO | None:
    """Hand ``task_id`` off to ``target_user_id``: they become the task's owner.

    Ownership is what `task_control_q` keys on, so the recipient drives the task
    afterwards (steer, archive, forward thread messages), and future runs resolve
    GitHub authorship and notification recipients from them. Membership in the
    project's organization is required — anything weaker would hand control of a
    task to someone who can't see the project.

    Visibility follows the recipient when the task lives in a private space: a
    task in the actor's ``#me`` (or a legacy channel-less task) moves into the
    recipient's ``#me`` so they can open what's now theirs. Public channels stay
    put; both sides keep the shared view.

    Only the owner can hand a task off: ``task_control_q`` also grants control
    over team-owned origin products, and giving a task away is stricter than
    driving it. The recipient must be an org member with access to this project
    (``all_users_with_access`` honors private-project access control), otherwise
    they'd end up owning a task they can't open.

    Returns the updated task detail, or ``None`` when the actor can't control the
    task or no longer owns it. Raises ``TaskHandoffError`` for invalid targets
    (not a member with project access, or the current owner).

    All task runs must be terminal and every sandbox session must be closed
    before a handoff. The transfer rotates a server-owned ownership version and
    revokes task-bound sandbox OAuth tokens, so old runs cannot execute or refresh
    credentials under the recipient's identity.
    """
    task = _visible_task_qs(team_id, user_id, for_control=True).filter(id=task_id).first()
    if task is None:
        return None
    if user_id is None or task.created_by_id != user_id:
        return None
    if task.created_by_id == target_user_id:
        raise TaskHandoffError("That person already owns this task.")
    target = task.team.all_users_with_access().filter(id=target_user_id).first()
    if target is None:
        raise TaskHandoffError("Tasks can only be handed off to someone with access to this project.")

    previous_owner_id = task.created_by_id
    actor = User.objects.filter(id=user_id).only("first_name", "email", "distinct_id").first() if user_id else None
    actor_name = ((actor.first_name.strip() or actor.email) if actor else None) or "Someone"
    target_name = target.first_name.strip() or target.email
    with transaction.atomic():
        locked = Task.objects.select_for_update().get(pk=task.pk)
        # Under the lock: two concurrent handoffs settle last-writer-loses
        # instead of double-announcing and rerouting mid-flight.
        if locked.deleted:
            return None
        if locked.created_by_id != previous_owner_id:
            raise TaskHandoffError("Someone else has already handed this task off. Refresh and try again.")
        if (
            TaskRun.objects.filter(task_id=locked.id, team_id=team_id)
            .exclude(status__in=[TaskRun.Status.COMPLETED, TaskRun.Status.FAILED, TaskRun.Status.CANCELLED])
            .exists()
        ):
            raise TaskHandoffError("Finish or cancel active runs before handing off this task.")
        if (
            SandboxSession.objects.for_team(team_id)
            .filter(
                task_run__task_id=locked.id,
                ended_at__isnull=True,
                ttl_expires_at__gt=django_timezone.now(),
            )
            .exists()
        ):
            raise TaskHandoffError("Wait for active sandboxes to shut down before handing off this task.")

        bound_tokens = OAuthAccessToken.objects.filter(sandbox_task_id=locked.id)
        OAuthRefreshToken.objects.filter(access_token__in=bound_tokens).delete()
        bound_tokens.delete()

        detach_conversations_for_task_handoff(locked.id, target.id)

        channel = locked.channel
        if channel is None or channel.channel_type == Channel.ChannelType.PERSONAL:
            # Never widen: a task in one private space moves to the other private
            # space rather than becoming visible to the whole project, and a legacy
            # channel-less task joins the recipient's #me where they'll find it.
            locked.channel = _ensure_personal_channel(team_id, target.id)[0]
        locked.created_by = target
        # The stored GitHub-user preference names the old owner's installation; the
        # recipient picks their own on their next run. Carrying it across would
        # defer to user-scoped resolution anyway (it keys on created_by), so clear it.
        if locked.github_user_integration_id is not None:
            locked.github_user_integration = None
        # A stamped built-in agent task may borrow its credential owner's MCP Store
        # grants. Handing ownership off while keeping that borrow would hand the old
        # owner's connected accounts to whoever drives the run now, so drop the borrow.
        locked.state = {
            key: value for key, value in (locked.state or {}).items() if key != MCP_CREDENTIAL_OWNER_STATE_KEY
        }
        locked.state[TASK_OWNERSHIP_VERSION_STATE_KEY] = str(uuid4())
        locked.save()
        message = TaskThreadMessage.objects.for_team(team_id).create(
            team_id=team_id,
            task_id=locked.id,
            author_id=user_id,
            author_kind=TaskThreadMessage.AuthorKind.SYSTEM,
            event="task_handed_off",
            payload={
                "from_user_id": previous_owner_id,
                "to_user_id": target.id,
                # Clients render names straight from the payload (ids alone would need a
                # member lookup); both are same-org members, so carrying names is safe.
                "from_display_name": actor_name if user_id is not None else None,
                "to_display_name": target_name,
            },
            content=f"{actor_name} handed this task off to {target_name}",
        )

    try:
        project_thread_message_activity(message)
    except Exception:
        logger.exception("Failed to project handoff thread activity", extra={"task_id": str(task_id)})
    from products.tasks.backend.push_dispatcher import (
        notify_task_handoff,  # noqa: PLC0415 — optional push dep stays off the import path
    )

    notify_task_handoff(locked, recipient=target, actor=actor, message_id=message.id)
    # Task.capture_event would attribute to the new owner (it keys on created_by);
    # the actor initiated the handoff, so capture under their identity instead.
    try:
        posthoganalytics.capture(
            distinct_id=str(actor.distinct_id) if actor is not None and actor.distinct_id else str(locked.team.uuid),
            event="task_handed_off",
            properties={
                "task_id": str(locked.id),
                "team_id": locked.team_id,
                "title": locked.title,
                "origin_product": locked.origin_product,
                "repository": locked.repository,
                "from_user_id": previous_owner_id,
                "to_user_id": target.id,
            },
            groups=groups(team=locked.team),
            send_feature_flags=True,
        )
    except Exception as e:
        logger.warning("task_handed_off capture_event failed for task %s: %s", locked.id, e)

    return _task_detail_to_dto(_task_detail_queryset().get(pk=locked.pk))


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


def can_mint_readonly_github_token(team_id: int) -> bool:
    """Whether a repo-less sandbox requesting `github_read_access` would actually get a token.

    Preflight for callers that condition user-visible behavior (e.g. prompt guidance naming `gh`)
    on the read-only token being obtainable — true only when the team has a usable team-level
    GitHub installation. Never raises.
    """
    from products.tasks.backend.temporal.process_task.utils import (  # noqa: PLC0415 — keeps the temporal stack off the facade import path
        can_mint_readonly_github_token as _can_mint,
    )

    return _can_mint(team_id)


def _find_idling_warm_run(
    team_id: int,
    user_id: int | None,
    *,
    repository: str | None,
    repositories: list[str] | None = None,
    github_integration_id: int | None,
    branch: str | None,
    runtime_adapter: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    sandbox_environment_id: str | UUID | None = None,
    custom_image_id: str | UUID | None = None,
) -> TaskRun | None:
    """Most-recent idling pre-warmed Run matching this user's cloud composing selection, or ``None``.

    A warm Run is a non-terminal ``USER_CREATED`` Run for the same optional repo+branch still awaiting its
    first user message (the ``await_user_message`` state marker). This is the backend's single source
    of truth for the warm pool: it dedupes warm provisioning (so a repeated ``warm`` call reuses the
    live Run instead of spawning a second) and lets the normal create+run path transparently reuse a
    warm Run on submit. Team + user scoped; branch compared as ``None``-normalized exact match.

    Reuse also requires the warm Run's runtime, model, sandbox environment, and custom image selections to
    match the request. Reasoning effort is deliberately excluded: activation applies the final effort before
    the first turn. Other mismatches return ``None`` so the caller cold-creates on the correct sandbox.
    The optional repo/branch/``await_user_message`` predicates stay in the query; the remaining selection is
    matched in Python over the small candidate set.
    """
    if user_id is None:
        return None
    normalized_repositories = [repo.lower() for repo in (repositories or ([repository] if repository else []))]
    repository_filter = {"task__repository__iexact": repository} if repository else {"task__repository__isnull": True}
    candidates = (
        TaskRun.objects.filter(  # nosemgrep: idor-lookup-without-team — team_id filter applied via the task FK below
            task__team_id=team_id,
            task__created_by_id=user_id,
            task__origin_product=Task.OriginProduct.USER_CREATED,
            task__deleted=False,
            task__github_integration_id=github_integration_id,
            state__await_user_message=True,
            branch=branch or None,
            **repository_filter,
        )
        .exclude(status__in=_TERMINAL_TASK_RUN_STATUSES)
        .select_related("task")
        .order_by("-created_at")[:20]
    )
    wanted = (
        runtime_adapter or None,
        model or None,
        str(sandbox_environment_id) if sandbox_environment_id else None,
        str(custom_image_id) if custom_image_id else None,
    )
    for run in candidates:
        state = run.state or {}
        have_repositories = [
            repo.lower() for repo in (run.task.repositories or ([run.task.repository] if run.task.repository else []))
        ]
        if have_repositories != normalized_repositories:
            continue
        have = (
            state.get("runtime_adapter") or None,
            state.get("model") or None,
            state.get("sandbox_environment_id") or None,
            state.get("custom_image_id") or None,
        )
        if have == wanted:
            return run
    return None


def _warm_sandbox_selection_is_accessible(
    *,
    team_id: int,
    task_created_by_id: int | None,
    sandbox_environment_id: str | UUID | None,
    custom_image_id: str | UUID | None,
) -> bool:
    if sandbox_environment_id is not None:
        sandbox_environment = SandboxEnvironment.get_accessible_for_task(
            environment_id=sandbox_environment_id,
            team_id=team_id,
            task_created_by_id=task_created_by_id,
        )
        if sandbox_environment is None:
            return False

    if custom_image_id is not None:
        custom_image = SandboxCustomImage.get_accessible_for_task(
            image_id=custom_image_id,
            team_id=team_id,
            task_created_by_id=task_created_by_id,
        )
        if custom_image is None or not custom_image.is_ready:
            return False

    return True


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
    reasoning_effort: str | None = None,
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
    activation_state_updates: dict[str, object] = {}
    if auto_publish is not None:
        # Before the signal: the agent-server re-reads run state when the forwarded
        # first message arrives, so the choice must already be persisted by then.
        activation_state_updates["auto_publish"] = auto_publish
    if reasoning_effort is not None:
        activation_state_updates["reasoning_effort"] = reasoning_effort
    TaskRun.update_state_atomic(
        run.id,
        updates=activation_state_updates,
        remove_keys=["reasoning_effort"] if reasoning_effort is None else None,
    )
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
    repository: str | None,
    repositories: list[str] | None = None,
    github_integration_id: int | None,
    branch: str | None,
    runtime_adapter: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    sandbox_environment_id: str | UUID | None = None,
    custom_image_id: str | UUID | None = None,
    client_provenance: TaskClientProvenance | None = None,
) -> contracts.WarmTaskDTO | None:
    """Warm a full idling Run for a Code-app cloud task while the user composes.

    Births a draft Task (``USER_CREATED``), then ``SandboxWarmer.warm()`` provisions an interactive
    Run that boots, optionally clones and checks out ``branch``, then starts the agent on the selected
    ``runtime_adapter``/``model``/``reasoning_effort`` (carried on the Run state and read by the
    agent-server at launch, so the sandbox boots on the right runtime), then idles awaiting the first
    ``user_message``. The Run is dispatched with ``create_pr=True`` so that, once activated on submit,
    it completes autonomously and opens a PR like a normal Code-app cloud task.

    Best-effort: returns ``None`` (not an HTTP error) when warming is gated — over quota
    (``QuotaLimitExceeded``), product not enabled (``PermissionDenied``), or the warm pool is full
    (``Throttled``). The caller treats ``None`` as "no warm run; fall through to a cold create+run".

    When present, ``github_integration_id`` must already be re-scoped to ``team_id`` by the caller
    (see :func:`resolve_team_github_integration_id`). Repository-less warms omit it.
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

    team = Team.objects.get(id=team_id)
    normalized_repositories = [repo.lower() for repo in (repositories or ([repository] if repository else []))]
    repository = normalized_repositories[0] if normalized_repositories else None
    github_integration = None
    if github_integration_id is not None:
        github_integration = Integration.objects.filter(
            id=github_integration_id, team_id=team_id, kind="github"
        ).first()
    if bool(normalized_repositories) != bool(github_integration):
        return None
    sandbox_environment = None
    if sandbox_environment_id is not None:
        sandbox_environment = SandboxEnvironment.get_accessible_for_task(
            environment_id=sandbox_environment_id,
            team_id=team_id,
            task_created_by_id=user_id,
        )
        if sandbox_environment is None:
            return None

    custom_image = None
    if custom_image_id is not None:
        custom_image = SandboxCustomImage.get_accessible_for_task(
            image_id=custom_image_id,
            team_id=team_id,
            task_created_by_id=user_id,
        )
        if custom_image is None or not custom_image.is_ready:
            return None

    existing = _find_idling_warm_run(
        team_id,
        user_id,
        repository=repository,
        repositories=normalized_repositories,
        github_integration_id=github_integration_id,
        branch=branch,
        runtime_adapter=runtime_adapter,
        model=model,
        reasoning_effort=reasoning_effort,
        sandbox_environment_id=sandbox_environment_id,
        custom_image_id=custom_image_id,
    )
    if existing is not None:
        return contracts.WarmTaskDTO(task_id=existing.task_id, run_id=existing.id)

    task = Task.create_without_run(
        team=team,
        title="",
        description="",
        origin_product=Task.OriginProduct.USER_CREATED,
        user_id=user_id,
        repository=repository,
        client_provenance=client_provenance,
    )
    task.repositories = normalized_repositories
    task.github_integration = github_integration
    task.save(update_fields=["repositories", "github_integration", "updated_at"])
    assert task.created_by is not None  # create_without_run always sets created_by from user_id

    provider = get_provider_for_runtime_adapter(runtime_adapter)
    initial_permission_mode = "auto" if runtime_adapter == RuntimeAdapter.CODEX.value else "default"
    extra_state: dict = {
        "branch": branch,
        "initial_permission_mode": initial_permission_mode,
    }
    if sandbox_environment is not None:
        extra_state["sandbox_environment_id"] = str(sandbox_environment.id)
    if custom_image is not None:
        extra_state["custom_image_id"] = str(custom_image.id)
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
    from products.signals.backend.task_run_artefacts import (  # noqa: PLC0415 — cross-product read kept off the api import path
        enforce_report_implementation_rerun_cap,
    )
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
    report_id_for_slot_check = (
        str(task.signal_report_id)
        if task.signal_report_id and task.origin_product == Task.OriginProduct.SIGNAL_REPORT
        else None
    )
    if report_id_for_slot_check is not None:
        # Ahead of the warm-run reuse below, which returns early: a task released its slot when
        # its runs all failed, so another implementation may hold it by now. Refusing here also
        # avoids the sandbox and repository lookups a doomed run would otherwise do first. The
        # check that actually holds the slot is the one wrapping `create_run` below.
        with transaction.atomic():
            enforce_report_implementation_rerun_cap(
                team_id=team_id, report_id=report_id_for_slot_check, task_id=str(task.id)
            )
    mode = validated_data.get("mode", "background")
    branch = validated_data.get("branch")
    resume_from_run_id = validated_data.get("resume_from_run_id")
    pending_user_message = validated_data.get("pending_user_message")
    pending_user_artifact_ids = validated_data.get("pending_user_artifact_ids") or []
    is_pi_task = task.runtime == Task.Runtime.PI

    if branch is None and not resume_from_run_id and task.origin_product == Task.OriginProduct.SIGNAL_REPORT:
        # The inbox "Create PR" button sends no branch, so without this the run would target the
        # repository's GitHub default branch. Auto-start resolves the same setting when it builds
        # its task. This sits before the warm-run reuse check below, so that a sandbox idling on
        # the default branch is not reused for a run that needs the configured branch.
        from products.signals.backend.facade.api import (  # noqa: PLC0415 — cross-product read kept off the api import path
            autostart_base_branch_for_repository,
        )

        branch = autostart_base_branch_for_repository(
            team_id, task.repositories[0] if task.repositories else task.repository
        )

    if not resume_from_run_id:
        warm_run = _idling_warm_run_for_task(task)
        if warm_run is not None and (branch or None) == (warm_run.branch or None):
            warm_state = warm_run.state or {}
            warm_runtime_matches = (
                warm_state.get("runtime_adapter") or None,
                warm_state.get("model") or None,
                warm_state.get("context_window") or None,
                warm_state.get("fast_mode") or None,
                warm_state.get("sandbox_environment_id") or None,
                warm_state.get("custom_image_id") or None,
            ) == (
                validated_data.get("runtime_adapter") or None,
                validated_data.get("model") or None,
                validated_data.get("context_window") or None,
                validated_data.get("fast_mode") or None,
                str(validated_data["sandbox_environment_id"]) if validated_data.get("sandbox_environment_id") else None,
                str(validated_data["custom_image_id"]) if validated_data.get("custom_image_id") else None,
            )
            if warm_runtime_matches and _warm_sandbox_selection_is_accessible(
                team_id=team_id,
                task_created_by_id=task.created_by_id,
                sandbox_environment_id=warm_state.get("sandbox_environment_id"),
                custom_image_id=warm_state.get("custom_image_id"),
            ):
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
                        reasoning_effort=validated_data.get("reasoning_effort"),
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
    context_window = validated_data.get("context_window")
    fast_mode = validated_data.get("fast_mode")
    github_user_token = validated_data.get("github_user_token")
    initial_permission_mode = validated_data.get("initial_permission_mode")
    imported_mcp_servers = validated_data.get("imported_mcp_servers")
    relayed_mcp_servers = validated_data.get("relayed_mcp_servers")
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
        "context_window": context_window,
        "fast_mode": fast_mode,
    }

    extra_state: dict | None = None
    if pending_user_message is not None and not is_pi_task:
        extra_state = {"pending_user_message": pending_user_message}
    if pending_user_artifact_ids and not is_pi_task:
        extra_state = extra_state or {}
        extra_state["pending_user_artifact_ids"] = pending_user_artifact_ids
    if initial_permission_mode is not None:
        extra_state = extra_state or {}
        extra_state["initial_permission_mode"] = initial_permission_mode
    rtk_enabled = validated_data.get("rtk_enabled")
    if rtk_enabled is not None:
        extra_state = extra_state or {}
        extra_state["rtk_enabled"] = rtk_enabled

    if resume_from_run_id:
        previous_run = task.runs.filter(id=resume_from_run_id).first()
        if not previous_run:
            return contracts.TaskRunResult(
                error=contracts.TaskValidationError(kind="detail", detail="Invalid resume_from_run_id")
            )
        if not previous_run.matches_task_ownership(task):
            return contracts.TaskRunResult(
                error=contracts.TaskValidationError(
                    kind="detail",
                    detail="This run belongs to a previous task owner. Start a new run instead.",
                )
            )

        prev_state = parse_run_state(previous_run.state)
        extra_state = extra_state or {}
        if not is_pi_task:
            extra_state["resume_from_run_id"] = str(resume_from_run_id)
            extra_state.update(prev_state.resume_snapshot_carry_state())

        # The resumed agent still pushes the head branch baked into the original prompt, so the
        # PR webhook must be able to match this run, not the terminal predecessor.
        prev_wizard_head_branch = (previous_run.state or {}).get("wizard_head_branch")
        if prev_wizard_head_branch:
            extra_state["wizard_head_branch"] = prev_wizard_head_branch

        # Same reasoning for a signals self-driving run: the head branch is baked into the original
        # prompt, so the resumed run pushes it too, and the review carve-out's branch linkage
        # (find_signal_implementation_run) only matches the successor if its stamp is carried
        # forward — otherwise a resume (the usual recovery for a cancelled run) silently ends
        # re-reviews. The key is PATCH-protected, so this server-side copy is the only way it
        # reaches the successor run.
        prev_self_driving_head_branch = (previous_run.state or {}).get("self_driving_head_branch")
        if prev_self_driving_head_branch:
            extra_state["self_driving_head_branch"] = prev_self_driving_head_branch

        # A read-only GitHub grant describes how the task was created, not one run — without the
        # carry-forward, a resumed successor of a repo-less read-only run falls through to the
        # full credential path and regains the write-capable token. (The key is PATCH-protected,
        # so this server-side copy is the only way it reaches a successor run.)
        if (previous_run.state or {}).get("github_read_access") is True:
            extra_state["github_read_access"] = True

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
        context_window = runtime_state_fields["context_window"]
        fast_mode = runtime_state_fields["fast_mode"]
        if branch is None and prev_state.pr_base_branch is not None:
            branch = prev_state.pr_base_branch

    provider = get_provider_for_runtime_adapter(runtime_adapter)

    run_state_values = {
        "pr_base_branch": branch,
        "pr_authorship_mode": pr_authorship_mode,
        "auto_publish": auto_publish,
        "run_source": run_source,
        "signal_report_id": signal_report_id,
        "runtime_adapter": runtime_adapter,
        "provider": provider,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "context_window": context_window,
        "fast_mode": fast_mode,
    }
    if is_pi_task:
        for key in ("runtime_adapter", "provider", "model", "reasoning_effort"):
            run_state_values.pop(key)
    for key, value in run_state_values.items():
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

    # A resume inherits the previous run's model, so the serializer's check saw `None` and
    # passed. Re-check the model that will actually run. Only a gated model pays the lookup.
    if get_required_model_flag(model) is not None:
        actor_distinct_id = (
            User.objects.filter(pk=user_id).values_list("distinct_id", flat=True).first() if user_id else None
        )
        model_access_error = get_model_access_error(model, distinct_id=actor_distinct_id)
        if model_access_error is not None:
            return contracts.TaskRunResult(
                error=contracts.TaskValidationError(
                    kind="validation_error", code="invalid_input", detail=model_access_error, attr="model"
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
    try:
        with transaction.atomic():
            task_run = task.create_run(mode=mode, branch=branch, extra_state=extra_state)
            if report_id_for_slot_check is not None:
                enforce_report_implementation_rerun_cap(
                    team_id=team_id, report_id=report_id_for_slot_check, task_id=str(task.id)
                )
    except TaskOwnershipChangedError:
        return None
    if is_pi_task and resume_from_run_id:
        task_run.active_task_session = previous_run.active_task_session
        task_run.save(update_fields=["active_task_session", "updated_at"])

    if imported_mcp_servers or relayed_mcp_servers:
        update_fields = ["updated_at"]
        if imported_mcp_servers:
            # Kept out of `state` (a plain JSONField) because header values carry credentials.
            task_run.imported_mcp_servers = imported_mcp_servers
            update_fields.append("imported_mcp_servers")
        if relayed_mcp_servers:
            task_run.relayed_mcp_servers = relayed_mcp_servers
            update_fields.append("relayed_mcp_servers")
        task_run.save(update_fields=update_fields)

    if pending_user_artifact_ids:
        _attach_staged_artifacts_to_run(
            task_run, task, staged_artifacts=staged_artifacts, artifact_ids=pending_user_artifact_ids
        )

    if github_user_token and pr_authorship_mode == PrAuthorshipMode.USER:
        cache_github_user_token(str(task_run.id), github_user_token)

    logger.info("Triggering workflow for task %s, run %s", task.id, task_run.id)
    if is_pi_task:
        initial_message = (
            pending_user_message if resume_from_run_id else pending_user_message or task.description or None
        )
        _trigger_task_processing_workflow(
            task,
            task_run,
            user_id,
            initial_message=initial_message,
            initial_artifact_ids=pending_user_artifact_ids,
            raise_on_error=False,
        )
    else:
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
    # Prefer the run's actual id (prefixed dispatches persist it); fall back to derived when the row is gone.
    workflow_id = (
        research_run.workflow_id
        if research_run is not None
        else TaskRun.get_workflow_id(research_task_id, research_run_id)
    )
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
    team_id: int, user_id: int | None, *, channel: str, thread_ts: str, url: str, build_url
) -> contracts.SlackThreadContextResult:
    """Resolve a parsed Slack permalink to its task, runs, and Temporal workflow handles.

    Caller passes the already-parsed ``(channel, thread_ts)`` and a ``build_url`` callable
    (``request.build_absolute_uri``) so the facade stays request-agnostic. The mapping is filtered
    through the backing task's visibility after the caller enforces the internal-debug gate.
    """
    from posthog.storage import object_storage  # noqa: PLC0415

    from products.slack_app.backend.models import (  # noqa: PLC0415 — cross-product import kept off the api import path
        SlackThreadTaskMapping,
    )

    mapping = (
        SlackThreadTaskMapping.objects.select_related("task", "task__created_by")
        .filter(channel=channel, thread_ts=thread_ts, team_id=team_id, task__deleted=False)
        .filter(task_run_visibility_q(user_id))
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
        task_processing_workflow_id = run.workflow_id
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


def send_cancel(run_id: str | UUID, *, auth_token: str | None = None):
    """Cancel the agent running in a run's live sandbox."""
    from products.tasks.backend.logic.services.agent_command import (  # noqa: PLC0415 — keep sandbox deps off the api import path
        send_cancel as _send_cancel,
    )

    run = TaskRun.objects.select_related("task").get(id=run_id)
    return _send_cancel(run, auth_token=auth_token)


# --- Channels & task threads ---


_CHANNEL_NAME_SEPARATORS = re.compile(r"[^a-z0-9]+")


def normalize_channel_name(name: str) -> str:
    """Slack-style channel key: lowercase letters, digits and dashes, with every run of
    anything else becoming a single dash. Must stay in step with ``normalizeChannelName``
    in ``channelName.ts``, or a name is stored in a shape the field cannot produce.

    Returns "" for a name with nothing usable in it, which callers reject.
    """
    return _CHANNEL_NAME_SEPARATORS.sub("-", name.strip().lower()).strip("-")[:128].strip("-")


PERSONAL_SPACE_NAMES = frozenset({Channel.PERSONAL_CHANNEL_NAME, Channel.PERSONAL_CHANNEL_LABEL})
RESERVED_CHANNEL_NAMES = PERSONAL_SPACE_NAMES | {Channel.GENERAL_CHANNEL_NAME}


def is_personal_space_name(name: str) -> bool:
    """Reads as somebody's private space. Surfaces holding a bare name decide the lock and
    the label from it, so a shared space under one of these presents itself as private."""
    return normalize_channel_name(name) in PERSONAL_SPACE_NAMES


def is_reserved_channel_name(name: str) -> bool:
    """Reads as one of the system spaces. Renaming a space to the general name would also
    make it permanently unrenameable, since the guards fall back to the name."""
    return normalize_channel_name(name) in RESERVED_CHANNEL_NAMES


def _set_channel_star(channel_id: UUID, team_id: int, user_id: int, *, starred: bool) -> None:
    if starred:
        ChannelStar.objects.get_or_create(channel_id=channel_id, user_id=user_id, defaults={"team_id": team_id})
    else:
        ChannelStar.objects.filter(channel_id=channel_id, user_id=user_id).delete()


def _is_channel_starred(channel_id: UUID, user_id: int) -> bool:
    return ChannelStar.objects.filter(channel_id=channel_id, user_id=user_id).exists()


def _channel_to_dto(channel: Channel, *, starred: bool = False) -> contracts.ChannelDTO:
    return contracts.ChannelDTO(
        id=channel.id,
        name=channel.name,
        channel_type=channel.channel_type,
        system_role=channel.system_role,
        github_integration=channel.github_integration_id,
        repositories=channel.repositories,
        created_at=channel.created_at,
        created_by=_user_basic_info(channel.created_by if channel.created_by_id else None),
        starred=starred,
    )


def _team_channels(team_id: int) -> QuerySet[Channel]:
    # for_team rather than a bare team_id filter so these reads also resolve outside request
    # scope (Temporal activities), where the fail-closed manager raises on an unscoped read.
    return Channel.objects.for_team(team_id)


def _ensure_system_channel(
    team_id: int,
    user_id: int | None,
    *,
    role: str,
    owner_lookup: dict[str, Any],
    legacy_lookup: dict[str, Any],
    create_defaults: dict[str, Any],
) -> tuple[Channel, bool]:
    """``legacy_lookup`` must be covered by a unique constraint; that is what makes the
    IntegrityError fallback safe under concurrent provisioning calls."""
    created = False
    channels = _team_channels(team_id).select_related("created_by")
    channel = channels.filter(system_role=role, deleted=False, **owner_lookup).first()
    if channel is None:
        channel = channels.filter(**legacy_lookup).first()
    if channel is None:
        try:
            channel, created = channels.get_or_create(
                team_id=team_id, **legacy_lookup, defaults={**create_defaults, "system_role": role}
            )
        except IntegrityError:
            channel, created = channels.get(team_id=team_id, **legacy_lookup), False
        if created and channel.channel_type == Channel.ChannelType.PUBLIC:
            _emit_channel_created(channel, user_id)
    if channel.system_role != role:
        channel.system_role = role
        channel.save(update_fields=["system_role"])
    return channel, created


PERSONAL_LEGACY_SHAPE: dict[str, Any] = {"channel_type": Channel.ChannelType.PERSONAL}
GENERAL_LEGACY_SHAPE: dict[str, Any] = {
    "channel_type": Channel.ChannelType.PUBLIC,
    "name": Channel.GENERAL_CHANNEL_NAME,
}


def _ensure_personal_channel(team_id: int, user_id: int) -> tuple[Channel, bool]:
    return _ensure_system_channel(
        team_id,
        user_id,
        role=Channel.SystemRole.PERSONAL,
        owner_lookup={"created_by_id": user_id},
        legacy_lookup={"created_by_id": user_id, **PERSONAL_LEGACY_SHAPE, "deleted": False},
        create_defaults={"name": Channel.PERSONAL_CHANNEL_NAME},
    )


def ensure_personal_channel_id(team_id: int, user_id: int) -> UUID:
    """Get-or-create the user's personal "#me" channel and return its id.

    For callers outside a request (Temporal activities) that need somewhere to file a task.
    """
    return _ensure_personal_channel(team_id, user_id)[0].id


def _ensure_general_channel(team_id: int, user_id: int | None) -> tuple[Channel, bool]:
    return _ensure_system_channel(
        team_id,
        user_id,
        role=Channel.SystemRole.GENERAL,
        owner_lookup={},
        legacy_lookup={**GENERAL_LEGACY_SHAPE, "deleted": False},
        create_defaults={"created_by_id": user_id},
    )


def _matches_legacy_shape(channel: Channel, legacy: dict[str, Any]) -> bool:
    return all(getattr(channel, key) == value for key, value in legacy.items())


def general_channel_q(prefix: str = "") -> Q:
    if prefix == "channel":
        return Q(channel__system_role=Channel.SystemRole.GENERAL) | Q(
            channel__system_role__isnull=True,
            channel__channel_type=Channel.ChannelType.PUBLIC,
            channel__name=Channel.GENERAL_CHANNEL_NAME,
        )
    if prefix:
        raise ValueError(f"Unsupported channel relation: {prefix}")
    return Q(system_role=Channel.SystemRole.GENERAL) | Q(
        system_role__isnull=True,
        channel_type=Channel.ChannelType.PUBLIC,
        name=Channel.GENERAL_CHANNEL_NAME,
    )


def personal_channel_q(prefix: str = "") -> Q:
    if prefix == "channel":
        return Q(channel__system_role=Channel.SystemRole.PERSONAL) | Q(
            channel__system_role__isnull=True,
            channel__channel_type=Channel.ChannelType.PERSONAL,
        )
    if prefix:
        raise ValueError(f"Unsupported channel relation: {prefix}")
    return Q(system_role=Channel.SystemRole.PERSONAL) | Q(
        system_role__isnull=True,
        channel_type=Channel.ChannelType.PERSONAL,
    )


def find_general_channel_id(team_id: int) -> UUID | None:
    """The team's general space, or ``None`` when nobody has provisioned one. Read-only, so
    a product filing work into that space can gate on its existence instead of bringing the
    team's default spaces into being as a side effect."""
    channel = (
        _team_channels(team_id)
        .filter(general_channel_q(), deleted=False)
        # A stamped row wins over an unstamped one, in the vanishingly rare case a team has both.
        .order_by(F("system_role").asc(nulls_last=True))
        .first()
    )
    return channel.id if channel is not None else None


def _is_general_channel(channel: Channel) -> bool:
    """Must match ``isGeneralChannel`` in ``channelName.ts``: a row with no role but the
    general name is still the team's general space."""
    if channel.system_role is not None:
        return channel.system_role == Channel.SystemRole.GENERAL
    return _matches_legacy_shape(channel, GENERAL_LEGACY_SHAPE)


def provision_default_channels(team_id: int, user_id: int) -> contracts.ProvisionedChannelsDTO:
    """The created flags let a client distinguish "this call provisioned the space"
    (first user in the team) from inheriting one that already existed."""
    _, personal_created = _ensure_personal_channel(team_id, user_id)
    _, general_created = _ensure_general_channel(team_id, user_id)
    return contracts.ProvisionedChannelsDTO(
        channels=list_channels(team_id, user_id),
        personal_created=personal_created,
        general_created=general_created,
    )


def list_channels(team_id: int, user_id: int | None) -> list[contracts.ChannelDTO]:
    """Every space the requester can see, by name. ``starred`` reflects the requester's
    stars. Creates nothing, which is what lets a caller gate on a space existing."""
    channels = list(
        _team_channels(team_id).select_related("created_by").filter(Channel.visible_to_q(user_id)).order_by("name")
    )
    starred_ids: set = (
        set(ChannelStar.objects.filter(team_id=team_id, user_id=user_id).values_list("channel_id", flat=True))
        if user_id is not None
        else set()
    )
    return [_channel_to_dto(channel, starred=channel.id in starred_ids) for channel in channels]


def _emit_channel_created(channel: Channel, user_id: int | None) -> None:
    """Announce a newly-created public channel in its own feed as a system row
    ("Ann created this context"). Server-emitted so the announcement appears no
    matter which client (or integration) created the channel. Best-effort — a
    feed-write failure must never break channel creation. The fail-closed
    ``TeamScopedManager`` raises without team context, so callers outside a
    request (temporal, MCP) must wrap in ``team_scope()`` or the announcement
    is swallowed here and only logged."""
    try:
        ChannelFeedMessage.objects.create(
            team_id=channel.team_id,
            channel_id=channel.id,
            author_id=user_id,
            author_kind=ChannelFeedMessage.AuthorKind.SYSTEM,
            event="channel_created",
            payload={"channel_name": channel.name},
        )
    except Exception:
        logger.exception("Failed to emit channel_created feed message", extra={"channel_id": str(channel.id)})


def resolve_channel(team_id: int, user_id: int | None, *, name: str, star: bool) -> contracts.ChannelDTO | None:
    """Resolve-or-create a public channel by (normalized) name. ``None`` for empty names.
    The general name resolves the team's general space, which cannot then be renamed away.
    Emits a ``channel_created`` feed message the first time a channel is created, and (unless
    ``star`` is false) stars the channel for whoever created it. Resolving a channel that
    already exists leaves the requester's star alone — only creation stars."""
    normalized = normalize_channel_name(name)
    if not normalized:
        return None
    if normalized == Channel.GENERAL_CHANNEL_NAME:
        # Resolving by name here would produce a second, unstamped general space, so
        # every path that can create one goes through the role-aware helper.
        channel, created = _ensure_general_channel(team_id, user_id)
    else:
        created = False
        try:
            channel, created = Channel.objects.select_related("created_by").get_or_create(
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
        if created:
            _emit_channel_created(channel, user_id)
    if user_id is None:
        starred = False
    elif not created:
        starred = _is_channel_starred(channel.id, user_id)
    else:
        starred = star
        if star:
            _set_channel_star(channel.id, team_id, user_id, starred=True)
    return _channel_to_dto(channel, starred=starred)


def update_channel(
    channel_id: str | UUID,
    team_id: int,
    user_id: int | None,
    *,
    name: str | None = None,
    github_integration: Integration | None = None,
    repositories: list[str] | None = None,
) -> contracts.ChannelDTO | str:
    """Update a visible channel."""
    channel = Channel.objects.filter(id=channel_id, team_id=team_id, deleted=False).first()
    if channel is None:
        return "not_found"
    if channel.channel_type == Channel.ChannelType.PERSONAL:
        if channel.created_by_id != user_id:
            return "not_found"
        if name is not None:
            return "personal"
    if name is not None and _is_general_channel(channel):
        return "general"
    update_fields: list[str] = []
    if name is not None:
        normalized = normalize_channel_name(name)
        if not normalized:
            return "invalid_name"
        channel.name = normalized
        update_fields.append("name")
    if repositories is not None:
        channel.repositories = repositories
        channel.github_integration = github_integration if repositories else None
        update_fields.extend(["repositories", "github_integration"])
    if not update_fields:
        return _channel_to_dto(channel)
    try:
        channel.save(update_fields=[*update_fields, "updated_at"])
    except IntegrityError:
        return "name_taken"
    return _channel_to_dto(channel)


def delete_channel(channel_id: str | UUID, team_id: int, user_id: int | None) -> str:
    """Soft-delete an empty public channel. Archived tasks do not count as content."""
    channel = Channel.objects.filter(id=channel_id, team_id=team_id, deleted=False).first()
    if channel is None:
        return "not_found"
    if channel.channel_type == Channel.ChannelType.PERSONAL:
        return "personal" if channel.created_by_id == user_id else "not_found"
    if _is_general_channel(channel):
        return "general"
    with transaction.atomic():
        # Emptiness is checked under a row lock because filing a task takes FOR KEY SHARE on
        # its channel: unlocked, a task can land after the check and be orphaned in a channel
        # this call goes on to delete.
        channel = Channel.objects.select_for_update().filter(id=channel_id, team_id=team_id, deleted=False).first()
        if channel is None:
            return "not_found"
        if (
            channel.tasks.filter(deleted=False, archived=False).exists()
            or channel.canvases.filter(deleted=False).exists()
        ):
            return "not_empty"
        # Not filtered on `archived`: flipping that flag leaves the FK untouched, so it takes
        # no lock on the channel and can happen after the check above. Task visibility joins
        # through the channel, so a task left pointing at a deleted one leaves every list.
        channel.tasks.filter(deleted=False).update(channel=None)
        channel.deleted = True
        channel.save(update_fields=["deleted", "updated_at"])
    return "ok"


# Per-channel ceiling on feed rows — the feed holds rare lifecycle announcements, so the
# cap exists to stop one member making the feed unboundedly expensive to store and read.
CHANNEL_FEED_MAX_MESSAGES = 500


def _channel_feed_message_to_dto(message: ChannelFeedMessage) -> contracts.ChannelFeedMessageDTO:
    return contracts.ChannelFeedMessageDTO(
        id=message.id,
        channel=message.channel_id,
        author_kind=message.author_kind,
        event=message.event,
        payload=message.payload or {},
        content=message.content,
        created_at=message.created_at,
        author=_user_basic_info(message.author if message.author_id else None),
    )


def visible_channels_q(user_id: int | None, *, relation: Literal["", "channel"] = "") -> Q:
    """The channel-visibility rule as a queryset filter; see ``Channel.visible_to_q``
    for the semantics. Exported for cross-product callers filtering channel-joined
    querysets. Single-object callers use ``get_channel``."""
    return Channel.visible_to_q(user_id, relation=relation)


def visible_tasks_q(user_id: int | None, *, relation: Literal["", "task"] = "") -> Q:
    return task_run_visibility_q(user_id) if relation == "task" else task_visibility_q(user_id)


def channel_exists(team_id: int, channel_id: str | UUID, user_id: int | None) -> bool:
    """Whether ``channel_id`` is a live channel in this team that the user may see."""
    return Channel.objects.filter(Channel.visible_to_q(user_id), id=channel_id, team_id=team_id, deleted=False).exists()


def _visible_channel(channel_id: str | UUID, team_id: int, user_id: int | None) -> Channel | None:
    """A channel the requester may read: any live public channel on the team, or their
    own personal channel. ``None`` when it's missing or someone else's personal channel."""
    return (
        _team_channels(team_id)
        .select_related("created_by")
        .filter(visible_channels_q(user_id), id=channel_id, deleted=False)
        .first()
    )


def list_channel_feed_messages(
    channel_id: str | UUID, team_id: int, user_id: int | None
) -> list[contracts.ChannelFeedMessageDTO] | None:
    """A channel's system-announcement feed, ascending. ``None`` when the channel isn't visible.
    Bounded to the newest ``CHANNEL_FEED_MAX_MESSAGES``: the feed holds rare lifecycle
    events, and the write path caps a channel at the same count. Add real pagination
    before any per-task or per-thread event lands here."""
    if _visible_channel(channel_id, team_id, user_id) is None:
        return None
    messages = (
        ChannelFeedMessage.objects.filter(channel_id=channel_id, team_id=team_id, deleted=False)
        .select_related("author")
        .order_by("-created_at", "-id")[:CHANNEL_FEED_MAX_MESSAGES]
    )
    return [_channel_feed_message_to_dto(message) for message in reversed(messages)]


def create_channel_feed_message(
    channel_id: str | UUID,
    team_id: int,
    user_id: int | None,
    *,
    event: str,
    payload: dict,
    created_at: datetime | None = None,
) -> contracts.ChannelFeedMessageDTO | None | str:
    """Post an announcement into a channel's feed as the requester. ``None`` when the
    channel isn't visible; ``"full"`` when the channel's feed is at capacity. The row is
    marked human-authored — ``system``/``agent`` kinds are reserved for server-side
    writers, so a client can't forge rows other clients render as trusted. ``author``
    records the acting user so the client can render "Adam …". ``created_at`` lets a
    client order a burst of announcements deterministically (else the server stamps
    ``now``)."""
    if _visible_channel(channel_id, team_id, user_id) is None:
        return None
    if (
        ChannelFeedMessage.objects.filter(channel_id=channel_id, team_id=team_id, deleted=False).count()
        >= CHANNEL_FEED_MAX_MESSAGES
    ):
        return "full"
    fields: dict = {
        "team_id": team_id,
        "channel_id": channel_id,
        "author_id": user_id,
        "author_kind": ChannelFeedMessage.AuthorKind.HUMAN,
        "event": event,
        "payload": payload or {},
    }
    if created_at is not None:
        fields["created_at"] = created_at
    message = ChannelFeedMessage.objects.create(**fields)
    # Fresh row: author lazy-loads once for the DTO.
    return _channel_feed_message_to_dto(message)


def get_channel(channel_id: str | UUID, team_id: int, user_id: int | None) -> contracts.ChannelDTO | None:
    """One channel the requester may read, or ``None``."""
    channel = _visible_channel(channel_id, team_id, user_id)
    if channel is None:
        return None
    starred = user_id is not None and _is_channel_starred(channel.id, user_id)
    return _channel_to_dto(channel, starred=starred)


# --- Channel instructions (CONTEXT.md) ---

# Generous cap on the markdown blob; channel instructions are descriptions, not documents.
CHANNEL_INSTRUCTIONS_MAX_BYTES = 100_000
MAX_CHANNEL_INSTRUCTIONS_VERSION = 2000


@dataclass
class ChannelInstructionsTooLargeError(Exception):
    max_bytes: int


@dataclass
class ChannelInstructionsVersionConflictError(Exception):
    current_version: int


@dataclass
class ChannelInstructionsVersionLimitError(Exception):
    max_version: int


def _instructions_to_dto(row: ChannelInstructions) -> contracts.ChannelInstructionsDTO:
    return contracts.ChannelInstructionsDTO(
        channel=row.channel_id,
        content=row.content,
        version=row.version,
        created_at=row.created_at,
        created_by=_user_basic_info(row.created_by if row.created_by_id else None),
    )


def _blank_instructions_dto(channel: Channel) -> contracts.ChannelInstructionsDTO:
    """A channel with no published instructions reads as blank version 0, so
    readers never 404 and a first publish guards on ``base_version: 0``."""
    return contracts.ChannelInstructionsDTO(channel=channel.id, content="", version=0)


def get_channel_instructions(
    channel_id: str | UUID, team_id: int, user_id: int | None
) -> contracts.ChannelInstructionsDTO | None:
    """The channel's latest instructions (blank version 0 when none exist).
    ``None`` when the channel isn't visible."""
    channel = _visible_channel(channel_id, team_id, user_id)
    if channel is None:
        return None
    latest = (
        ChannelInstructions.objects.filter(channel_id=channel.id, deleted=False, is_latest=True)
        .select_related("created_by")
        .first()
    )
    return _instructions_to_dto(latest) if latest is not None else _blank_instructions_dto(channel)


def desktop_users_in_team(team: Team, exclude_user_id: int) -> list[str]:
    channels = (
        Channel.objects.for_team(team.id)
        .filter(
            personal_channel_q(),
            deleted=False,
            created_by__in=team.all_users_with_access(),
        )
        .exclude(created_by_id=exclude_user_id)
        .select_related("created_by")
        .order_by("created_at")[:4]
    )
    return [
        channel.created_by.first_name or channel.created_by.email.split("@")[0]
        for channel in channels
        if channel.created_by
    ]


def organization_has_context(organization_id: UUID | str) -> bool:
    contents = (
        ChannelInstructions.objects.unscoped()
        .filter(
            general_channel_q("channel"),
            team__organization_id=organization_id,
            channel__deleted=False,
            deleted=False,
            is_latest=True,
            version__gt=0,
        )
        .exclude(content="")
        .values_list("content", flat=True)[:20]
    )
    return any(content.strip() for content in contents)


def list_channel_instruction_versions(
    channel_id: str | UUID, team_id: int, user_id: int | None
) -> list[contracts.ChannelInstructionsDTO] | None:
    """The channel's instruction history, newest first. ``None`` when the channel isn't visible."""
    if _visible_channel(channel_id, team_id, user_id) is None:
        return None
    versions = (
        ChannelInstructions.objects.filter(channel_id=channel_id, team_id=team_id, deleted=False)
        .select_related("created_by")
        .order_by("-version", "-created_at", "-id")[:200]
    )
    return [_instructions_to_dto(row) for row in versions]


def task_can_publish_channel_instructions(task_id: str | UUID, team_id: int, channel_id: str | UUID) -> bool:
    task = Task.objects.filter(id=task_id, team_id=team_id).only("origin_product").first()
    if task is None:
        return False
    if task.origin_product != Task.OriginProduct.LOOP:
        return True

    run_state = (
        TaskRun.objects.filter(task_id=task.id, team_id=team_id)
        .order_by("-created_at")
        .values_list("state", flat=True)
        .first()
    )
    context_target = ((run_state or {}).get("config_snapshot") or {}).get("context_target") or {}
    outputs = context_target.get("outputs") or {}
    return bool(outputs.get("update_context")) and str(context_target.get("channel_id")) == str(channel_id)


def loop_context_channel_id_for_task(task_id: str | UUID) -> str | None:
    """The channel a loop run was configured to keep current, or None.

    Scoped by task rather than by team, because the caller's authority here is a
    run token minted for exactly this task. Returns None for anything that is
    not a loop run configured to update its context, so callers fail closed.
    """
    task = Task.objects.filter(id=task_id).only("id", "origin_product").first()
    if task is None or task.origin_product != Task.OriginProduct.LOOP:
        return None

    run_state = TaskRun.objects.filter(task_id=task.id).order_by("-created_at").values_list("state", flat=True).first()
    context_target = ((run_state or {}).get("config_snapshot") or {}).get("context_target") or {}
    if not (context_target.get("outputs") or {}).get("update_context"):
        return None
    channel_id = context_target.get("channel_id")
    return str(channel_id) if channel_id else None


def publish_channel_instructions(
    channel_id: str | UUID,
    team_id: int,
    user_id: int | None,
    *,
    content: str,
    base_version: int | None = None,
) -> contracts.ChannelInstructionsDTO | None:
    """Publish a new instructions version, superseding the current latest.

    ``base_version`` guards against lost updates: when the current latest no
    longer matches, ``ChannelInstructionsVersionConflictError`` is raised.
    ``None`` when the channel isn't visible. Publishing clears the channel's
    in-progress context-generation marker.
    """
    channel = _visible_channel(channel_id, team_id, user_id)
    if channel is None:
        return None
    if len(content.encode("utf-8")) > CHANNEL_INSTRUCTIONS_MAX_BYTES:
        raise ChannelInstructionsTooLargeError(max_bytes=CHANNEL_INSTRUCTIONS_MAX_BYTES)
    with transaction.atomic():
        current_latest = (
            ChannelInstructions.objects.select_for_update()
            .filter(channel_id=channel.id, deleted=False, is_latest=True)
            .order_by("-version", "-created_at", "-id")
            .first()
        )
        current_version = current_latest.version if current_latest is not None else 0
        if base_version is not None and base_version != current_version:
            raise ChannelInstructionsVersionConflictError(current_version=current_version)
        if current_version >= MAX_CHANNEL_INSTRUCTIONS_VERSION:
            raise ChannelInstructionsVersionLimitError(max_version=MAX_CHANNEL_INSTRUCTIONS_VERSION)
        if current_latest is not None:
            ChannelInstructions.objects.filter(pk=current_latest.pk).update(is_latest=False)
        try:
            # Nested savepoint: a lost-update race (the select_for_update above
            # locks no row when none exists yet, and a concurrent delete clears
            # is_latest without adding a lockable row) makes the insert collide
            # with the (channel, version) uniqueness. Rolling back to the
            # savepoint keeps this transaction usable so we can read the winner.
            with transaction.atomic():
                published = ChannelInstructions.objects.create(
                    team_id=team_id,
                    channel_id=channel.id,
                    content=content,
                    version=current_version + 1,
                    is_latest=True,
                    created_by_id=user_id,
                )
        except IntegrityError:
            # Surface the race as the conflict the view maps to 409, not a 500.
            latest = (
                ChannelInstructions.objects.filter(channel_id=channel.id, deleted=False)
                .order_by("-version", "-created_at", "-id")
                .first()
            )
            raise ChannelInstructionsVersionConflictError(current_version=latest.version if latest is not None else 0)
        # Publishing produced a result, so drop the in-progress generation marker.
        ChannelContextGeneration.objects.filter(channel_id=channel.id).update(task_id=None)
    return _instructions_to_dto(published)


def delete_channel_instructions(channel_id: str | UUID, team_id: int, user_id: int | None) -> int | None:
    """Soft-delete every instructions version. Returns the count, or ``None``
    when the channel isn't visible."""
    channel = _visible_channel(channel_id, team_id, user_id)
    if channel is None:
        return None
    with transaction.atomic():
        count = (
            ChannelInstructions.objects.select_for_update()
            .filter(channel_id=channel.id, deleted=False)
            .update(deleted=True, is_latest=False)
        )
        ChannelContextGeneration.objects.filter(channel_id=channel.id).update(task_id=None)
    return count


def get_channel_context_generation(
    channel_id: str | UUID, team_id: int, user_id: int | None
) -> str | None | Literal["not_found"]:
    """The id of the task currently generating the channel's CONTEXT.md, or ``None``."""
    channel = _visible_channel(channel_id, team_id, user_id)
    if channel is None:
        return "not_found"
    marker = ChannelContextGeneration.objects.filter(channel_id=channel.id).first()
    return str(marker.task_id) if marker is not None and marker.task_id else None


def set_channel_context_generation(
    channel_id: str | UUID, team_id: int, user_id: int | None, *, task_id: str | UUID | None
) -> str | None | Literal["not_found", "invalid_task"]:
    """Set or clear the task associated with the channel's CONTEXT.md generation."""
    channel = _visible_channel(channel_id, team_id, user_id)
    if channel is None:
        return "not_found"
    if task_id is not None and not task_exists(task_id, team_id):
        return "invalid_task"
    ChannelContextGeneration.objects.update_or_create(
        channel_id=channel.id, defaults={"team_id": team_id, "task_id": task_id}
    )
    return str(task_id) if task_id else None


def star_channel(channel_id: str | UUID, team_id: int, user_id: int, *, starred: bool) -> bool:
    """Star or unstar a channel for the requesting user. False when the channel isn't visible."""
    channel = _visible_channel(channel_id, team_id, user_id)
    if channel is None:
        return False
    _set_channel_star(channel.id, team_id, user_id, starred=starred)
    return True


def _thread_message_to_dto(message: TaskThreadMessage) -> contracts.TaskThreadMessageDTO:
    return contracts.TaskThreadMessageDTO(
        id=message.id,
        task=message.task_id,
        author_kind=message.author_kind,
        event=message.event,
        payload=message.payload or {},
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
        # The thread is human-to-human plus artifact announcements; rows written
        # back when the agent finished a turn (a since-removed behavior) stay out.
        .exclude(event="turn_complete")
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
        project_thread_message_activity(message)
    except Exception:
        logger.exception("Failed to project thread message activity", extra={"message_id": str(message.id)})
    try:
        mentioned_user_ids = resolve_mentioned_user_ids(
            User, message.content, team_id=message.team_id, author_id=message.author_id
        )
    except Exception:
        mentioned_user_ids = []
        logger.exception("Failed to resolve thread message mentions", extra={"message_id": str(message.id)})
    try:
        _index_thread_message_mentions(message, mentioned_user_ids)
    except Exception:
        # Mention indexing is best-effort: a failure must never fail message creation or discard resolved recipients.
        logger.exception("Failed to index thread message mentions", extra={"message_id": str(message.id)})
    from products.tasks.backend.push_dispatcher import notify_task_thread_message  # noqa: PLC0415

    notify_task_thread_message(message, mentioned_user_ids)
    # Fresh message: forwarded_by is None (no query) and author lazy-loads once.
    return _thread_message_to_dto(message)


def _index_thread_message_mentions(message: TaskThreadMessage, mentioned_user_ids: Collection[int]) -> None:
    """Create mention index rows for @[Name](email) tokens in the message content.

    Emails resolve case-insensitively, only to members of the team's organization;
    self-mentions are skipped (they are never notifications).
    """
    mentions = [
        TaskThreadMessageMention(
            team_id=message.team_id,
            message_id=message.id,
            task_id=message.task_id,
            mentioned_user_id=mentioned_user_id,
            created_at=message.created_at,
        )
        for mentioned_user_id in mentioned_user_ids
    ]
    TaskThreadMessageMention.objects.for_team(message.team_id).bulk_create(
        mentions,
        ignore_conflicts=True,
    )
    for mention in mentions:
        TaskActivity.record(
            team_id=message.team_id,
            user_id=mention.mentioned_user_id,
            task_id=message.task_id,
            kind=TaskActivity.Kind.MENTION,
            activity_at=message.created_at,
            message_id=message.id,
        )


def task_comment_target_is_accessible(
    *, team_id: int, user_id: int | None, task_id: str | UUID, scope: str, item_id: str | None
) -> bool:
    from products.tasks.backend.logic.services.comment_activity import target_is_accessible

    return target_is_accessible(team_id=team_id, user_id=user_id, task_id=task_id, scope=scope, item_id=item_id)


def task_comment_mentions_allowed(*, team_id: int, task_id: str | UUID) -> bool:
    from products.tasks.backend.logic.services.comment_activity import notifications_allowed

    return notifications_allowed(team_id=team_id, task_id=task_id)


def record_comment_activity(
    *,
    team_id: int,
    comment_id: UUID,
    mentioned_user_ids: Sequence[int],
    include_relationship_recipients: bool = True,
    target_owner_id: int | None = None,
    activity_at: datetime | None = None,
) -> None:
    from products.tasks.backend.logic.services.comment_activity import project_comment_activity

    project_comment_activity(
        team_id=team_id,
        comment_id=comment_id,
        mentioned_user_ids=mentioned_user_ids,
        include_relationship_recipients=include_relationship_recipients,
        target_owner_id=target_owner_id,
        activity_at=activity_at,
    )
    post_comment_thread_update(team_id=team_id, comment_id=comment_id)


def enqueue_comment_activity_retry(
    *,
    team_id: int,
    comment_id: str,
    mentioned_user_ids: list[int],
    include_relationship_recipients: bool,
    target_owner_id: int | None,
    activity_at: str | None,
) -> None:
    from products.tasks.backend.tasks.tasks import (  # noqa: PLC0415 — avoids the facade/task circular import
        project_task_comment_activity,
    )

    project_task_comment_activity.delay(
        team_id=team_id,
        comment_id=comment_id,
        mentioned_user_ids=mentioned_user_ids,
        include_relationship_recipients=include_relationship_recipients,
        target_owner_id=target_owner_id,
        activity_at=activity_at,
    )


def list_task_artifacts(*, team_id: int, task_id: UUID) -> list[contracts.TaskArtifactDTO]:
    from products.tasks.backend.logic.services.task_comments import list_artifacts

    return list_artifacts(team_id=team_id, task_id=task_id)


def list_task_comments(
    *,
    team_id: int,
    task_id: UUID,
    artifact_id: str | None,
    include_resolved: bool,
    limit: int,
    cursor: str | None,
) -> contracts.TaskCommentPageDTO:
    from products.tasks.backend.logic.services.task_comments import InvalidTaskCommentCursor, list_comments

    try:
        return list_comments(
            team_id=team_id,
            task_id=task_id,
            artifact_id=artifact_id,
            include_resolved=include_resolved,
            limit=limit,
            cursor=cursor,
        )
    except InvalidTaskCommentCursor:
        raise ValueError("Invalid task comment cursor") from None


def retrieve_task_comment(
    *,
    team_id: int,
    task_id: UUID,
    comment_id: UUID,
    limit: int,
    cursor: str | None,
    content_comment_id: UUID | None,
    content_offset: int,
) -> contracts.TaskCommentDetailDTO | None:
    from products.tasks.backend.logic.services.task_comments import InvalidTaskCommentCursor, retrieve_comment

    try:
        return retrieve_comment(
            team_id=team_id,
            task_id=task_id,
            comment_id=comment_id,
            limit=limit,
            cursor=cursor,
            content_comment_id=content_comment_id,
            content_offset=content_offset,
        )
    except InvalidTaskCommentCursor:
        raise ValueError("Invalid task comment cursor") from None


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
        # Legacy turn_complete rows are hidden from threads (see list_thread_messages),
        # so their indexed mentions must not surface notifications pointing at them.
    ).exclude(message__event="turn_complete")
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


def project_thread_message_activity(message: TaskThreadMessage) -> None:
    """Project a new thread message onto the feed of everyone it concerns."""
    recipient_ids = {recipient_id for recipient_id in (message.author_id, message.task.created_by_id) if recipient_id}
    for recipient_id in recipient_ids:
        TaskActivity.record(
            team_id=message.team_id,
            user_id=recipient_id,
            task_id=message.task_id,
            kind=TaskActivity.Kind.MESSAGE,
            activity_at=message.created_at,
            message_id=message.id,
            actor_id=message.author_id,
        )


def project_awaiting_input_activity(task_run: "TaskRun") -> None:
    """Flag the task creator's feed row when a run stops and needs them.

    Called from ``push_dispatcher.notify_task_run_awaiting_input`` so every path that
    decides a run is waiting (stream ingest, agent proxy callback, sandbox relay) projects
    the same row. Deliberately outside the push feature flag and its Redis cooldown — the
    in-app feed should update even where the mobile push is off.
    """
    creator_id = task_run.task.created_by_id
    if creator_id is None:
        return
    TaskActivity.record(
        team_id=task_run.task.team_id,
        user_id=creator_id,
        task_id=task_run.task_id,
        kind=TaskActivity.Kind.AWAITING_INPUT,
        activity_at=django_timezone.now(),
    )


def project_completed_activity(task_run: "TaskRun") -> None:
    creator_id = task_run.task.created_by_id
    if creator_id is None:
        return
    TaskActivity.record(
        team_id=task_run.task.team_id,
        user_id=creator_id,
        task_id=task_run.task_id,
        kind=TaskActivity.Kind.COMPLETED,
        activity_at=task_run.completed_at or django_timezone.now(),
    )


def _task_activity_qs(team_id: int, user_id: int) -> QuerySet[TaskActivity]:
    """The requester's feed rows, gated to tasks they can still see.

    Rows outlive visibility changes (a task moving to a private channel, say), so the
    visibility gate belongs on read rather than being enforced when projecting.
    """
    visible_tasks = _visible_task_qs(team_id, user_id).filter(internal=False, archived=False)
    return TaskActivity.objects.for_team(team_id).filter(user_id=user_id, task__in=visible_tasks)


def _comment_activity_qs(team_id: int, user_id: int) -> QuerySet[TaskCommentActivity]:
    visible_tasks = _visible_task_qs(team_id, user_id).filter(internal=False, archived=False)
    return TaskCommentActivity.objects.for_team(team_id).filter(
        user_id=user_id, task__in=visible_tasks, comment__deleted=False
    )


def count_unread_task_activity(team_id: int, user_id: int | None) -> int:
    """Unread tasks across the requester's whole feed. Backs the sidebar badge."""
    if user_id is None:
        return 0
    return (
        _task_activity_qs(team_id, user_id).filter(read_at__isnull=True).count()
        + _comment_activity_qs(team_id, user_id).filter(read_at__isnull=True).count()
    )


def list_task_activity(
    team_id: int,
    user_id: int | None,
    *,
    limit: int = 100,
    before: datetime | None = None,
    before_id: UUID | None = None,
) -> contracts.TaskActivityPageDTO:
    """The requester's task and comment activity, newest first.

    ``unread_count`` counts every unread row the requester can see, not just the ones in
    this page, so the sidebar badge stays honest past ``limit``.
    """
    if user_id is None:
        return contracts.TaskActivityPageDTO(results=[], unread_count=0)
    task_qs = _task_activity_qs(team_id, user_id)
    comment_qs = _comment_activity_qs(team_id, user_id)
    if before is not None and before_id is not None:
        cursor = Q(activity_at__lt=before) | Q(activity_at=before, id__lt=before_id)
        task_qs = task_qs.filter(cursor)
        comment_qs = comment_qs.filter(cursor)
    task_rows = task_qs.select_related("task__channel", "message__author").order_by("-activity_at", "-id")[: limit + 1]
    comment_rows = comment_qs.select_related("task__channel", "comment__created_by").order_by("-activity_at", "-id")[
        : limit + 1
    ]
    activity_rows: list[TaskActivity | TaskCommentActivity] = [*task_rows, *comment_rows]
    rows: list[TaskActivity | TaskCommentActivity] = sorted(
        activity_rows,
        key=lambda row: (row.activity_at, row.id),
        reverse=True,
    )[: limit + 1]
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_row = rows[-1] if has_more else None

    return contracts.TaskActivityPageDTO(
        results=[
            contracts.TaskActivityDTO(
                id=row.id,
                task_id=row.task_id,
                task_title=row.task.title,
                channel_id=row.task.channel_id,
                channel_name=row.task.channel.name if row.task.channel else None,
                activity_at=row.activity_at,
                activity_kind=row.kind,
                snippet=_bounded_activity_snippet(
                    (row.comment.content or "" if row.comment else "")
                    if isinstance(row, TaskCommentActivity)
                    else (row.message.content if row.message else "")
                ),
                latest_author=_user_basic_info(
                    row.comment.created_by
                    if isinstance(row, TaskCommentActivity)
                    else (row.message.author if row.message and row.message.author_id else None)
                ),
                latest_message_id=None if isinstance(row, TaskCommentActivity) else row.message_id,
                latest_comment_id=row.root_comment_id if isinstance(row, TaskCommentActivity) else None,
                latest_comment_scope=row.comment.scope if isinstance(row, TaskCommentActivity) else None,
                latest_comment_item_id=row.comment.item_id if isinstance(row, TaskCommentActivity) else None,
                is_unread=row.read_at is None,
            )
            for row in rows
        ],
        unread_count=count_unread_task_activity(team_id, user_id),
        next_before=next_row.activity_at if next_row else None,
        next_before_id=next_row.id if next_row else None,
    )


def _bounded_activity_snippet(content: str, limit: int = 1024) -> str:
    return content.encode("utf-8")[:limit].decode("utf-8", errors="ignore")


def mark_task_activity_read(
    team_id: int,
    user_id: int | None,
    activities: Sequence[tuple[UUID, datetime, UUID | None]],
) -> int:
    """Mark feed rows read only when their latest activity was visible to the requester."""
    if user_id is None or not activities:
        return 0
    activity_versions = Q()
    comment_activity_ids: list[UUID] = []
    for task_id, seen_before, comment_activity_id in activities:
        if comment_activity_id:
            comment_activity_ids.append(comment_activity_id)
        else:
            activity_versions |= Q(task_id=task_id, activity_at__lte=seen_before)
    task_rows = 0
    if activity_versions:
        task_rows = (
            TaskActivity.objects.for_team(team_id)
            .filter(user_id=user_id, read_at__isnull=True)
            .filter(activity_versions)
            .update(read_at=django_timezone.now())
        )
    comment_rows = (
        TaskCommentActivity.objects.for_team(team_id)
        .filter(
            user_id=user_id,
            id__in=comment_activity_ids,
            read_at__isnull=True,
        )
        .update(read_at=django_timezone.now())
    )
    return task_rows + comment_rows


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


# Threads are a Channels (project-bluebird) surface, so agent-authored thread
# updates are gated on the same flag — evaluated for the task creator.
AGENT_THREAD_UPDATES_FLAG = "project-bluebird"


def _create_agent_thread_message(task: Task, content: str, *, event: str, payload: dict | None = None) -> None:
    """Write an agent-authored thread message and index its mentions.

    ``content`` is the rendered text (older clients show it as-is); ``event`` +
    ``payload`` are the structured record, mirroring ChannelFeedMessage, that
    lets clients render agent rows natively and dedupe them against live views.
    """
    # for_team: callers include non-request contexts (temporal relay) where the
    # fail-closed manager has no team scope.
    message = TaskThreadMessage.objects.for_team(task.team_id).create(
        team_id=task.team_id,
        task_id=task.id,
        author_id=None,
        author_kind=TaskThreadMessage.AuthorKind.AGENT,
        event=event,
        payload=payload or {},
        content=content,
    )
    try:
        # A projection failure must not roll back the caller's dedup transaction with
        # the announcement in it; the savepoint contains a database error.
        with transaction.atomic():
            project_thread_message_activity(message)
    except Exception:
        logger.exception("Failed to project thread message activity", extra={"message_id": str(message.id)})
    try:
        mentioned_user_ids = resolve_mentioned_user_ids(
            User, message.content, team_id=message.team_id, author_id=message.author_id
        )
        _index_thread_message_mentions(message, mentioned_user_ids)
    except Exception:
        logger.exception("Failed to index thread message mentions", extra={"message_id": str(message.id)})


def _agent_thread_updates_enabled(creator: User | None) -> bool:
    """Fail closed: no creator to key the flag on, or a flag-service error, means no post."""
    if creator is None:
        return False
    # Local dev rarely has the server-side flag client wired up, and failing
    # closed there silently drops every agent thread update (PR and canvas
    # announcements vanish from task threads with nothing in the logs).
    if settings.DEBUG:
        return True
    distinct_id = creator.distinct_id or f"user_{creator.id}"
    try:
        return bool(
            posthoganalytics.feature_enabled(AGENT_THREAD_UPDATES_FLAG, distinct_id, send_feature_flag_events=False)
        )
    except Exception:
        logger.warning("Agent thread update flag check failed", extra={"user_id": creator.id}, exc_info=True)
        return False


def _commit_push_head_sha(output: object) -> str:
    if not isinstance(output, dict) or not isinstance(output.get("commit_push"), dict):
        return ""
    commits = output["commit_push"].get("commits")
    if not isinstance(commits, list) or not commits or not isinstance(commits[-1], dict):
        return ""
    sha = commits[-1].get("sha")
    return sha[:64] if isinstance(sha, str) else ""


def post_commits_pushed_thread_update(run: TaskRun, push: dict) -> None:
    try:
        head_sha = _commit_push_head_sha({"commit_push": push})
        if not head_sha:
            return
        task = Task.objects.select_related("created_by").filter(id=run.task_id, team_id=run.team_id).first()
        if task is None or not _agent_thread_updates_enabled(task.created_by):
            return
        raw_commits = push.get("commits")
        if not isinstance(raw_commits, list):
            return
        commits = [
            {
                "sha": str(commit.get("sha") or "")[:64],
                "subject": str(commit.get("subject") or "")[:120],
                "url": str(commit.get("url") or "")[:2048],
            }
            for commit in raw_commits[-10:]
            if isinstance(commit, dict) and commit.get("sha")
        ]
        if not commits:
            return
        with transaction.atomic():
            Task.objects.select_for_update().filter(id=task.id).first()
            if (
                TaskThreadMessage.objects.for_team(task.team_id)
                .filter(task_id=task.id, event="commits_pushed", payload__head_sha=head_sha)
                .exists()
            ):
                return
            # Branch is caller-controlled and flows into rendered markdown content
            # and the server-side mention scanner. Strip the bracket and newline
            # characters that would otherwise forge a [label](url) link, a
            # ![alt](url) image, or an @[name](email) mention (the canvas-name and
            # PR-URL guards below sanitize their equivalents for the same reason).
            branch = re.sub(r"[\[\]\n]", " ", str(push.get("branch") or "")).strip()[:255]
            count = len(raw_commits)
            content = f"{count} commit{'s' if count != 1 else ''} pushed"
            _create_agent_thread_message(
                task,
                f"{content} to {branch}" if branch else content,
                event="commits_pushed",
                payload={
                    "run_id": str(run.id),
                    "branch": branch,
                    "repository": str(push.get("repository") or "")[:255],
                    "commits": commits,
                    "total": count,
                    "head_sha": head_sha,
                },
            )
    except Exception:
        logger.exception("Failed to post commits-pushed thread update", extra={"task_id": str(run.task_id)})


def _comment_target_name(task: Task, *, scope: str, item_id: str | None) -> str | None:
    """The commented artifact's display name for the row label; None on the task's own scope."""
    if scope != "task_artifact" or not item_id:
        return None
    try:
        name = (
            TaskArtifact.objects.for_team(task.team_id)
            .filter(task_id=task.id, id=item_id)
            .values_list("name", flat=True)
            .first()
        )
    except (ValueError, DjangoValidationError):
        name = None
    if not name:
        run = (
            TaskRun.objects.filter(team_id=task.team_id, task_id=task.id, artifacts__contains=[{"id": item_id}])
            .values_list("artifacts", flat=True)
            .first()
        )
        name = next((entry.get("name") for entry in run or [] if entry.get("id") == item_id), None)
    return str(name)[:255] if name else None


def post_comment_thread_update(*, team_id: int, comment_id: UUID) -> None:
    """Draw a comment on the task timeline: identity-only payload, the commenter as author.

    Root comments and resolve/reopen replies each get a row; plain replies stay in the
    Comments tab so a busy thread cannot flood the timeline.
    """
    from posthog.models.comment import Comment  # noqa: PLC0415 — keeps the comments app off the api import path

    from products.tasks.backend.logic.services.comment_activity import comment_task_id  # noqa: PLC0415

    try:
        comment = Comment.objects.filter(team_id=team_id, id=comment_id, deleted=False).first()
        if comment is None or comment.created_by_id is None:
            return
        context = comment.item_context if isinstance(comment.item_context, dict) else {}
        thread_state = context.get("threadState")
        if comment.source_comment_id and thread_state in ("resolved", "open"):
            event = "comment_state_changed"
        elif comment.source_comment_id:
            return
        else:
            event = "comment_added"
        task_id = comment_task_id(comment)
        if task_id is None:
            return
        task = Task.objects.select_related("created_by").filter(id=task_id, team_id=team_id).first()
        if task is None or not _agent_thread_updates_enabled(task.created_by):
            return
        payload: dict = {
            "comment_id": str(comment.id),
            "root_comment_id": str(comment.source_comment_id or comment.id),
            "scope": comment.scope,
            "item_id": str(comment.item_id) if comment.item_id else None,
            "target_name": _comment_target_name(task, scope=comment.scope, item_id=comment.item_id),
        }
        if event == "comment_state_changed":
            payload["state"] = thread_state
            content = "Resolved a comment thread" if thread_state == "resolved" else "Reopened a comment thread"
        else:
            content = "Commented"
        with transaction.atomic():
            Task.objects.select_for_update().filter(id=task.id).first()
            if (
                TaskThreadMessage.objects.for_team(task.team_id)
                .filter(task_id=task.id, event=event, payload__comment_id=str(comment.id))
                .exists()
            ):
                return
            # Not _create_agent_thread_message: the commenter is the author, and the
            # comment path already projected activity and indexed mentions.
            TaskThreadMessage.objects.for_team(task.team_id).create(
                team_id=task.team_id,
                task_id=task.id,
                author_id=comment.created_by_id,
                author_kind=TaskThreadMessage.AuthorKind.HUMAN,
                event=event,
                payload=payload,
                content=content,
            )
    except Exception:
        logger.exception("Failed to post comment thread update", extra={"comment_id": str(comment_id)})


def _announce_agent_artifact_uploads(run: TaskRun, new_entries: list[dict], manifest: list[dict]) -> None:
    """Announce files the agent delivered as task outputs.

    The manifest also holds internal state such as git handoff checkpoints and skill
    bundles. Those files support the run but are not deliverables for the timeline.
    Manifest entries carry no version, so same-named output entries determine whether
    an upload created or revised a file. The artifact id deduplicates retried uploads.
    """
    output_entries = [entry for entry in new_entries if entry.get("type") == "output"]
    new_output_ids = {entry.get("id") for entry in output_entries}
    announced_in_batch: dict[str, int] = {}
    for entry in output_entries:
        name = entry.get("name")
        prior_versions = sum(
            1
            for other in manifest
            if other.get("type") == "output" and other.get("name") == name and other.get("id") not in new_output_ids
        ) + announced_in_batch.get(name or "", 0)
        announced_in_batch[name or ""] = announced_in_batch.get(name or "", 0) + 1
        post_artifact_thread_update(
            run,
            {
                "id": entry.get("id"),
                "name": name,
                "artifact_type": entry.get("type"),
                "current_version": prior_versions + 1,
            },
            revised=prior_versions > 0,
        )


def post_artifact_thread_update(run: TaskRun, artifact: dict, *, revised: bool) -> None:
    try:
        artifact_id = str(artifact.get("id") or "")
        # Caller-controlled, rendered as markdown, and scanned for mentions: strip
        # link/mention syntax like the commits-pushed branch field.
        name = re.sub(r"[\[\]\n]", " ", str(artifact.get("name") or "")).strip()[:255]
        if not artifact_id or not name:
            return
        raw_version = artifact.get("current_version")
        version = raw_version if isinstance(raw_version, int) else 1
        task = Task.objects.select_related("created_by").filter(id=run.task_id, team_id=run.team_id).first()
        if task is None or not _agent_thread_updates_enabled(task.created_by):
            return
        reference_type = str(artifact.get("reference_type") or "")[:64]
        object_kind = str(artifact.get("object_kind") or "")[:64]
        event = "artifact_revised" if revised else "artifact_created"
        with transaction.atomic():
            Task.objects.select_for_update().filter(id=task.id).first()
            if (
                TaskThreadMessage.objects.for_team(task.team_id)
                .filter(task_id=task.id, event=event, payload__artifact_id=artifact_id, payload__version=version)
                .exists()
            ):
                return
            verb = "Revised" if revised else "Added" if reference_type == "posthog_object" else "Created"
            payload = {
                "run_id": str(run.id),
                "artifact_id": artifact_id,
                "name": name,
                "artifact_type": str(artifact.get("artifact_type") or "")[:64],
                "version": version,
            }
            if reference_type:
                payload["reference_type"] = reference_type
            if object_kind:
                payload["object_kind"] = object_kind
            _create_agent_thread_message(task, f"{verb} {name}", event=event, payload=payload)
    except Exception:
        logger.exception("Failed to post artifact thread update", extra={"task_id": str(run.task_id)})


def _thread_safe_canvas_name(canvas_name: str) -> str:
    # Brackets and newlines in the name would break the [label](url) token.
    return re.sub(r"[\[\]\n]", " ", canvas_name).strip() or "Canvas"


def post_canvas_created_thread_update(
    task_id: str | UUID, team_id: int, *, acting_user_id: int | None, canvas_name: str, canvas_url: str | None
) -> None:
    """Announce a freshly created canvas in the generating task's thread.

    Posts "[name](url) has been created" as an agent message. Called on a canvas's
    first publish only — the caller owns that once-guard. ``acting_user_id`` must be
    the task's creator: the sandbox publishes with the creator's credentials, so this
    binds the attributed task to the caller's identity — a same-team caller can't
    plant agent messages in someone else's task thread by naming its id. Best-effort
    and never raises: the publish must not fail because its announcement couldn't
    be written.
    """
    try:
        task = Task.objects.select_related("created_by").filter(id=task_id, team_id=team_id).first()
        if task is None or task.created_by_id is None or task.created_by_id != acting_user_id:
            return
        if not _agent_thread_updates_enabled(task.created_by):
            return
        name = _thread_safe_canvas_name(canvas_name)
        content = f"[{name}]({canvas_url}) has been created" if canvas_url else f"{name} has been created"
        _create_agent_thread_message(
            task,
            content,
            event="canvas_created",
            payload={"canvas_name": name, "canvas_url": canvas_url},
        )
    except Exception:
        logger.exception("Failed to post canvas-created thread update", extra={"task_id": str(task_id)})


def post_canvas_error_thread_update(
    task_id: str | UUID,
    team_id: int,
    *,
    canvas_id: str,
    canvas_name: str,
    build_id: str,
    source_version_id: str | None,
    error_type: str,
    origin: str,
    error_codes: list[str] | None = None,
) -> str:
    """File a canvas failure report (``event="canvas_error_reported"``) in the authoring task's thread.

    ``error_type``/``error_codes`` must already be validated identifiers — the canvas
    backend owns that sanitization because everything here lands in agent-visible text.
    The task id is resolved server-side from the canvas record, never caller-named, so
    a teammate can't plant reports in an unrelated task's thread. Dedupes per
    ``(build_id, error_type)`` under the task row lock, mirroring ``pr_created``.
    Returns ``filed`` / ``duplicate`` / ``skipped``; never raises.
    """
    try:
        task = Task.objects.select_related("created_by").filter(id=task_id, team_id=team_id).first()
        if task is None or not _agent_thread_updates_enabled(task.created_by):
            return "skipped"
        with transaction.atomic():
            Task.objects.select_for_update().filter(id=task.id).first()
            if (
                TaskThreadMessage.objects.for_team(task.team_id)
                .filter(
                    task_id=task.id,
                    event="canvas_error_reported",
                    payload__build_id=build_id,
                    payload__error_type=error_type,
                )
                .exists()
            ):
                return "duplicate"
            name = _thread_safe_canvas_name(canvas_name)
            if origin == "build":
                codes = ", ".join(error_codes or []) or "unknown"
                content = f'Canvas "{name}" build failed ({codes})'
            else:
                content = f'Canvas "{name}" hit a runtime error ({error_type}) in a rendering session'
            _create_agent_thread_message(
                task,
                content,
                event="canvas_error_reported",
                payload={
                    "canvas_id": canvas_id,
                    "canvas_name": name,
                    "build_id": build_id,
                    "source_version_id": source_version_id,
                    "error_type": error_type,
                    "origin": origin,
                    "error_codes": error_codes or [],
                },
            )
        return "filed"
    except Exception:
        logger.exception("Failed to post canvas-error thread update", extra={"task_id": str(task_id)})
        return "skipped"


def _canvas_fix_denial_outcome(reason: str) -> str:
    """Map a compute-quota denial to a canvas fix outcome.

    Deactivation and quota exhaustion need different copy: a retry clears a spent
    quota but never a deactivation.
    """
    from products.tasks.backend.logic.services.compute_quota import (  # noqa: PLC0415
        ORGANIZATION_DEACTIVATED_DENIAL_CODE,
    )

    return "organization_deactivated" if reason == ORGANIZATION_DEACTIVATED_DENIAL_CODE else "quota_exhausted"


def request_canvas_fix(task_id: str | UUID, team_id: int, *, prompt: str, acting_user_id: int | None) -> str:
    """Wake a task's agent to fix a canvas: signal the live run, else seed a fresh run with ``prompt``.

    Creator-only, like every run-driving surface (``forward_thread_message``,
    ``task_control_q``): the dispatched run executes with the task creator's
    credentials, so nobody else may start or steer it. The task row is locked
    for the duration so overlapping fix requests serialize instead of each
    creating a paid run. The fresh-run path creates the run inside the
    transaction and dispatches its processing workflow on commit with
    ``skip_user_check``.
    Returns ``signaled`` / ``new_run`` / ``already_queued`` / ``not_found`` /
    ``forbidden`` / ``quota_exhausted`` / ``organization_deactivated``.
    """
    from products.tasks.backend.exceptions import (
        ComputeBillingLimitError,  # noqa: PLC0415 — keep temporalio off the api import path
    )
    from products.tasks.backend.logic.services.compute_quota import get_compute_quota_denial_reason  # noqa: PLC0415

    with transaction.atomic():
        # of=("self",): FOR UPDATE cannot span the nullable created_by join.
        task = (
            Task.objects.select_for_update(of=("self",))
            .select_related("team", "created_by")
            .filter(id=task_id, team_id=team_id)
            .first()
        )
        if task is None:
            return "not_found"
        if acting_user_id is None or task.created_by_id != acting_user_id:
            return "forbidden"
        if reason := get_compute_quota_denial_reason(task):
            return _canvas_fix_denial_outcome(reason)
        run = task.latest_run
        if run is not None and not run.is_terminal:
            try:
                if signal_task_run_user_message(
                    run.id, task.id, team_id, content=prompt, artifact_ids=[], actor_user_id=acting_user_id
                ):
                    return "signaled"
            except ComputeBillingLimitError as error:
                return _canvas_fix_denial_outcome(error.reason)
            if run.status == TaskRun.Status.QUEUED and (run.state or {}).get("pending_user_message"):
                # A queued, prompt-seeded run whose workflow hasn't registered yet
                # is a fix run a just-committed request dispatched (creation is
                # serialized on this row lock). Another run would double-bill.
                return "already_queued"
            # The workflow is gone despite the non-terminal row (evicted or stale); fall
            # through to a fresh run rather than reporting a dead end.
        task_run = task.create_run(mode="background", extra_state={"pending_user_message": prompt})
        from products.tasks.backend.logic.services.workflow_dispatch import (  # noqa: PLC0415
            WorkflowDispatchOptions,
            enqueue_or_start_workflow,
        )

        enqueue_or_start_workflow(
            task_run,
            options=WorkflowDispatchOptions(user_id=task.created_by_id, skip_user_check=True),
        )
    return "new_run"


def request_canvas_change(
    task_id: str | UUID,
    team_id: int,
    *,
    prompt: str,
    viewer_prompt: str,
    acting_user_id: int | None,
) -> str:
    """Dispatch a creator's canvas request, or file a teammate's request for review."""
    with transaction.atomic():
        task = Task.objects.select_for_update().filter(id=task_id, team_id=team_id).first()
        if task is None:
            return "not_found"
        if acting_user_id is None:
            return "not_found"
        is_creator = task.created_by_id == acting_user_id
    if not is_creator:
        # A teammate can reach this through a canvas they can see while the authoring
        # task is deleted or filed in a space they can't — the thread message is then
        # dropped, so surface the miss instead of reporting a delivery that didn't happen.
        filed = create_thread_message(
            task_id,
            team_id,
            acting_user_id,
            content=f"Requested from the canvas:\n\n{viewer_prompt}",
        )
        return "reported" if filed is not None else "not_found"
    outcome = request_canvas_fix(task_id, team_id, prompt=prompt, acting_user_id=acting_user_id)
    # already_queued is a deduplicated repeat: the request that queued the run
    # already wrote this entry, so writing another would double the record.
    if outcome in {"signaled", "new_run"}:
        create_thread_message(task_id, team_id, acting_user_id, content="Run requested from the canvas")
    return outcome


_GITHUB_PR_PATH_PATTERN = re.compile(r"/([^/]+)/([^/]+)/pull/(\d+)/?", re.IGNORECASE)

# Characters that could break out of a markdown [label](url) token or smuggle
# extra markdown into the rendered thread message.
_PR_URL_UNSAFE_CHARS = set(" \t\n\r()[]<>\"'`\\")

_PR_URL_MAX_LENGTH = 2048


def _is_safe_pr_url(pr_url: str) -> bool:
    """Whether ``pr_url`` is a plain http(s) URL safe to embed in a markdown link.

    ``pr_url`` originates from task-run output APIs, so it is caller-controlled.
    Real PR URLs never contain whitespace, quotes, brackets, or parentheses;
    anything that does is rejected rather than escaped.
    """
    if not pr_url or len(pr_url) > _PR_URL_MAX_LENGTH or any(char in _PR_URL_UNSAFE_CHARS for char in pr_url):
        return False
    parsed = urlparse(pr_url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _pr_display_label(pr_url: str) -> str:
    parsed = urlparse(pr_url)
    if parsed.hostname is None or parsed.hostname.lower() != "github.com":
        return pr_url
    match = _GITHUB_PR_PATH_PATTERN.fullmatch(parsed.path)
    if match:
        owner, repo, number = match.groups()
        return f"{owner}/{repo}#{number}"
    return pr_url


def post_pr_created_thread_update(run: TaskRun, pr_url: str) -> None:
    """Announce a run's freshly opened pull request in its task's thread.

    Posts "[owner/repo#N](url) has been opened" as an agent artifact message
    (``event="pr_created"``). Both the agent-output path and the GitHub webhook
    backstop can observe the same PR, so the announcement dedupes on the task's
    existing ``pr_created`` rows for this URL. Best-effort and never raises —
    recording the PR must not fail because its announcement couldn't be written.
    """
    try:
        if not _is_safe_pr_url(pr_url):
            logger.info("pr_created thread update skipped", extra={"task_id": str(run.task_id), "reason": "unsafe_url"})
            return
        # Unlike turn_complete's old channel guard, artifact rows post for
        # channel-less tasks too: every task has a thread panel.
        task = Task.objects.select_related("created_by").filter(id=run.task_id, team_id=run.team_id).first()
        if task is None:
            return
        if task.created_by is None or not _agent_thread_updates_enabled(task.created_by):
            logger.info(
                "pr_created thread update skipped",
                extra={"task_id": str(task.id), "reason": "no_creator" if task.created_by is None else "flag_off"},
            )
            return
        # The agent-output path and the webhook backstop can race on the same PR;
        # locking the task row makes the dedupe check-and-create atomic across them.
        with transaction.atomic():
            Task.objects.select_for_update().filter(id=task.id).first()
            if (
                TaskThreadMessage.objects.for_team(task.team_id)
                .filter(task_id=task.id, event="pr_created", payload__pr_url=pr_url)
                .exists()
            ):
                return
            label = _pr_display_label(pr_url)
            _create_agent_thread_message(
                task,
                f"[{label}]({pr_url}) has been opened",
                event="pr_created",
                payload={"pr_url": pr_url},
            )
    except Exception:
        logger.exception("Failed to post pr-created thread update", extra={"task_id": str(run.task_id)})
