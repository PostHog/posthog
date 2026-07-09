from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist

import posthoganalytics
from temporalio import activity

from posthog.models import Team
from posthog.temporal.common.utils import asyncify, close_db_connections

from products.tasks.backend.constants import (
    AGENT_PROXY_KEEP_STREAM_OPEN_FEATURE_FLAG,
    MODAL_DIRECTORY_RESUME_SNAPSHOTS_FEATURE_FLAG,
    MODAL_NETWORK_ALLOWLIST_FEATURE_FLAG,
    OVERLAP_CLONE_BOOT_FEATURE_FLAG,
    RTK_DISABLED_FEATURE_FLAG,
    SANDBOX_EVENT_INGEST_FEATURE_FLAG,
    vm_sandbox_allowed_origins,
)
from products.tasks.backend.exceptions import TaskInvalidStateError, TaskRunNotReadyError
from products.tasks.backend.logic.services.sandbox_config import (
    MAX_SANDBOX_CPU_CORES,
    MAX_SANDBOX_MEMORY_GB,
    MAX_SANDBOX_TTL_SECONDS,
)
from products.tasks.backend.models import SandboxCustomImage, SandboxEnvironment, Task, TaskRun
from products.tasks.backend.temporal.constants import resolve_inactivity_timeout
from products.tasks.backend.temporal.observability import emit_agent_log, log_with_activity_context
from products.tasks.backend.temporal.process_task.utils import (
    format_allowed_domains_for_log,
    get_pr_authorship_mode,
    resolve_user_github_integration_for_task,
)


@dataclass
class GetTaskProcessingContextInput:
    run_id: str
    create_pr: bool = True


