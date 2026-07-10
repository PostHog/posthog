import shlex
import logging
from dataclasses import dataclass

from django.conf import settings

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.constants import SNAPSHOT_KIND_FILESYSTEM, filter_user_sandbox_env_vars
from products.tasks.backend.exceptions import GitHubAuthenticationError, OAuthTokenError, TaskNotFoundError
from products.tasks.backend.logic.services.agentsh import ENV_FILE, INFRASTRUCTURE_DOMAINS, _get_debug_only_domains
from products.tasks.backend.logic.services.connection_token import (
    SANDBOX_JWT_STATE_KID_KEY,
    get_primary_sandbox_jwt_kid,
    get_sandbox_jwt_public_key,
)
from products.tasks.backend.logic.services.sandbox import Sandbox, SandboxConfig, SandboxTemplate
from products.tasks.backend.models import SandboxSnapshot, Task, TaskRun
from products.tasks.backend.temporal.metrics import (
    StepTimer,
    increment_sandbox_created,
    increment_snapshot_restore,
    increment_snapshot_usage,
)
from products.tasks.backend.temporal.oauth import create_oauth_access_token_for_run, create_wizard_oauth_access_token
from products.tasks.backend.temporal.observability import emit_agent_log, log_activity_execution
from products.tasks.backend.temporal.process_task.sandbox_credentials import set_git_remote_token
from products.tasks.backend.temporal.process_task.utils import (
    get_git_identity_env_vars,
    get_sandbox_api_url,
    get_sandbox_github_token,
    get_sandbox_name_for_task,
    get_sandbox_snapshot_metadata,
    get_task_run_credential_user,
    parse_run_state,
)

from .get_task_processing_context import TaskProcessingContext

logger = logging.getLogger(__name__)

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


@dataclass
class CreateSandboxForRepositoryInput:
    context: TaskProcessingContext
    prepared: PrepareSandboxForRepositoryOutput


@dataclass
class CreateSandboxForRepositoryOutput:
    sandbox_id: str
    sandbox_url: str
    connect_token: str | None
    used_snapshot: bool | None = None
    create_ms: int | None = None


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


@dataclass
class InjectFreshTokensOnResumeInput:
    context: TaskProcessingContext
    sandbox_id: str
    repository: str | None


@dataclass
class InvalidateResumeSnapshotInput:
    run_id: str
    snapshot_external_id: str | None = None


def _is_covered_by_wildcard(host: str, wildcard_bases: set[str]) -> bool:
    base = host[2:] if host.startswith("*.") else host
    for wildcard_base in wildcard_bases:
        if host.startswith("*.") and base == wildcard_base:
            continue
        if base == wildcard_base or base.endswith("." + wildcard_base):
            return True
    return False


def _to_modal_domain_allowlist(allowed_domains: list[str]) -> list[str]:
    """Translate the agentsh allowlist into Modal's outbound_domain_allowlist.

    Modal fences the whole sandbox and supports `*.` wildcards that match the
    apex and any subdomain, so union in the infra (and local tunnel) domains the
    agent needs, drop loopback aliases Modal rejects as invalid domains, and
    collapse entries already covered by a wildcard.
    """
    domains = list(allowed_domains)
    extra = list(INFRASTRUCTURE_DOMAINS)
    if settings.DEBUG:
        extra += _get_debug_only_domains()
    for domain in extra:
        if domain not in domains:
            domains.append(domain)

    fqdns = [d for d in domains if "." in d and d != "host.docker.internal"]
    wildcard_bases = {d[2:] for d in fqdns if d.startswith("*.")}

    result: list[str] = []
    seen: set[str] = set()
    for domain in fqdns:
        if domain in seen or _is_covered_by_wildcard(domain, wildcard_bases):
            continue
        seen.add(domain)
        result.append(domain)
    return result


