import shlex
import asyncio
import logging
import threading
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.utils import timezone

import posthoganalytics
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.dataclasses import frozen
from posthog.models.user_integration import ReauthorizationRequired
from posthog.temporal.common.utils import asyncify

from products.context_layer.backend.facade import api as context_layer_facade
from products.tasks.backend.constants import (
    DEV_STACK_IMAGE_NAME,
    SNAPSHOT_KIND_FILESYSTEM,
    TASK_SIGNALS_CLONING_BLOBLESS_FEATURE_FLAG,
    filter_user_sandbox_env_vars,
)
from products.tasks.backend.exceptions import (
    ComputeBillingLimitError,
    CredentialUnavailableError,
    GitHubAuthenticationError,
    OAuthTokenError,
    RepositoryCloneError,
    SandboxNetworkPolicyError,
    TaskInvalidStateError,
    TaskNotFoundError,
)
from products.tasks.backend.logic.services.agentsh import (
    _get_debug_only_domains,
    _get_debug_only_ports,
    enforced_egress_domains,
)
from products.tasks.backend.logic.services.compute_quota import get_compute_quota_denial_reason
from products.tasks.backend.logic.services.connection_token import (
    SANDBOX_JWT_STATE_KID_KEY,
    get_primary_sandbox_jwt_kid,
    get_sandbox_jwt_public_key,
)
from products.tasks.backend.logic.services.network_policy import (
    EffectiveNetworkPolicy,
    NetworkPolicyValidationError,
    compile_network_policy,
)
from products.tasks.backend.logic.services.sandbox import (
    ExecutionResult,
    Sandbox,
    SandboxBase,
    SandboxConfig,
    SandboxTemplate,
    get_sandbox_class,
    sandbox_repo_path,
    workload_for_origin_product,
)
from products.tasks.backend.logic.services.sandbox_usage import (
    measure_sandbox_billed_cpu_usage,
    measure_sandbox_cpu_usage,
    open_sandbox_session,
)
from products.tasks.backend.models import TASK_OWNERSHIP_VERSION_STATE_KEY, SandboxSnapshot, Task, TaskRun
from products.tasks.backend.temporal.metrics import (
    StepTimer,
    increment_resume_mode,
    increment_snapshot_restore,
    increment_snapshot_usage,
    modal_sandbox_backend_label,
    record_network_enforcement,
    record_sandbox_created,
    resume_mode_label,
    sandbox_runtime_label,
)
from products.tasks.backend.temporal.oauth import create_oauth_access_token_for_run, create_wizard_oauth_access_token
from products.tasks.backend.temporal.observability import (
    emit_agent_log,
    log_activity_execution,
    log_with_activity_context,
)
from products.tasks.backend.temporal.process_task.sandbox_credentials import (
    replace_sandbox_credentials,
    set_git_remote_token,
)
from products.tasks.backend.temporal.process_task.utils import (
    get_git_identity_env_vars,
    get_readonly_github_token,
    get_sandbox_api_url,
    get_sandbox_github_token,
    get_sandbox_name_for_task,
    get_sandbox_otel_env_vars,
    get_sandbox_snapshot_metadata,
    get_task_run_credential_user,
    parse_run_state,
    run_gateway_env_vars,
)

from .get_task_processing_context import TaskProcessingContext

logger = logging.getLogger(__name__)
SANDBOX_CREATION_CANCELLATION_WAIT_SECONDS = 10
SANDBOX_CREATION_HEARTBEAT_SECONDS = 1

NETWORK_RESTRICTED_AGENT_ENV = {
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "DISABLE_TELEMETRY": "1",
    "DISABLE_ERROR_REPORTING": "1",
}


@dataclass
class PrepareSandboxForRepositoryInput:
    context: TaskProcessingContext


@dataclass
class PrepareSandboxForRepositoryOutput:
    sandbox_name: str
    repository: str | None
    github_token: str
    branch: str | None
    environment_variables: dict[str, str]
    snapshot_id: str | None
    snapshot_external_id: str | None
    used_snapshot: bool
    should_create_snapshot: bool
    shallow_clone: bool
    image_source: str
    image_source_label: str
    snapshot_kind: str = SNAPSHOT_KIND_FILESYSTEM
    snapshot_mount_path: str | None = None
    snapshot_source: str = "none"
    sandbox_creation_timeout_seconds: int = 300
    sandbox_creation_cancellable: bool = False


@dataclass
class CreateSandboxForRepositoryInput:
    context: TaskProcessingContext
    prepared: PrepareSandboxForRepositoryOutput


@frozen
class CreateSandboxForRepositoryOutput:
    sandbox_id: str
    sandbox_url: str
    connect_token: str | None
    used_snapshot: bool | None = None
    create_ms: int | None = None
    jwt_kid: str | None = None
    ttl_expires_at: str | None = None


@dataclass
class CloneRepositoryInSandboxOutput:
    clone_ms: int | None = None


@dataclass
class CheckoutBranchInSandboxOutput:
    checkout_ms: int | None = None


@dataclass
class CloneRepositoryInSandboxInput:
    context: TaskProcessingContext
    sandbox_id: str
    repository: str
    github_token: str
    shallow_clone: bool


@dataclass
class CheckoutBranchInSandboxInput:
    context: TaskProcessingContext
    sandbox_id: str
    repository: str
    branch: str
    github_token: str
    shallow_clone: bool
    used_snapshot: bool


def _prepare_posthog_desktop_cloud_task(ctx: TaskProcessingContext, sandbox: SandboxBase, repository: str) -> None:
    """Build Desktop workspace exports from the task's checked-out source.

    The dev-stack image warms pnpm's content-addressed store but deliberately does
    not retain checkout-specific node_modules or dist directories. Prepare only the
    internal PostHog checkout that uses that image, after its final branch is in place.
    """
    if (
        not ctx.desktop_workspace_warm_enabled
        or ctx.custom_image_name != DEV_STACK_IMAGE_NAME
        or repository.casefold() != "posthog/posthog"
        or sandbox.config.image_fallback
    ):
        return

    repo_path = f"{sandbox_repo_path(repository)}/products/desktop"
    emit_agent_log(ctx.run_id, "debug", "Preparing Desktop workspace dependencies")
    result = sandbox.execute(
        f"cd {shlex.quote(repo_path)} && pnpm bootstrap:cloud-task",
        timeout_seconds=10 * 60,
    )
    if result.exit_code != 0:
        output = (result.stderr or result.stdout)[-2_000:]
        raise ApplicationError(
            f"Failed to prepare Desktop workspace: {output}",
            type="DesktopCloudTaskBootstrapError",
            non_retryable=True,
        )