@dataclass
class TaskProcessingContext:
    """
    Serializable context object passed to all activities in the task processing workflow.
    Contains all the information needed to execute activities and emit logs.
    """

    task_id: str
    run_id: str
    team_id: int
    team_uuid: str
    organization_id: str
    github_integration_id: int | None
    repository: str | None
    distinct_id: str
    origin_product: str | None = None
    environment: str | None = None
    github_user_integration_id: str | None = None
    task_created_by_id: int | None = None
    create_pr: bool = True
    pr_loop_enabled: bool = False
    state: dict | None = None
    _branch: str | None = None
    sandbox_environment_name: str | None = None
    allowed_domains: list[str] | None = None
    json_schema: dict | None = None
    ci_prompt: str | None = None
    # Captured at workflow start so snapshot creation is deterministic across
    # activity retries. This means "create any Modal resume snapshot"; filesystem
    # snapshots are guarded by the legacy setting, directory snapshots by feature flag.
    use_modal_resume_snapshots: bool = True
    use_modal_directory_resume_snapshots: bool = False
    # Captured at workflow start so the sandbox event transport branch is
    # deterministic for the full run.
    sandbox_event_ingest_enabled: bool = False
    use_modal_vm_sandbox: bool = False
    use_modal_network_allowlist: bool = False
    # Burstable by default; the per-run state can opt out to pin a fixed-size box
    # (request == limit). Captured at workflow start so it's stable across activity retries.
    burstable_sandbox_resources_enabled: bool = True
    overlap_clone_boot_enabled: bool = False
    # Captured at workflow start so the agent-proxy stream lifetime stays deterministic across retries.
    agent_proxy_keep_stream_open: bool = False
    # Set only when the run resolved to the VM runtime — custom images layer on the VM base.
    custom_image_name: str | None = None
    # rtk command-output compression is on by default (the sandbox image ships the binary).
    # The kill-switch flag wins over everything; otherwise a per-run state override
    # (the user's toggle) applies. Captured at workflow start so it's stable across retries.
    rtk_enabled: bool = True

    @property
    def mode(self) -> str:
        """Get the execution mode from state. Defaults to 'background'."""
        return (self.state or {}).get("mode", "background")

    @property
    def interaction_origin(self) -> str | None:
        return (self.state or {}).get("interaction_origin")

    @property
    def auto_publish(self) -> bool:
        """User-opted auto-publish: the agent pushes and opens a draft PR on completion."""
        return (self.state or {}).get("auto_publish") is True

    @property
    def has_github_credentials(self) -> bool:
        return self.github_integration_id is not None or self.github_user_integration_id is not None

    @property
    def sandbox_environment_id(self) -> str | None:
        return (self.state or {}).get("sandbox_environment_id")

    @property
    def runtime_adapter(self) -> str | None:
        value = (self.state or {}).get("runtime_adapter")
        return value if isinstance(value, str) else None

    @property
    def provider(self) -> str | None:
        value = (self.state or {}).get("provider")
        return value if isinstance(value, str) else None

    @property
    def model(self) -> str | None:
        value = (self.state or {}).get("model")
        return value if isinstance(value, str) else None

    @property
    def reasoning_effort(self) -> str | None:
        value = (self.state or {}).get("reasoning_effort")
        return value if isinstance(value, str) else None

    @property
    def run_source(self) -> str | None:
        value = (self.state or {}).get("run_source")
        return value if isinstance(value, str) else None

    @property
    def wizard_config(self) -> dict | None:
        """Config for the pre-agent setup-wizard step (set at task creation); None for normal runs."""
        value = (self.state or {}).get("wizard_config")
        return value if isinstance(value, dict) else None

    def inactivity_timeout(self) -> timedelta:
        """Idle time before the workflow times the run out; longer for user-driven runs."""
        is_user_origin = not self.origin_product or self.origin_product in (
            Task.OriginProduct.USER_CREATED.value,
            Task.OriginProduct.IMAGE_BUILDER.value,
        )
        return resolve_inactivity_timeout(is_user_origin=is_user_origin, state=self.state)

    def sandbox_resource_overrides(self) -> dict[str, float | int]:
        """Per-task SandboxConfig overrides (compute + TTL), clamped to server-owned bounds.
        `bool` is excluded explicitly — it's an `int` subclass and would slip through as 0/1."""
        overrides: dict[str, float | int] = {}
        state = self.state or {}
        for state_key, config_key, max_value in (
            ("sandbox_cpu_cores", "cpu_cores", MAX_SANDBOX_CPU_CORES),
            ("sandbox_memory_gb", "memory_gb", MAX_SANDBOX_MEMORY_GB),
        ):
            value = state.get(state_key)
            if isinstance(value, int | float) and not isinstance(value, bool) and value > 0:
                overrides[config_key] = float(min(value, max_value))
        ttl = state.get("sandbox_ttl_seconds")
        if isinstance(ttl, int | float) and not isinstance(ttl, bool) and ttl > 0:
            overrides["ttl_seconds"] = int(min(ttl, MAX_SANDBOX_TTL_SECONDS))
        return overrides

    def get_sandbox_environment(self):
        """Resolve the SandboxEnvironment, team-scoped and respecting privacy."""
        sandbox_environment_id = self.sandbox_environment_id
        if not sandbox_environment_id:
            return None
        return SandboxEnvironment.get_accessible_for_task(
            environment_id=sandbox_environment_id,
            team_id=self.team_id,
            task_created_by_id=self.task_created_by_id,
        )

    @property
    def branch(self) -> str | None:
        # Prefer the dedicated model field; fall back to state for backward compatibility
        if self._branch:
            return self._branch
        value = (self.state or {}).get("branch")
        return value if isinstance(value, str) else None

    def to_log_context(self) -> dict:
        """Return a dict suitable for structured logging."""
        return {
            "task_id": self.task_id,
            "run_id": self.run_id,
            "team_id": self.team_id,
            "repository": self.repository,
            "origin_product": self.origin_product,
            "environment": self.environment,
            "distinct_id": self.distinct_id,
            "mode": self.mode,
            "run_source": self.run_source,
            "sandbox_environment_id": self.sandbox_environment_id,
            "runtime_adapter": self.runtime_adapter,
            "provider": self.provider,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
        }