def _load_task(ctx: TaskProcessingContext) -> Task:
    try:
        return Task.objects.select_related("created_by", "github_integration", "github_user_integration").get(
            id=ctx.task_id
        )
    except Task.DoesNotExist as e:
        raise TaskNotFoundError(f"Task {ctx.task_id} not found", {"task_id": ctx.task_id}, cause=e)


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

    if provider and provider.upper() == "MODAL_DOCKER":
        return "modal_local_build", "local Modal Dockerfile build"

    if settings.DEBUG and not has_repo:
        return "local_debug_build", "local debug sandbox image"

    return "base_image", "published sandbox base image"


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

    if ctx.allowed_domains is not None:
        environment_variables.update(NETWORK_RESTRICTED_AGENT_ENV)

    environment_variables.update(get_git_identity_env_vars(task, ctx.state))

    run_state = parse_run_state(ctx.state)
    if run_state.resume_from_run_id:
        environment_variables["POSTHOG_RESUME_RUN_ID"] = run_state.resume_from_run_id
    elif run_state.handoff_resumed:
        environment_variables["POSTHOG_RESUME_RUN_ID"] = str(ctx.run_id)

    # Cloud wizard runs get a SEPARATE token, minted under the wizard's own OAuth app with the
    # wizard's scopes, so the wizard's access stays independent of the agent's sandbox token above.
    # The run_wizard activity reads it from POSTHOG_WIZARD_API_KEY in the sandbox env.
    if ctx.wizard_config is not None:
        environment_variables["POSTHOG_WIZARD_API_KEY"] = create_wizard_oauth_access_token(task)

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
        "workflow_id": TaskRun.get_workflow_id(ctx.task_id, ctx.run_id),
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
        has_repo = ctx.repository is not None
        repository = ctx.repository

        snapshot = None
        used_snapshot = False
        snapshot_source = "none"
        snapshot_kind = SNAPSHOT_KIND_FILESYSTEM
        snapshot_mount_path: str | None = None
        # Repo-setup snapshots come from default-base sandboxes; restoring one would silently
        # drop the custom base image. Resume snapshots were taken from this task's own sandbox.
        if has_repo and ctx.github_integration_id is not None and not ctx.custom_image_name:
            assert repository is not None
            with StepTimer("snapshot_lookup") as snapshot_lookup_timer:
                snapshot = SandboxSnapshot.get_latest_snapshot_with_repos(ctx.github_integration_id, [repository])
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
        github_token = ""
        should_inject_github_token = ctx.has_github_credentials and (
            has_repo or ctx.github_user_integration_id is not None or ctx.github_integration_id is not None
        )
        if should_inject_github_token:
            try:
                github_token = (
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
            except Exception as e:
                raise GitHubAuthenticationError(
                    f"Failed to get GitHub token for integration {ctx.github_integration_id}",
                    {"github_integration_id": ctx.github_integration_id, "task_id": ctx.task_id, "error": str(e)},
                    cause=e,
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

        activity.logger.info(
            "resume_decision",
            extra={
                "run_id": ctx.run_id,
                "state_snapshot_external_id": run_state.snapshot_external_id,
                "state_snapshot_kind": run_state.snapshot_kind,
                "effective_snapshot_external_id": resume_snapshot_external_id,
                "effective_snapshot_kind": snapshot_kind,
                "effective_snapshot_mount_path": snapshot_mount_path,
                "handoff_resumed": run_state.handoff_resumed,
                "resume_from_run_id": run_state.resume_from_run_id,
                "posthog_resume_run_id_set": "POSTHOG_RESUME_RUN_ID" in environment_variables,
                "used_snapshot": used_snapshot,
            },
        )
        if run_state.handoff_resumed or run_state.resume_from_run_id:
            emit_agent_log(
                ctx.run_id,
                "debug",
                f"Resume mode: handoff_resumed={run_state.handoff_resumed}, "
                f"resume_from_run_id={run_state.resume_from_run_id}, "
                f"using_modal_snapshot={resume_snapshot_external_id is not None}",
            )

        provider = getattr(settings, "SANDBOX_PROVIDER", None)
        image_source, image_source_label = _get_image_source_label(
            has_repo=has_repo,
            provider=provider,
            resume_snapshot_external_id=resume_snapshot_external_id,
            snapshot=snapshot if not resume_snapshot_external_id else None,
            custom_image_name=ctx.custom_image_name if ctx.use_modal_vm_sandbox else None,
        )

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
        )


@activity.defn
@asyncify
def create_sandbox_for_repository(input: CreateSandboxForRepositoryInput) -> CreateSandboxForRepositoryOutput:
    ctx = input.context
    prepared = input.prepared

    with log_activity_execution(
        "create_sandbox_for_repository",
        image_source=prepared.image_source,
        **ctx.to_log_context(),
    ):
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
                f"Burstable resources enabled: requesting {config.cpu_request_cores} CPU / "
                f"{config.memory_request_mb} MiB, bursting up to {config.cpu_cores} CPU / "
                f"{int(config.memory_gb * 1024)} MiB",
            )

        # gVisor only — Modal's domain allowlist breaks vm_runtime.
        if ctx.use_modal_network_allowlist and not use_vm_sandbox and ctx.allowed_domains is not None:
            config.outbound_domain_allowlist = _to_modal_domain_allowlist(ctx.allowed_domains)
            emit_agent_log(
                ctx.run_id,
                "debug",
                f"Using Modal outbound_domain_allowlist ({len(config.outbound_domain_allowlist)} domains) instead of agentsh",
            )

        with StepTimer("sandbox_creation", used_snapshot=prepared.used_snapshot) as sandbox_creation_timer:
            sandbox = Sandbox.create(config)
            actual_used_snapshot = bool(
                (prepared.snapshot_external_id or prepared.snapshot_id) and sandbox.config.snapshot_restored
            )
            sandbox_creation_timer.set_used_snapshot(actual_used_snapshot)
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

        increment_sandbox_created("vm" if use_vm_sandbox else "gvisor")

        credentials = sandbox.get_connect_credentials()

        try:
            sandbox_state = {
                "sandbox_id": sandbox.id,
                "sandbox_url": credentials.url,
                SANDBOX_JWT_STATE_KID_KEY: get_primary_sandbox_jwt_kid(),
            }
            if credentials.token:
                sandbox_state["sandbox_connect_token"] = credentials.token
            TaskRun.update_state_atomic(ctx.run_id, updates=sandbox_state)
        except Exception:
            sandbox.destroy()
            raise

        emit_agent_log(ctx.run_id, "debug", f"Sandbox provisioned: {sandbox.id}")
        activity.logger.info(f"Created sandbox {sandbox.id} (used_snapshot={actual_used_snapshot})")

        return CreateSandboxForRepositoryOutput(
            sandbox_id=sandbox.id,
            sandbox_url=credentials.url,
            connect_token=credentials.token,
            used_snapshot=actual_used_snapshot,
            create_ms=create_ms,
        )