@dataclass
class InjectFreshTokensOnResumeInput:
    context: TaskProcessingContext
    sandbox_id: str
    repository: str | None


@frozen
class RestoreSandboxConnectionStateInput:
    run_id: str
    sandbox_id: str
    sandbox_url: str
    connect_token: str | None
    jwt_kid: str | None = None


@dataclass
class InvalidateResumeSnapshotInput:
    run_id: str
    snapshot_external_id: str | None = None


def _compile_sandbox_network_policy(allowed_domains: list[str]) -> EffectiveNetworkPolicy:
    return compile_network_policy(
        allowed_domains,
        infrastructure_domains=enforced_egress_domains(),
        debug_domains=_get_debug_only_domains() if settings.DEBUG else [],
        debug_ports=_get_debug_only_ports() if settings.DEBUG else [],
    )


def _to_modal_domain_allowlist(allowed_domains: list[str]) -> list[str]:
    return list(_compile_sandbox_network_policy(allowed_domains).modal_domains)


def _apply_modal_network_policy(
    config: SandboxConfig,
    ctx: TaskProcessingContext,
    *,
    use_vm_sandbox: bool,
) -> None:
    if ctx.allowed_domains is None:
        return
    if use_vm_sandbox and not ctx.use_modal_network_allowlist:
        record_network_enforcement("configuration_validation", "vm", "modal", "failure")
        raise SandboxNetworkPolicyError(
            "A restricted sandbox cannot start on the VM runtime without Modal network enforcement.",
            {"run_id": ctx.run_id, "network_policy_fingerprint": ctx.network_policy_fingerprint},
            cause=RuntimeError("restricted VM network interlock failed"),
        )
    if not ctx.use_modal_network_allowlist:
        return
    if ctx.modal_domain_allowlist is None or ctx.network_policy_fingerprint is None:
        try:
            policy = _compile_sandbox_network_policy(ctx.allowed_domains)
        except NetworkPolicyValidationError as error:
            record_network_enforcement(
                "configuration_validation", sandbox_runtime_label(use_vm_sandbox), "modal", "failure"
            )
            raise SandboxNetworkPolicyError(
                "This sandbox environment has no valid Modal network policy. Update its network settings and run the task again.",
                {"run_id": ctx.run_id, "sandbox_environment_id": ctx.sandbox_environment_id},
                cause=error,
            ) from error
        config.outbound_domain_allowlist = list(policy.modal_domains)
        config.network_policy_fingerprint = policy.fingerprint
        return
    config.outbound_domain_allowlist = list(ctx.modal_domain_allowlist)
    config.network_policy_fingerprint = ctx.network_policy_fingerprint