def _is_agent_proxy_keep_stream_open_enabled(
    *,
    distinct_id: str,
    organization_id: str,
    run_id: str,
    state: dict | None = None,
) -> bool:
    state_override = (state or {}).get("agent_proxy_keep_stream_open")
    if isinstance(state_override, bool):
        return state_override

    try:
        enabled = bool(
            posthoganalytics.feature_enabled(
                AGENT_PROXY_KEEP_STREAM_OPEN_FEATURE_FLAG,
                distinct_id=distinct_id,
                groups={"organization": organization_id},
                group_properties={"organization": {"id": organization_id}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception as e:
        log_with_activity_context("agent_proxy_keep_stream_open_flag_check_failed", run_id=run_id, error=str(e))
        return False

    log_with_activity_context(
        "agent_proxy_keep_stream_open_flag_checked",
        run_id=run_id,
        agent_proxy_keep_stream_open=enabled,
    )
    return enabled


def _is_rtk_enabled(
    *,
    distinct_id: str,
    organization_id: str,
    run_id: str,
    state: dict | None = None,
) -> bool:
    """rtk compression is on by default. The kill-switch flag wins over everything —
    a fleet-wide disable must not be pinned back on by a per-run override — and
    otherwise the per-run state override (the user's toggle in PostHog Code settings)
    applies. Fails open (enabled, override honored) on flag-service errors so the
    default posture is preserved."""
    try:
        disabled = bool(
            posthoganalytics.feature_enabled(
                RTK_DISABLED_FEATURE_FLAG,
                distinct_id=distinct_id,
                groups={"organization": organization_id},
                group_properties={"organization": {"id": organization_id}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception as e:
        log_with_activity_context("rtk_disabled_flag_check_failed", run_id=run_id, error=str(e))
        disabled = False

    if disabled:
        log_with_activity_context("rtk_disabled_flag_checked", run_id=run_id, rtk_enabled=False)
        return False

    state_override = (state or {}).get("rtk_enabled")
    if isinstance(state_override, bool):
        return state_override

    return True


def _is_sandbox_event_ingest_enabled(
    *,
    distinct_id: str,
    organization_id: str,
    run_id: str,
    state: dict | None = None,
) -> bool:
    # Local dev disables the analytics SDK, so the captured flag below is always False there.
    # Pointing ingest at the local agent-proxy is the opt-in and must win over the captured value;
    # prod (DEBUG off) still gates on the flag.
    if settings.DEBUG and settings.TASKS_AGENT_PROXY_INGEST_URL:
        return True

    state_override = (state or {}).get("sandbox_event_ingest_enabled")
    if isinstance(state_override, bool):
        log_with_activity_context(
            "sandbox_event_ingest_state_override",
            run_id=run_id,
            sandbox_event_ingest_enabled=state_override,
        )
        return state_override

    try:
        enabled = bool(
            posthoganalytics.feature_enabled(
                SANDBOX_EVENT_INGEST_FEATURE_FLAG,
                distinct_id=distinct_id,
                groups={"organization": organization_id},
                group_properties={"organization": {"id": organization_id}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception as e:
        log_with_activity_context("sandbox_event_ingest_flag_check_failed", run_id=run_id, error=str(e))
        return False

    log_with_activity_context(
        "sandbox_event_ingest_flag_checked",
        run_id=run_id,
        sandbox_event_ingest_enabled=enabled,
    )
    return enabled


def _is_modal_vm_sandbox_enabled(
    *,
    distinct_id: str,
    organization_id: str,
    run_id: str,
    origin_product: str | None,
    allowed_domains: list[str] | None,
    state: dict | None = None,
) -> bool:
    if allowed_domains is not None:
        log_with_activity_context(
            "modal_vm_sandbox_skipped_restricted_egress",
            run_id=run_id,
            use_modal_vm_sandbox=False,
        )
        return False

    state_override = (state or {}).get("use_modal_vm_sandbox")
    if isinstance(state_override, bool):
        log_with_activity_context(
            "modal_vm_sandbox_state_override",
            run_id=run_id,
            use_modal_vm_sandbox=state_override,
        )
        return state_override

    try:
        allowed_origins = vm_sandbox_allowed_origins(distinct_id=distinct_id, organization_id=organization_id)
    except Exception as e:
        log_with_activity_context("modal_vm_sandbox_flag_check_failed", run_id=run_id, error=str(e))
        return False

    result = origin_product in allowed_origins
    log_with_activity_context(
        "modal_vm_sandbox_flag_checked",
        run_id=run_id,
        flag_enabled=bool(allowed_origins),
        origin_product=origin_product,
        allowed_origin_products=sorted(allowed_origins),
        use_modal_vm_sandbox=result,
    )
    return result


def _is_burstable_sandbox_resources_enabled(
    *,
    run_id: str,
    state: dict | None = None,
) -> bool:
    # Burstable by default; the per-run state can pin a fixed-size box (request == limit).
    state_override = (state or {}).get("burstable_sandbox_resources_enabled")
    if isinstance(state_override, bool):
        log_with_activity_context(
            "burstable_sandbox_resources_state_override",
            run_id=run_id,
            burstable_sandbox_resources_enabled=state_override,
        )
        return state_override
    return True


def _is_overlap_clone_boot_enabled(
    *,
    distinct_id: str,
    organization_id: str,
    run_id: str,
    state: dict | None = None,
) -> bool:
    state_override = (state or {}).get("overlap_clone_boot_enabled")
    if isinstance(state_override, bool):
        log_with_activity_context(
            "overlap_clone_boot_state_override",
            run_id=run_id,
            overlap_clone_boot_enabled=state_override,
        )
        return state_override

    try:
        enabled = bool(
            posthoganalytics.feature_enabled(
                OVERLAP_CLONE_BOOT_FEATURE_FLAG,
                distinct_id=distinct_id,
                groups={"organization": organization_id},
                group_properties={"organization": {"id": organization_id}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception as e:
        log_with_activity_context("overlap_clone_boot_flag_check_failed", run_id=run_id, error=str(e))
        return False

    log_with_activity_context(
        "overlap_clone_boot_flag_checked",
        run_id=run_id,
        overlap_clone_boot_enabled=enabled,
    )
    return enabled


def _is_modal_network_allowlist_enabled(
    *,
    distinct_id: str,
    organization_id: str,
    run_id: str,
    state: dict | None = None,
) -> bool:
    state_override = (state or {}).get("use_modal_network_allowlist")
    if isinstance(state_override, bool):
        log_with_activity_context(
            "modal_network_allowlist_state_override",
            run_id=run_id,
            use_modal_network_allowlist=state_override,
        )
        return state_override

    try:
        enabled = bool(
            posthoganalytics.feature_enabled(
                MODAL_NETWORK_ALLOWLIST_FEATURE_FLAG,
                distinct_id=distinct_id,
                groups={"organization": organization_id},
                group_properties={"organization": {"id": organization_id}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception as e:
        log_with_activity_context("modal_network_allowlist_flag_check_failed", run_id=run_id, error=str(e))
        return False

    log_with_activity_context(
        "modal_network_allowlist_flag_checked",
        run_id=run_id,
        use_modal_network_allowlist=enabled,
    )
    return enabled


def _is_modal_directory_resume_snapshots_enabled(
    *,
    distinct_id: str,
    organization_id: str,
    run_id: str,
) -> bool:
    try:
        enabled = bool(
            posthoganalytics.feature_enabled(
                MODAL_DIRECTORY_RESUME_SNAPSHOTS_FEATURE_FLAG,
                distinct_id=distinct_id,
                groups={"organization": organization_id},
                group_properties={"organization": {"id": organization_id}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception as e:
        log_with_activity_context("modal_directory_resume_snapshots_flag_check_failed", run_id=run_id, error=str(e))
        return False

    log_with_activity_context(
        "modal_directory_resume_snapshots_flag_checked",
        run_id=run_id,
        use_modal_directory_resume_snapshots=enabled,
    )
    return enabled


@activity.defn
@asyncify
@close_db_connections
def get_task_processing_context(input: GetTaskProcessingContextInput) -> TaskProcessingContext:
    """Fetch task details and create the processing context for the workflow."""
    run_id = input.run_id
    log_with_activity_context("Fetching task processing context", run_id=run_id)

    try:
        task_run = TaskRun.objects.select_related(
            "task__created_by",
            "task__team",
            "task__github_integration",
            "task__github_user_integration",
        ).get(id=run_id)
    except ObjectDoesNotExist:
        # The row may simply not be visible yet (creating transaction not committed) or
        # be mid-cancel/delete. Retry rather than fail fatally so the transient window recovers.
        raise TaskRunNotReadyError(f"TaskRun {run_id} not found", {"run_id": run_id})

    emit_agent_log(run_id, "debug", "Fetching task details")

    task: Task = task_run.task
    team: Team = task.team
    organization_id = str(team.organization_id)
    if not task.created_by:
        raise TaskInvalidStateError(
            f"Task {task.id} has no created_by user",
            {"task_id": str(task.id), "run_id": run_id},
            cause=RuntimeError(f"Task {task.id} missing created_by field"),
        )

    assert task.created_by is not None

    distinct_id = task.created_by.distinct_id or "process_task_workflow"
    state = task_run.state or {}
    sandbox_environment_id = state.get("sandbox_environment_id")
    sandbox_environment_name: str | None = None
    allowed_domains: list[str] | None = None
    environment_custom_image_name: str | None = None

    if sandbox_environment_id:
        sandbox_environment = task_run.get_sandbox_environment()
        if sandbox_environment is None:
            raise TaskInvalidStateError(
                f"Sandbox environment {sandbox_environment_id} not accessible for team {task.team_id}",
                {"sandbox_environment_id": sandbox_environment_id, "team_id": task.team_id},
                cause=RuntimeError(
                    f"Sandbox environment {sandbox_environment_id} does not exist or is not accessible to the task creator"
                ),
            )
        else:
            sandbox_environment_name = sandbox_environment.name
            custom_image = sandbox_environment.custom_image
            if custom_image is not None:
                if not custom_image.is_accessible_to_user(task.created_by_id):
                    emit_agent_log(
                        run_id,
                        "warn",
                        f"Custom image '{custom_image.name}' is private to its creator; using the default base image",
                    )
                elif custom_image.is_ready:
                    environment_custom_image_name = custom_image.modal_image_name
                else:
                    emit_agent_log(
                        run_id,
                        "warn",
                        f"Custom image '{custom_image.name}' is not ready (status: {custom_image.status}); "
                        "using the default base image",
                    )
            if sandbox_environment.network_access_level == SandboxEnvironment.NetworkAccessLevel.FULL:
                allowed_domains = None
            else:
                allowed_domains = sandbox_environment.get_effective_domains()

            if allowed_domains is not None:
                emit_agent_log(
                    run_id,
                    "debug",
                    f"Resolved sandbox environment '{sandbox_environment.name}' with agentsh allowlist: {format_allowed_domains_for_log(allowed_domains)}",
                )
            else:
                emit_agent_log(
                    run_id,
                    "debug",
                    f"Resolved sandbox environment '{sandbox_environment.name}' with full network access",
                )

    # A per-run image (picked at task start) wins over the environment's image.
    state_custom_image_id = state.get("custom_image_id")
    if state_custom_image_id:
        state_custom_image = SandboxCustomImage.get_accessible_for_task(
            image_id=state_custom_image_id, team_id=task.team_id, task_created_by_id=task.created_by_id
        )
        if state_custom_image is not None and state_custom_image.is_ready:
            environment_custom_image_name = state_custom_image.modal_image_name
        else:
            emit_agent_log(
                run_id,
                "warn",
                f"Requested custom image {state_custom_image_id} is missing, not accessible, or not ready; "
                "falling back to the environment or default base image",
            )

    log_with_activity_context(
        "Task processing context created",
        task_id=str(task.id),
        run_id=run_id,
        team_id=task.team_id,
        repository=task.repository,
        origin_product=task.origin_product,
        environment=task_run.environment,
        distinct_id=distinct_id,
        sandbox_environment_id=sandbox_environment_id,
    )
    # Signals implementation PRs are bot-authored and always benefit from the PR
    # follow-up loop (fixing CI, replying to and resolving review threads), so they
    # opt in unconditionally — independent of the org-level `tasks-pr-loop` rollout
    # that gates other origins. This mirrors the babysitting the Slack coding bot
    # gets for its PRs.
    pr_loop_enabled = (
        task.origin_product == Task.OriginProduct.SIGNAL_REPORT
        or posthoganalytics.feature_enabled(
            "tasks-pr-loop",
            distinct_id=distinct_id,
            groups={"organization": organization_id},
            group_properties={"organization": {"id": organization_id}},
        )
        or False
    )  # Ensure we get a boolean value even if the flag is missing
    emit_agent_log(run_id, "debug", f"pr_loop_enabled: {pr_loop_enabled} for this task run")
    sandbox_event_ingest_enabled = _is_sandbox_event_ingest_enabled(
        distinct_id=distinct_id,
        organization_id=organization_id,
        run_id=run_id,
        state=state,
    )
    emit_agent_log(
        run_id,
        "debug",
        f"sandbox_event_ingest_enabled: {sandbox_event_ingest_enabled} for this task run",
    )
    use_modal_vm_sandbox = _is_modal_vm_sandbox_enabled(
        distinct_id=distinct_id,
        organization_id=organization_id,
        run_id=run_id,
        origin_product=task.origin_product,
        allowed_domains=allowed_domains,
        state=state,
    )
    emit_agent_log(
        run_id,
        "debug",
        f"use_modal_vm_sandbox: {use_modal_vm_sandbox} for this task run",
    )
    custom_image_name: str | None = None
    if environment_custom_image_name:
        if use_modal_vm_sandbox:
            custom_image_name = environment_custom_image_name
            emit_agent_log(run_id, "debug", f"Using custom base image: {custom_image_name}")
        else:
            emit_agent_log(
                run_id,
                "warn",
                "This environment's custom image requires the VM runtime, which is not enabled for this run; "
                "using the default base image",
            )
    use_modal_network_allowlist = _is_modal_network_allowlist_enabled(
        distinct_id=distinct_id,
        organization_id=organization_id,
        run_id=run_id,
        state=state,
    )
    emit_agent_log(
        run_id,
        "debug",
        f"use_modal_network_allowlist: {use_modal_network_allowlist} for this task run",
    )
    burstable_sandbox_resources_enabled = _is_burstable_sandbox_resources_enabled(
        run_id=run_id,
        state=state,
    )
    emit_agent_log(
        run_id,
        "debug",
        f"burstable_sandbox_resources_enabled: {burstable_sandbox_resources_enabled} for this task run",
    )
    overlap_clone_boot_enabled = _is_overlap_clone_boot_enabled(
        distinct_id=distinct_id,
        organization_id=organization_id,
        run_id=run_id,
        state=state,
    )
    emit_agent_log(
        run_id,
        "debug",
        f"overlap_clone_boot_enabled: {overlap_clone_boot_enabled} for this task run",
    )
    use_modal_directory_resume_snapshots = _is_modal_directory_resume_snapshots_enabled(
        distinct_id=distinct_id,
        organization_id=organization_id,
        run_id=run_id,
    )
    emit_agent_log(
        run_id,
        "debug",
        f"use_modal_directory_resume_snapshots: {use_modal_directory_resume_snapshots} for this task run",
    )
    agent_proxy_keep_stream_open = _is_agent_proxy_keep_stream_open_enabled(
        distinct_id=distinct_id,
        organization_id=organization_id,
        run_id=run_id,
        state=state,
    )
    emit_agent_log(
        run_id,
        "debug",
        f"agent_proxy_keep_stream_open: {agent_proxy_keep_stream_open} for this task run",
    )
    rtk_enabled = _is_rtk_enabled(
        distinct_id=distinct_id,
        organization_id=organization_id,
        run_id=run_id,
        state=state,
    )
    emit_agent_log(
        run_id,
        "debug",
        f"rtk_enabled: {rtk_enabled} for this task run",
    )
    user_github_integration_id = str(task.github_user_integration_id) if task.github_user_integration_id else None
    if user_github_integration_id is None and get_pr_authorship_mode(task, state).value == "user":
        user_github_integration = resolve_user_github_integration_for_task(task, allow_refresh=False)
        if user_github_integration is not None:
            user_github_integration_id = str(user_github_integration.integration.id)

    return TaskProcessingContext(
        task_id=str(task.id),
        run_id=run_id,
        team_id=task.team_id,
        team_uuid=str(task.team.uuid),
        organization_id=str(task.team.organization_id),
        github_integration_id=task.github_integration_id,
        github_user_integration_id=user_github_integration_id,
        repository=task.repository,
        distinct_id=distinct_id,
        origin_product=task.origin_product,
        environment=task_run.environment,
        task_created_by_id=task.created_by_id,
        create_pr=input.create_pr,
        pr_loop_enabled=pr_loop_enabled,
        state=state,
        _branch=task_run.branch,
        sandbox_environment_name=sandbox_environment_name,
        allowed_domains=allowed_domains,
        json_schema=task.json_schema,
        ci_prompt=task.ci_prompt,
        use_modal_resume_snapshots=settings.TASKS_USE_MODAL_RESUME_SNAPSHOTS or use_modal_directory_resume_snapshots,
        use_modal_directory_resume_snapshots=use_modal_directory_resume_snapshots,
        sandbox_event_ingest_enabled=sandbox_event_ingest_enabled,
        use_modal_vm_sandbox=use_modal_vm_sandbox,
        use_modal_network_allowlist=use_modal_network_allowlist,
        burstable_sandbox_resources_enabled=burstable_sandbox_resources_enabled,
        overlap_clone_boot_enabled=overlap_clone_boot_enabled,
        agent_proxy_keep_stream_open=agent_proxy_keep_stream_open,
        custom_image_name=custom_image_name,
        rtk_enabled=rtk_enabled,
    )