@activity.defn
@asyncify
def clone_repository_in_sandbox(input: CloneRepositoryInSandboxInput) -> CloneRepositoryInSandboxOutput:
    ctx = input.context

    with log_activity_execution(
        "clone_repository_in_sandbox",
        sandbox_id=input.sandbox_id,
        **ctx.to_log_context(),
    ):
        emit_agent_log(ctx.run_id, "debug", f"Cloning {input.repository} into sandbox")
        sandbox = Sandbox.get_by_id(input.sandbox_id)

        with StepTimer("repository_clone", used_snapshot=False) as clone_timer:
            clone_result = sandbox.clone_repository(
                input.repository,
                github_token=input.github_token,
                shallow=input.shallow_clone,
            )

        if clone_result.exit_code != 0:
            raise RuntimeError(f"Failed to clone repository {input.repository}: {clone_result.stderr}")

        return CloneRepositoryInSandboxOutput(clone_ms=clone_timer.elapsed_ms)


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

        depth_flag = f" --depth {shlex.quote('1')}" if input.shallow_clone else ""
        fetch_and_checkout = (
            f"cd {shlex.quote(repo_path)} && "
            f"git fetch{depth_flag} origin -- {shlex.quote(input.branch)} && "
            f"git checkout -B {shlex.quote(input.branch)} FETCH_HEAD"
        )

        with StepTimer("branch_checkout", used_snapshot=input.used_snapshot) as checkout_timer:
            result = sandbox.execute(fetch_and_checkout, timeout_seconds=5 * 60)

        if result.exit_code != 0:
            logger.warning("Branch checkout failed", extra={"branch": input.branch, "stderr": result.stderr})
            raise RuntimeError(f"Failed to checkout branch {input.branch}")

        return CheckoutBranchInSandboxOutput(checkout_ms=checkout_timer.elapsed_ms)


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
        if ctx.has_github_credentials:
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

        if github_token and input.repository:
            set_git_remote_token(sandbox, input.repository, github_token)

        # Pre-seed the agentsh env file so any wrapped command that runs between
        # resume and start_agent_server (diagnostics, branch checkout) sees the
        # fresh tokens instead of the stale snapshot values. start_agent_server
        # re-dumps the full process env over this, so a partial overwrite is fine
        # here (unlike the mid-run refresh, which must preserve the live env).
        fresh_env_vars: dict[str, str] = {}
        if github_token:
            fresh_env_vars["GITHUB_TOKEN"] = github_token
            fresh_env_vars["GH_TOKEN"] = github_token
        if access_token:
            fresh_env_vars["POSTHOG_PERSONAL_API_KEY"] = access_token

        if fresh_env_vars:
            env_payload = b"".join(f"{k}={v}\x00".encode() for k, v in fresh_env_vars.items())
            overwrite_result = sandbox.write_file(ENV_FILE, env_payload)
            if overwrite_result.exit_code != 0:
                logger.warning(
                    "Failed to refresh agentsh env file on resume",
                    extra={
                        "sandbox_id": input.sandbox_id,
                        "env_file": ENV_FILE,
                        "stderr": overwrite_result.stderr,
                    },
                )

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