def _is_blobless_signals_clone_enabled(ctx: TaskProcessingContext) -> bool:
    if ctx.origin_product != Task.OriginProduct.SIGNAL_REPORT:
        return False

    try:
        return bool(
            posthoganalytics.feature_enabled(
                TASK_SIGNALS_CLONING_BLOBLESS_FEATURE_FLAG,
                distinct_id=ctx.distinct_id,
                groups={"organization": ctx.organization_id},
                group_properties={"organization": {"id": ctx.organization_id}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception as error:
        log_with_activity_context(
            "blobless_signals_clone_flag_check_failed",
            run_id=ctx.run_id,
            error=str(error),
        )
        return False


def _resolve_sandbox_github_token(
    ctx: TaskProcessingContext,
    *,
    task: Task,
    actor_user: Any,
    repository: str | None,
    has_repo: bool,
) -> str:
    """Decide which GitHub credential (if any) a fresh sandbox gets.

    A repo-less run that requested read-only access is resolved FIRST: _build_task attaches the
    team's GitHub integration to every task, so has_github_credentials is true whenever the team
    has GitHub connected at all — resolved the other way around, the write-capable installation
    token would reach a run that asked for read-only. The read-only mint is best-effort (empty
    string on failure, never the full token); the full credential path keeps its raise-on-failure
    contract for repo-backed runs that can't work without credentials.
    """
    if ctx.github_read_access and not has_repo:
        github_token = get_readonly_github_token(ctx.team_id) or ""
        emit_agent_log(
            ctx.run_id,
            "debug",
            "Read-only GitHub token minted for evidence gathering"
            if github_token
            else "Read-only GitHub token unavailable, continuing without GitHub access",
        )
        return github_token

    if not has_repo and task.origin_product in (Task.OriginProduct.SIGNALS_CHAT, Task.OriginProduct.SIGNAL_REPORT):
        return ""

    should_inject_github_token = ctx.has_github_credentials and (
        has_repo or ctx.github_user_integration_id is not None or ctx.github_integration_id is not None
    )
    if not should_inject_github_token:
        return ""
    try:
        return (
            get_sandbox_github_token(
                ctx.github_integration_id,
                run_id=ctx.run_id,
                state=ctx.state,
                task=task,
                actor_user=actor_user,
                github_user_integration_id=ctx.github_user_integration_id,
                repository=repository,
            )
            or ""
        )
    except ReauthorizationRequired as e:
        # Expected user-actionable state — the acting user must re-link GitHub. Non-retryable and
        # kept out of the raw error stream (CredentialUnavailableError does not capture) so it does
        # not surface as error-tracking noise. Mirrors the refresh path in sandbox_credentials.py.
        raise CredentialUnavailableError(
            "GitHub user integration for this run requires reauthorization",
            {"github_integration_id": ctx.github_integration_id, "task_id": ctx.task_id},
            cause=e,
        )
    except Exception as e:
        raise GitHubAuthenticationError(
            f"Failed to get GitHub token for integration {ctx.github_integration_id}",
            {"github_integration_id": ctx.github_integration_id, "task_id": ctx.task_id, "error": str(e)},
            cause=e,
        )


def _load_task(ctx: TaskProcessingContext) -> Task:
    try:
        task = Task.objects.select_related(
            "created_by", "github_integration", "github_user_integration", "team", "loop"
        ).get(id=ctx.task_id)
    except Task.DoesNotExist as e:
        raise TaskNotFoundError(f"Task {ctx.task_id} not found", {"task_id": ctx.task_id}, cause=e)
    context_ownership_version = (ctx.state or {}).get(TASK_OWNERSHIP_VERSION_STATE_KEY)
    if context_ownership_version != task.ownership_version:
        raise TaskInvalidStateError(
            f"TaskRun {ctx.run_id} belongs to a previous task owner",
            {"task_id": ctx.task_id, "run_id": ctx.run_id},
            cause=RuntimeError(f"TaskRun {ctx.run_id} ownership version is stale"),
        )
    return task


def _get_image_source_label(
    *,
    has_repo: bool,
    provider: str | None,
    resume_snapshot_external_id: str | None,
    snapshot: SandboxSnapshot | None,
    custom_image_name: str | None = None,
) -> tuple[str, str]:
    if resume_snapshot_external_id:
        return "resume_snapshot", f"resume snapshot {resume_snapshot_external_id}"

    if snapshot is not None:
        external_id = snapshot.external_id or str(snapshot.id)
        return "repository_snapshot", f"repository snapshot {external_id}"

    if custom_image_name:
        return "custom_image", f"custom base image {custom_image_name}"

    if provider == "docker":
        return "docker_base_image", "local Docker sandbox image"

    if provider and provider.upper() in ("MODAL_DOCKER", "MODAL_EVALS"):
        return "modal_local_build", "local Modal Dockerfile build"

    if settings.DEBUG and not has_repo:
        return "local_debug_build", "local debug sandbox image"

    return "base_image", "published sandbox base image"


def get_fresh_image_source_for_context(ctx: TaskProcessingContext) -> tuple[str, str]:
    """Image source and label for a sandbox provisioned fresh (no snapshot) from this context."""
    return _get_image_source_label(
        has_repo=ctx.repository is not None,
        provider=getattr(settings, "SANDBOX_PROVIDER", None),
        resume_snapshot_external_id=None,
        snapshot=None,
        custom_image_name=ctx.custom_image_name if ctx.use_modal_vm_sandbox else None,
    )


def _sandbox_image_kind(image_source: str, custom_image_name: str | None) -> str:
    if image_source == "resume_snapshot":
        return "resume_snapshot"
    if image_source == "repository_snapshot":
        return "repository_snapshot"
    if custom_image_name == DEV_STACK_IMAGE_NAME:
        return "dev_stack"
    if custom_image_name:
        return "custom"
    return "base"


def _build_environment_variables(
    ctx: TaskProcessingContext, task: Task, github_token: str, access_token: str
) -> dict[str, str]:
    environment_variables = {
        "POSTHOG_PERSONAL_API_KEY": access_token,
        "POSTHOG_API_URL": get_sandbox_api_url(),
        "POSTHOG_PROJECT_ID": str(ctx.team_id),
        "POSTHOG_TASK_ID": str(ctx.task_id),
        "POSTHOG_TASK_RUN_ID": str(ctx.run_id),
        "JWT_PUBLIC_KEY": get_sandbox_jwt_public_key(),
    }

    sandbox_environment = None
    if ctx.sandbox_environment_id:
        sandbox_environment = ctx.get_sandbox_environment()
        if sandbox_environment and sandbox_environment.environment_variables:
            safe_vars, skipped_keys = filter_user_sandbox_env_vars(sandbox_environment.environment_variables)
            environment_variables.update(safe_vars)

            emit_agent_log(
                ctx.run_id,
                "debug",
                f"Applied {len(safe_vars)} sandbox environment variable(s) from '{sandbox_environment.name}'",
            )
            if skipped_keys:
                emit_agent_log(
                    ctx.run_id,
                    "debug",
                    f"Skipped reserved/blocked sandbox environment variable keys from '{sandbox_environment.name}': {', '.join(sorted(skipped_keys))}",
                )

    if github_token:
        environment_variables["GITHUB_TOKEN"] = github_token
        environment_variables["GH_TOKEN"] = github_token

    # BASH_ENV is intentionally NOT set in the container env: it's applied only to the
    # agent-server launch (see the sandbox services) so backend maintenance execs don't source
    # a script that a resume snapshot could control. It's blocked (constants.py) so a
    # user-supplied env var can't add it here.

    if settings.SANDBOX_LLM_GATEWAY_URL:
        environment_variables["LLM_GATEWAY_URL"] = settings.SANDBOX_LLM_GATEWAY_URL

    environment_variables.update(run_gateway_env_vars(ctx, task))

    if settings.DEBUG:
        # Local eval runs pin models per unit; the agent's overload rescue would silently switch a
        # session to the fallback model mid-run, breaking prompt-cache sharing (model is part of
        # the cache key) and cost attribution. Rely on Temporal retries instead.
        environment_variables["POSTHOG_DISABLE_MODEL_FALLBACK"] = "1"

    if ctx.agent_otel_telemetry_enabled:
        environment_variables.update(get_sandbox_otel_env_vars())

    if ctx.allowed_domains is not None:
        environment_variables.update(NETWORK_RESTRICTED_AGENT_ENV)

    environment_variables.update(get_git_identity_env_vars(task, ctx.state))

    run_state = parse_run_state(ctx.state)
    if run_state.resume_from_run_id:
        environment_variables["POSTHOG_RESUME_RUN_ID"] = run_state.resume_from_run_id
    elif run_state.handoff_resumed:
        environment_variables["POSTHOG_RESUME_RUN_ID"] = str(ctx.run_id)
        if run_state.handoff_resume_idle:
            environment_variables["POSTHOG_RESUME_IDLE"] = "1"

    # Cloud wizard runs get a SEPARATE token, minted under the wizard's own OAuth app with the
    # wizard's scopes, so the wizard's access stays independent of the agent's sandbox token above.
    # The run_wizard activity reads it from POSTHOG_WIZARD_API_KEY in the sandbox env.
    if ctx.wizard_config is not None:
        environment_variables["POSTHOG_WIZARD_API_KEY"] = create_wizard_oauth_access_token(task)

    # The flag was evaluated once in get_task_processing_context; presence of
    # the mount-path env var is what gates the materialize activity in the workflow.
    if ctx.context_layer_enabled:
        environment_variables.update(
            context_layer_facade.sandbox_environment_variables(ctx.organization_id, ctx.team_id)
        )

    return environment_variables


def _emit_image_source_log(ctx: TaskProcessingContext, prepared: PrepareSandboxForRepositoryOutput) -> None:
    if prepared.image_source == "resume_snapshot":
        emit_agent_log(ctx.run_id, "debug", f"Resuming environment from snapshot for {prepared.repository}")
    elif prepared.image_source == "repository_snapshot":
        emit_agent_log(ctx.run_id, "debug", f"Found existing environment for {prepared.repository}")
    elif prepared.repository:
        emit_agent_log(
            ctx.run_id, "debug", f"Creating environment from {prepared.image_source_label} for {prepared.repository}"
        )
    else:
        emit_agent_log(ctx.run_id, "debug", f"Creating environment from {prepared.image_source_label}")


def _build_sandbox_tags(
    ctx: TaskProcessingContext,
    prepared: PrepareSandboxForRepositoryOutput,
    use_vm_sandbox: bool,
) -> dict[str, str]:
    """Tags forwarded to the Modal sandbox so it can be traced back when debugging.

    Modal tag values must be strings; None values are dropped so we don't emit empty tags.
    """
    tags: dict[str, str | int | None] = {
        "task_id": ctx.task_id,
        "task_run_id": ctx.run_id,
        "origin_product": ctx.origin_product,
        "team_id": ctx.team_id,
        # The running workflow's real id — a re-derived default would mislabel prefixed dispatches.
        "workflow_id": activity.info().workflow_id,
        "image_source": prepared.image_source,
        "sandbox_runtime": "vm" if use_vm_sandbox else "gvisor",
    }
    return {key: str(value) for key, value in tags.items() if value is not None}


@activity.defn
@asyncify
def prepare_sandbox_for_repository(input: PrepareSandboxForRepositoryInput) -> PrepareSandboxForRepositoryOutput:
    ctx = input.context

    with log_activity_execution(
        "prepare_sandbox_for_repository",
        **ctx.to_log_context(),
    ):
        has_repo = bool(ctx.repositories)
        repository = ctx.repository

        snapshot = None
        used_snapshot = False
        snapshot_source = "none"
        snapshot_kind = SNAPSHOT_KIND_FILESYSTEM
        snapshot_mount_path: str | None = None
        # Repo-setup snapshots come from default-base sandboxes; restoring one would silently
        # drop the custom base image. Resume snapshots were taken from this task's own sandbox.
        if has_repo and ctx.github_integration_id is not None and not ctx.custom_image_name:
            with StepTimer(
                "snapshot_lookup",
                origin_product=ctx.origin_product,
                runtime=sandbox_runtime_label(ctx.use_modal_vm_sandbox),
            ) as snapshot_lookup_timer:
                snapshot = SandboxSnapshot.get_latest_snapshot_with_repos(ctx.github_integration_id, ctx.repositories)
                used_snapshot = snapshot is not None
                snapshot_lookup_timer.set_used_snapshot(used_snapshot)
            if snapshot is not None:
                snapshot_metadata = get_sandbox_snapshot_metadata(snapshot)
                if not snapshot_metadata.is_usable:
                    snapshot = None
                    used_snapshot = False
                else:
                    snapshot_source = "repository"
                    snapshot_kind = snapshot_metadata.kind
                    snapshot_mount_path = snapshot_metadata.mount_path
        elif not has_repo:
            emit_agent_log(ctx.run_id, "debug", "Creating environment without repository")

        task = _load_task(ctx)
        shallow_clone = task.origin_product != Task.OriginProduct.SIGNAL_REPORT

        actor_user = get_task_run_credential_user(task, ctx.state)
        credential_repository = repository or (ctx.repositories[0] if ctx.repositories else None)
        github_token = _resolve_sandbox_github_token(
            ctx, task=task, actor_user=actor_user, repository=credential_repository, has_repo=has_repo
        )

        try:
            access_token = create_oauth_access_token_for_run(task, ctx.state)
        except Exception as e:
            raise OAuthTokenError(
                f"Failed to create OAuth access token for task {ctx.task_id}",
                {"task_id": ctx.task_id, "error": str(e)},
                cause=e,
            )

        environment_variables = _build_environment_variables(ctx, task, github_token, access_token)

        run_state = parse_run_state(ctx.state)
        # VM and gVisor both resume from snapshots. A run's stored snapshot kind
        # determines the restore mechanism; the rollout flag only chooses the
        # kind of new snapshot created after this run.
        resume_snapshot_external_id = run_state.snapshot_external_id
        if resume_snapshot_external_id:
            if not run_state.resume_snapshot_is_usable():
                emit_agent_log(
                    ctx.run_id,
                    "debug",
                    "Previous session snapshot is unusable; resuming with a fresh sandbox",
                )
                resume_snapshot_external_id = None
            else:
                used_snapshot = True
                snapshot_source = "resume"
                snapshot_kind = run_state.resume_snapshot_kind()
                snapshot_mount_path = run_state.resume_snapshot_mount_path()

        is_resume = bool(run_state.handoff_resumed or run_state.resume_from_run_id)
        resume_mode = resume_mode_label(
            handoff_resumed=run_state.handoff_resumed,
            using_modal_snapshot=resume_snapshot_external_id is not None,
        )
        resume_decision_log = (
            activity.logger.warning if is_resume and resume_mode == "neither" else activity.logger.info
        )
        resume_decision_log(
            "resume_decision",
            extra={
                "run_id": ctx.run_id,
                "resume_mode": resume_mode,
                "state_snapshot_external_id": run_state.snapshot_external_id,
                "state_snapshot_kind": run_state.snapshot_kind,
                "effective_snapshot_external_id": resume_snapshot_external_id,
                "effective_snapshot_kind": snapshot_kind,
                "effective_snapshot_mount_path": snapshot_mount_path,
                "handoff_resumed": run_state.handoff_resumed,
                "handoff_resume_idle": run_state.handoff_resume_idle,
                "resume_from_run_id": run_state.resume_from_run_id,
                "posthog_resume_run_id_set": "POSTHOG_RESUME_RUN_ID" in environment_variables,
                "used_snapshot": used_snapshot,
            },
        )
        if is_resume:
            emit_agent_log(
                ctx.run_id,
                "debug",
                f"Resume mode: handoff_resumed={run_state.handoff_resumed}, "
                f"resume_idle={run_state.handoff_resume_idle}, "
                f"resume_from_run_id={run_state.resume_from_run_id}, "
                f"using_modal_snapshot={resume_snapshot_external_id is not None}",
            )
            increment_resume_mode(resume_mode, origin_product=ctx.origin_product)

        provider = getattr(settings, "SANDBOX_PROVIDER", None)
        image_source, image_source_label = _get_image_source_label(
            has_repo=has_repo,
            provider=provider,
            resume_snapshot_external_id=resume_snapshot_external_id,
            snapshot=snapshot if not resume_snapshot_external_id else None,
            custom_image_name=ctx.custom_image_name if ctx.use_modal_vm_sandbox else None,
        )

        sandbox_class = get_sandbox_class()
        return PrepareSandboxForRepositoryOutput(
            sandbox_name=get_sandbox_name_for_task(ctx.task_id),
            repository=repository,
            github_token=github_token,
            branch=ctx.branch,
            environment_variables=environment_variables,
            snapshot_id=str(snapshot.id) if snapshot and not resume_snapshot_external_id else None,
            snapshot_external_id=resume_snapshot_external_id,
            used_snapshot=used_snapshot,
            should_create_snapshot=not used_snapshot,
            shallow_clone=shallow_clone,
            image_source=image_source,
            image_source_label=image_source_label,
            snapshot_kind=snapshot_kind,
            snapshot_mount_path=snapshot_mount_path,
            snapshot_source=snapshot_source,
            sandbox_creation_timeout_seconds=sandbox_class.creation_timeout_seconds,
            sandbox_creation_cancellable=sandbox_class.supports_creation_cancellation,
        )


@asyncify
def _create_sandbox_for_repository(input: CreateSandboxForRepositoryInput) -> CreateSandboxForRepositoryOutput:
    ctx = input.context
    prepared = input.prepared

    with log_activity_execution(
        "create_sandbox_for_repository",
        image_source=prepared.image_source,
        **ctx.to_log_context(),
    ):
        if not (ctx.state or {}).get("await_user_message"):
            task = _load_task(ctx)
            if reason := get_compute_quota_denial_reason(task):
                raise ComputeBillingLimitError(
                    {"team_id": ctx.team_id, "task_id": ctx.task_id, "run_id": ctx.run_id}, reason
                )
        _emit_image_source_log(ctx, prepared)
        emit_agent_log(
            ctx.run_id,
            "debug",
            f"Provisioning sandbox from {prepared.image_source_label} (image build may take a few minutes on first run)",
        )

        # The VM template bakes in Docker (and forces the VM runtime), so the agent
        # can run nested containers; the default template has neither.
        use_vm_sandbox = ctx.use_modal_vm_sandbox
        config = SandboxConfig(
            name=prepared.sandbox_name,
            template=SandboxTemplate.VM_BASE if use_vm_sandbox else SandboxTemplate.DEFAULT_BASE,
            workload=workload_for_origin_product(ctx.origin_product),
            custom_image_name=ctx.custom_image_name if use_vm_sandbox else None,
            environment_variables=prepared.environment_variables,
            snapshot_id=prepared.snapshot_id,
            snapshot_external_id=prepared.snapshot_external_id,
            snapshot_kind=prepared.snapshot_kind,
            snapshot_mount_path=prepared.snapshot_mount_path,
            snapshot_source=prepared.snapshot_source,
            metadata=_build_sandbox_tags(ctx, prepared, use_vm_sandbox),
            vm_runtime=use_vm_sandbox,
            **ctx.sandbox_resource_overrides(),
        )

        # Request a small slice and let the box burst up to the configured size. Burstable by
        # default, but the per-run state can opt out to pin a fixed-size box (request == limit).
        # The decision is captured once in the context at workflow start, so it's stable across
        # activity retries.
        if ctx.burstable_sandbox_resources_enabled:
            config.burstable_resources = True
            emit_agent_log(
                ctx.run_id,
                "debug",
                f"Burstable resources enabled: requesting {config.effective_cpu_request_cores} CPU / "
                f"{config.effective_memory_request_mb} MiB, bursting up to {config.cpu_cores} CPU / "
                f"{int(config.memory_gb * 1024)} MiB",
            )

        runtime = sandbox_runtime_label(use_vm_sandbox)
        sandbox_backend = modal_sandbox_backend_label()
        _apply_modal_network_policy(config, ctx, use_vm_sandbox=use_vm_sandbox)
        if config.outbound_domain_allowlist is not None:
            emit_agent_log(
                ctx.run_id,
                "debug",
                f"Requesting Modal network enforcement for {len(config.outbound_domain_allowlist)} domains",
            )

        try:
            with StepTimer(
                "sandbox_creation",
                used_snapshot=prepared.used_snapshot,
                origin_product=ctx.origin_product,
                runtime=runtime,
                sandbox_backend=sandbox_backend,
            ) as sandbox_creation_timer:
                sandbox = Sandbox.create(config)
                # The provider's TTL clock starts here — the usage ledger anchors its
                # kill deadline on this boundary, not on when the row is opened below.
                sandbox_created_at = timezone.now()
                actual_used_snapshot = bool(
                    (prepared.snapshot_external_id or prepared.snapshot_id) and sandbox.config.snapshot_restored
                )
                sandbox_creation_timer.set_used_snapshot(actual_used_snapshot)
        except Exception:
            if config.outbound_domain_allowlist is not None:
                record_network_enforcement(
                    "sandbox_creation_with_policy_request", runtime, "modal_requested", "failure"
                )
            raise
        if config.outbound_domain_allowlist is not None:
            emit_agent_log(ctx.run_id, "debug", "Modal sandbox created with network policy requested")
            record_network_enforcement("sandbox_creation_with_policy_request", runtime, "modal_requested", "success")
        if not sandbox.start_cpu_billing_sampler():
            activity.logger.warning("Failed to start sandbox CPU billing sampler", extra={"sandbox_id": sandbox.id})
        if sandbox.config.image_fallback:
            emit_agent_log(
                ctx.run_id,
                "warn",
                f"Sandbox image downgraded: {sandbox.config.image_fallback}",
            )
        if sandbox.launch_dev_stack_bootstrap():
            emit_agent_log(
                ctx.run_id,
                "debug",
                "Warming the prebaked dev stack in the background (compose host aliases + dockerd)",
            )
        create_ms = sandbox_creation_timer.elapsed_ms
        snapshot_outcome = (
            "used" if actual_used_snapshot else "fresh" if prepared.snapshot_source == "none" else "fallback"
        )
        metrics_snapshot_kind = prepared.snapshot_kind if prepared.snapshot_source != "none" else "none"
        increment_snapshot_usage(
            actual_used_snapshot,
            snapshot_source=prepared.snapshot_source,
            snapshot_kind=metrics_snapshot_kind,
        )
        increment_snapshot_restore(prepared.snapshot_source, metrics_snapshot_kind, snapshot_outcome)

        record_sandbox_created(
            runtime,
            _sandbox_image_kind(prepared.image_source, config.custom_image_name),
            sandbox.config.image_fallback is not None,
            create_ms,
            sandbox_backend=sandbox_backend,
        )

        credentials = sandbox.get_connect_credentials()

        try:
            jwt_kid = get_primary_sandbox_jwt_kid()
            sandbox_state = {
                "sandbox_id": sandbox.id,
                "sandbox_url": credentials.url,
                SANDBOX_JWT_STATE_KID_KEY: jwt_kid,
            }
            if credentials.token:
                sandbox_state["sandbox_connect_token"] = credentials.token
            TaskRun.update_state_atomic(ctx.run_id, updates=sandbox_state)
            cpu_usage_attribution_usec, cpu_usage_attribution_measured_at = measure_sandbox_cpu_usage(sandbox)
            billed_cpu_usage_attribution_usec = measure_sandbox_billed_cpu_usage(sandbox)
            open_sandbox_session(
                run_id=ctx.run_id,
                sandbox_id=sandbox.id,
                config=sandbox.config,
                sandbox_created_at=sandbox_created_at,
                cpu_usage_attribution_usec=cpu_usage_attribution_usec,
                billed_cpu_usage_attribution_usec=billed_cpu_usage_attribution_usec,
                cpu_usage_attribution_measured_at=cpu_usage_attribution_measured_at,
                required=ctx.task_runtime == "pi",
            )
        except Exception:
            try:
                sandbox.destroy()
            finally:
                TaskRun.clear_sandbox_connection_state_atomic(ctx.run_id, sandbox.id)
            raise

        emit_agent_log(ctx.run_id, "debug", f"Sandbox provisioned: {sandbox.id}")
        activity.logger.info(f"Created sandbox {sandbox.id} (used_snapshot={actual_used_snapshot})")

        return CreateSandboxForRepositoryOutput(
            sandbox_id=sandbox.id,
            sandbox_url=credentials.url,
            connect_token=credentials.token,
            used_snapshot=actual_used_snapshot,
            create_ms=create_ms,
            ttl_expires_at=(sandbox_created_at + timedelta(seconds=sandbox.config.ttl_seconds)).isoformat(),
            jwt_kid=jwt_kid,
        )


@activity.defn
async def create_sandbox_for_repository(input: CreateSandboxForRepositoryInput) -> CreateSandboxForRepositoryOutput:
    sandbox_class = get_sandbox_class()
    if not sandbox_class.supports_creation_cancellation:
        return await _create_sandbox_for_repository(input)

    cancel_event = threading.Event()
    creation_after_cancellation: CreateSandboxForRepositoryOutput | None = None
    cancellation: asyncio.CancelledError | None = None

    with sandbox_class.creation_cancellation_scope(cancel_event):
        creation_task = asyncio.create_task(_create_sandbox_for_repository(input))
        try:
            while True:
                activity.heartbeat()
                try:
                    return await asyncio.wait_for(
                        asyncio.shield(creation_task), timeout=SANDBOX_CREATION_HEARTBEAT_SECONDS
                    )
                except TimeoutError:
                    continue
        except asyncio.CancelledError as error:
            cancellation = error
            cancel_event.set()
            # sync_to_async cannot stop its worker thread, so wait for the provider operation
            # to exit before Temporal can retry this activity against the same sandbox name.
            try:
                creation_after_cancellation = await asyncio.wait_for(
                    asyncio.shield(creation_task), timeout=SANDBOX_CREATION_CANCELLATION_WAIT_SECONDS
                )
            except TimeoutError:
                logger.exception(
                    "sandbox_creation_cancellation_wait_timed_out",
                    extra={"run_id": input.context.run_id},
                )
            except Exception as error:
                logger.debug(
                    "sandbox_creation_stopped_after_cancellation",
                    extra={"run_id": input.context.run_id, "error_type": type(error).__name__},
                )

    if creation_after_cancellation is not None:
        sandbox = await asyncio.to_thread(Sandbox.get_by_id, creation_after_cancellation.sandbox_id)
        try:
            await asyncio.to_thread(sandbox.destroy)
        finally:
            await asyncio.to_thread(
                TaskRun.clear_sandbox_connection_state_atomic,
                input.context.run_id,
                creation_after_cancellation.sandbox_id,
            )

    assert cancellation is not None
    raise cancellation


@activity.defn
@asyncify
def clone_repository_in_sandbox(input: CloneRepositoryInSandboxInput) -> CloneRepositoryInSandboxOutput:
    ctx = input.context
    blobless_clone = _is_blobless_signals_clone_enabled(ctx)

    with log_activity_execution(
        "clone_repository_in_sandbox",
        sandbox_id=input.sandbox_id,
        blobless_clone=blobless_clone,
        **ctx.to_log_context(),
    ):
        emit_agent_log(ctx.run_id, "debug", f"Cloning {input.repository} into sandbox")
        sandbox = Sandbox.get_by_id(input.sandbox_id)

        state = ctx.state or {}
        is_resume = bool(state.get("resume_from_run_id") or state.get("handoff_resumed"))

        with StepTimer(
            "repository_clone",
            used_snapshot=False,
            origin_product=ctx.origin_product,
            runtime=sandbox_runtime_label(ctx.use_modal_vm_sandbox),
        ) as clone_timer:
            clone_result = sandbox.clone_repository(
                input.repository,
                github_token=input.github_token,
                shallow=input.shallow_clone,
                branch=ctx.branch if is_resume else None,
                blobless=blobless_clone,
            )

            if is_resume and ctx.branch and _is_missing_remote_branch_clone_error(clone_result):
                emit_agent_log(
                    ctx.run_id,
                    "debug",
                    f"Resume branch {ctx.branch} is unavailable; cloning the repository default branch so the agent can restore its git checkpoint",
                )
                clone_result = sandbox.clone_repository(
                    input.repository,
                    github_token=input.github_token,
                    shallow=input.shallow_clone,
                    branch=None,
                    blobless=blobless_clone,
                )

            if clone_result.exit_code != 0:
                error_output = clone_result.stderr or clone_result.stdout or clone_result.error or "No output captured"
                raise RepositoryCloneError(
                    f"Git clone failed with exit code {clone_result.exit_code}",
                    {
                        "repository": input.repository,
                        "sandbox_id": input.sandbox_id,
                        "exit_code": clone_result.exit_code,
                        "stderr": clone_result.stderr[:500],
                        "stdout": clone_result.stdout[:500],
                        "error": clone_result.error,
                    },
                    cause=RuntimeError(error_output[:200]),
                )

        # A fresh single-repository run checks its requested branch out in the next
        # activity. Resumes clone that branch directly, and multi-repo runs do not run
        # the checkout activity, so prepare them here once their final source exists.
        will_checkout_later = len(ctx.repositories) == 1 and bool(ctx.branch) and not is_resume
        if not will_checkout_later:
            _prepare_posthog_desktop_cloud_task(ctx, sandbox, input.repository)

        return CloneRepositoryInSandboxOutput(clone_ms=clone_timer.elapsed_ms)


def _is_missing_remote_branch_clone_error(result: ExecutionResult) -> bool:
    if result.exit_code == 0:
        return False

    output = f"{result.stdout}\n{result.stderr}".casefold()
    return (
        "could not find remote branch" in output
        or ("remote branch" in output and "not found in upstream origin" in output)
        or "couldn't find remote ref" in output
    )


@activity.defn
@asyncify
def checkout_branch_in_sandbox(input: CheckoutBranchInSandboxInput) -> CheckoutBranchInSandboxOutput:
    ctx = input.context

    with log_activity_execution(
        "checkout_branch_in_sandbox",
        sandbox_id=input.sandbox_id,
        branch=input.branch,
        **ctx.to_log_context(),
    ):
        emit_agent_log(ctx.run_id, "debug", f"Checking out branch {input.branch}")
        sandbox = Sandbox.get_by_id(input.sandbox_id)

        org, repo = input.repository.lower().split("/")
        repo_path = f"/tmp/workspace/repos/{org}/{repo}"

        if input.used_snapshot and input.github_token:
            update_remote = (
                f"cd {shlex.quote(repo_path)} && "
                f"git remote set-url origin https://x-access-token:{shlex.quote(input.github_token)}@github.com/{shlex.quote(input.repository)}.git"
            )
            update_result = sandbox.execute(update_remote, timeout_seconds=30)
            if update_result.exit_code != 0:
                logger.warning(
                    "Failed to update remote URL for snapshot",
                    extra={"branch": input.branch, "stderr": update_result.stderr},
                )

        branch = shlex.quote(input.branch)
        branch_ref = shlex.quote(f"refs/heads/{input.branch}")
        remote_branch_check = f"cd {shlex.quote(repo_path)} && git ls-remote --exit-code --heads origin {branch_ref}"
        remote_branch_result = sandbox.execute(remote_branch_check, timeout_seconds=30)

        if remote_branch_result.exit_code == 0:
            depth_flag = f" --depth {shlex.quote('1')}" if input.shallow_clone else ""
            checkout_command = (
                f"cd {shlex.quote(repo_path)} && "
                f"git fetch{depth_flag} origin -- {branch} && "
                f"git checkout -B {branch} FETCH_HEAD"
            )
        elif remote_branch_result.exit_code == 2:
            if input.used_snapshot:
                depth_flag = f" --depth {shlex.quote('1')}" if input.shallow_clone else ""
                checkout_command = (
                    f"cd {shlex.quote(repo_path)} && "
                    f"git fetch{depth_flag} origin -- HEAD && "
                    f"git checkout -B {branch} FETCH_HEAD"
                )
            else:
                checkout_command = f"cd {shlex.quote(repo_path)} && git checkout -B {branch} HEAD"
        else:
            logger.warning(
                "Failed to check whether remote branch exists",
                extra={"branch": input.branch, "stderr": remote_branch_result.stderr},
            )
            raise RuntimeError(f"Failed to check whether branch {input.branch} exists")

        with StepTimer(
            "branch_checkout",
            used_snapshot=input.used_snapshot,
            origin_product=ctx.origin_product,
            runtime=sandbox_runtime_label(ctx.use_modal_vm_sandbox),
        ) as checkout_timer:
            result = sandbox.execute(checkout_command, timeout_seconds=5 * 60)

        if result.exit_code != 0:
            logger.warning("Branch checkout failed", extra={"branch": input.branch, "stderr": result.stderr})
            raise RuntimeError(f"Failed to checkout branch {input.branch}")

        _prepare_posthog_desktop_cloud_task(ctx, sandbox, input.repository)

        return CheckoutBranchInSandboxOutput(checkout_ms=checkout_timer.elapsed_ms)


@activity.defn
@asyncify
def restore_sandbox_connection_state(input: RestoreSandboxConnectionStateInput) -> None:
    """Point the run's persisted connection state back at a sandbox it already had.

    Creating a replacement sandbox publishes its connection details immediately, so an
    abandoned replacement would otherwise leave every later follow-up addressing a sandbox
    that no longer exists while the original is still serving the run.
    """
    updates: dict[str, Any] = {
        "sandbox_id": input.sandbox_id,
        "sandbox_url": input.sandbox_url,
    }
    remove_keys = [] if input.connect_token else ["sandbox_connect_token"]
    if input.connect_token:
        updates["sandbox_connect_token"] = input.connect_token
    # The signing key id belongs to the same set as the handle it authenticates —
    # clear_sandbox_connection_state_atomic drops all four together. Leaving the
    # replacement's behind would sign tokens the restored sandbox does not trust.
    if input.jwt_kid:
        updates[SANDBOX_JWT_STATE_KID_KEY] = input.jwt_kid
    else:
        remove_keys.append(SANDBOX_JWT_STATE_KID_KEY)
    TaskRun.update_state_atomic(input.run_id, updates=updates, remove_keys=remove_keys)
    activity.logger.info(
        "restored sandbox connection state",
        extra={"run_id": input.run_id, "sandbox_id": input.sandbox_id},
    )


@activity.defn
@asyncify
def inject_fresh_tokens_on_resume(input: InjectFreshTokensOnResumeInput) -> None:
    """Refresh credentials inside a sandbox that was restored from a snapshot.

    Modal secrets deliver fresh ``GITHUB_TOKEN`` / ``POSTHOG_PERSONAL_API_KEY``
    env vars to the new sandbox process, but the snapshotted filesystem can
    still carry stale tokens that Modal does not own. In particular the
    previous run's ``.git/config`` embeds ``x-access-token:<OLD_TOKEN>`` in
    its remote URL, so ``git fetch``/``push`` would use the expired token
    until the remote URL is rewritten.

    This activity always fetches fresh tokens (rather than trusting whatever
    the workflow previously cached in its inputs) and persists them to the
    in-sandbox locations that Modal secrets cannot refresh.
    """
    ctx = input.context

    with log_activity_execution(
        "inject_fresh_tokens_on_resume",
        sandbox_id=input.sandbox_id,
        **ctx.to_log_context(),
    ):
        task = _load_task(ctx)

        actor_user = get_task_run_credential_user(task, ctx.state)
        github_token = ""
        if ctx.github_read_access and input.repository is None:
            # Same priority rule as fresh provisioning (_resolve_sandbox_github_token): a repo-less
            # read-only run must never regain the write-capable token on resume. Best-effort — an
            # empty token just leaves the sandbox without GitHub access.
            github_token = get_readonly_github_token(ctx.team_id) or ""
        elif ctx.has_github_credentials:
            try:
                github_token = (
                    get_sandbox_github_token(
                        ctx.github_integration_id,
                        run_id=ctx.run_id,
                        state=ctx.state,
                        task=task,
                        actor_user=actor_user,
                        github_user_integration_id=ctx.github_user_integration_id,
                        repository=input.repository,
                    )
                    or ""
                )
            except ReauthorizationRequired as e:
                raise CredentialUnavailableError(
                    "GitHub user integration for this run requires reauthorization",
                    {"github_integration_id": ctx.github_integration_id, "task_id": ctx.task_id},
                    cause=e,
                )
            except Exception as e:
                raise GitHubAuthenticationError(
                    f"Failed to refresh GitHub token for integration {ctx.github_integration_id}",
                    {
                        "github_integration_id": ctx.github_integration_id,
                        "task_id": ctx.task_id,
                        "error": str(e),
                    },
                    cause=e,
                )

        try:
            access_token = create_oauth_access_token_for_run(task, ctx.state)
        except Exception as e:
            raise OAuthTokenError(
                f"Failed to refresh OAuth access token for task {ctx.task_id}",
                {"task_id": ctx.task_id, "error": str(e)},
                cause=e,
            )

        sandbox = Sandbox.get_by_id(input.sandbox_id)

        if input.repository:
            set_git_remote_token(sandbox, input.repository, github_token or None)

        # Replace both credential domains even when resolution returns no token,
        # so revoked credentials cannot survive in a resumed filesystem snapshot.
        if not replace_sandbox_credentials(sandbox, github_token or None, access_token or None):
            raise RuntimeError("Failed to replace resumed sandbox credentials")

        emit_agent_log(ctx.run_id, "debug", "Refreshed sandbox credentials after resume")


@activity.defn
@asyncify
def invalidate_resume_snapshot(input: InvalidateResumeSnapshotInput) -> None:
    """Drop the resume snapshot from the run state after a failed restore, so retries and
    future runs of the task (which carry the previous run's snapshot) stop resuming from it."""
    with log_activity_execution(
        "invalidate_resume_snapshot",
        run_id=input.run_id,
        snapshot_external_id=input.snapshot_external_id,
    ):
        TaskRun.update_state_atomic(
            input.run_id,
            remove_keys=["snapshot_external_id", "snapshot_kind", "snapshot_mount_path"],
        )
        emit_agent_log(input.run_id, "debug", "Previous session snapshot could not be restored; discarded it")
