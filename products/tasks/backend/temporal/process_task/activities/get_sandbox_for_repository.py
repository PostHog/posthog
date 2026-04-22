import shlex
import logging
from dataclasses import dataclass

from django.conf import settings

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.models import SandboxEnvironment, SandboxSnapshot, Task, TaskRun
from products.tasks.backend.services.connection_token import get_sandbox_jwt_public_key
from products.tasks.backend.services.sandbox import (
    Sandbox,
    SandboxConfig,
    SandboxTemplate,
    parse_sandbox_repo_mount_map,
)
from products.tasks.backend.temporal.exceptions import GitHubAuthenticationError, OAuthTokenError, TaskNotFoundError
from products.tasks.backend.temporal.metrics import StepTimer, increment_snapshot_usage
from products.tasks.backend.temporal.oauth import create_oauth_access_token
from products.tasks.backend.temporal.observability import emit_agent_log, log_activity_execution
from products.tasks.backend.temporal.process_task.utils import (
    get_git_identity_env_vars,
    get_sandbox_api_url,
    get_sandbox_github_token,
    get_sandbox_name_for_task,
    parse_run_state,
)

from .get_task_processing_context import TaskProcessingContext

logger = logging.getLogger(__name__)

RESERVED_SANDBOX_ENVIRONMENT_VARIABLE_KEYS = {
    "POSTHOG_PERSONAL_API_KEY",
    "POSTHOG_API_URL",
    "POSTHOG_PROJECT_ID",
    "JWT_PUBLIC_KEY",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "LLM_GATEWAY_URL",
    "POSTHOG_RESUME_RUN_ID",
}


def _get_image_source_label(
    *,
    has_repo: bool,
    provider: str | None,
    resume_snapshot_external_id: str | None,
    snapshot: SandboxSnapshot | None,
) -> str:
    if resume_snapshot_external_id:
        return f"resume snapshot {resume_snapshot_external_id}"

    if snapshot is not None:
        external_id = snapshot.external_id or str(snapshot.id)
        return f"repository snapshot {external_id}"

    if provider == "docker":
        return "local Docker sandbox image"

    if provider and provider.upper() == "MODAL_DOCKER":
        return "local Modal Dockerfile build"

    if settings.DEBUG and not has_repo:
        return "local debug sandbox image"

    return "published sandbox base image"


def _emit_provisioning_diagnostics(ctx: TaskProcessingContext, sandbox: object) -> None:
    diagnostics = getattr(sandbox, "provision_diagnostics", None)
    if diagnostics is None:
        return

    summary_lines = getattr(diagnostics, "summary_lines", None) or []
    if summary_lines:
        emit_agent_log(
            ctx.run_id,
            "debug",
            "Sandbox image build summary:\n" + "\n".join(f"- {line}" for line in summary_lines),
        )

    raw_excerpt = getattr(diagnostics, "raw_excerpt", None)
    if raw_excerpt:
        emit_agent_log(ctx.run_id, "debug", f"Sandbox image build logs:\n{raw_excerpt}")


@dataclass
class GetSandboxForRepositoryInput:
    context: TaskProcessingContext


@dataclass
class GetSandboxForRepositoryOutput:
    sandbox_id: str
    sandbox_url: str
    connect_token: str | None
    used_snapshot: bool
    should_create_snapshot: bool


@activity.defn
@asyncify
def get_sandbox_for_repository(input: GetSandboxForRepositoryInput) -> GetSandboxForRepositoryOutput:
    ctx = input.context

    with log_activity_execution(
        "get_sandbox_for_repository",
        **ctx.to_log_context(),
    ):
        has_repo = ctx.repository is not None
        repository: str | None = ctx.repository
        github_integration_id: int | None = ctx.github_integration_id

        snapshot = None
        used_snapshot = False
        if has_repo and github_integration_id is not None:
            assert repository is not None
            with StepTimer("snapshot_lookup") as snapshot_lookup_timer:
                snapshot = SandboxSnapshot.get_latest_snapshot_with_repos(github_integration_id, [repository])
                used_snapshot = snapshot is not None
                snapshot_lookup_timer.set_used_snapshot(used_snapshot)
            increment_snapshot_usage(used_snapshot)
        elif not has_repo:
            emit_agent_log(ctx.run_id, "debug", "Creating environment without repository")

        try:
            task = Task.objects.select_related("created_by").get(id=ctx.task_id)
        except Task.DoesNotExist as e:
            raise TaskNotFoundError(f"Task {ctx.task_id} not found", {"task_id": ctx.task_id}, cause=e)

        # Signal report research sandboxes need full history for git blame.
        # All other sandboxes use shallow clone (--depth 1) for faster boot.
        shallow = task.origin_product != Task.OriginProduct.SIGNAL_REPORT

        github_token = ""
        if has_repo and github_integration_id is not None:
            try:
                github_token = (
                    get_sandbox_github_token(
                        github_integration_id,
                        run_id=ctx.run_id,
                        state=ctx.state,
                    )
                    or ""
                )
            except Exception as e:
                raise GitHubAuthenticationError(
                    f"Failed to get GitHub token for integration {github_integration_id}",
                    {"github_integration_id": github_integration_id, "task_id": ctx.task_id, "error": str(e)},
                    cause=e,
                )

        try:
            access_token = create_oauth_access_token(task)
        except Exception as e:
            raise OAuthTokenError(
                f"Failed to create OAuth access token for task {ctx.task_id}",
                {"task_id": ctx.task_id, "error": str(e)},
                cause=e,
            )

        environment_variables = {
            "POSTHOG_PERSONAL_API_KEY": access_token,
            "POSTHOG_API_URL": get_sandbox_api_url(),
            "POSTHOG_PROJECT_ID": str(ctx.team_id),
            "JWT_PUBLIC_KEY": get_sandbox_jwt_public_key(),
        }

        sandbox_environment = None
        if ctx.sandbox_environment_id:
            sandbox_environment = SandboxEnvironment.objects.filter(
                id=ctx.sandbox_environment_id, team=task.team
            ).first()
            if sandbox_environment and sandbox_environment.environment_variables:
                skipped_keys: list[str] = []
                added_keys = 0
                for key, value in sandbox_environment.environment_variables.items():
                    if key in RESERVED_SANDBOX_ENVIRONMENT_VARIABLE_KEYS:
                        skipped_keys.append(key)
                        continue
                    environment_variables[key] = value
                    added_keys += 1

                emit_agent_log(
                    ctx.run_id,
                    "debug",
                    f"Applied {added_keys} sandbox environment variable(s) from '{sandbox_environment.name}'",
                )
                if skipped_keys:
                    emit_agent_log(
                        ctx.run_id,
                        "debug",
                        f"Skipped reserved sandbox environment variable keys from '{sandbox_environment.name}': {', '.join(sorted(skipped_keys))}",
                    )

        if github_token:
            environment_variables["GITHUB_TOKEN"] = github_token
            environment_variables["GH_TOKEN"] = github_token

        if settings.SANDBOX_LLM_GATEWAY_URL:
            environment_variables["LLM_GATEWAY_URL"] = settings.SANDBOX_LLM_GATEWAY_URL

        environment_variables.update(get_git_identity_env_vars(task, ctx.state))

        run_state = parse_run_state(ctx.state)

        # Set resume run ID independently of snapshot so conversation history
        # can be rebuilt from logs even when the filesystem snapshot has expired.
        if run_state.resume_from_run_id:
            environment_variables["POSTHOG_RESUME_RUN_ID"] = run_state.resume_from_run_id

        # Check for resume snapshot (takes priority over integration-level snapshots)
        resume_snapshot_ext_id = run_state.snapshot_external_id
        if resume_snapshot_ext_id:
            used_snapshot = True

        provider = getattr(settings, "SANDBOX_PROVIDER", None)
        image_source_label = _get_image_source_label(
            has_repo=has_repo,
            provider=provider,
            resume_snapshot_external_id=resume_snapshot_ext_id,
            snapshot=snapshot if not resume_snapshot_ext_id else None,
        )

        if resume_snapshot_ext_id:
            emit_agent_log(ctx.run_id, "debug", f"Resuming environment from snapshot for {repository}")
        elif has_repo and used_snapshot:
            emit_agent_log(ctx.run_id, "debug", f"Found existing environment for {repository}")
        elif has_repo:
            emit_agent_log(ctx.run_id, "debug", f"Creating environment from {image_source_label} for {repository}")
        else:
            emit_agent_log(ctx.run_id, "debug", f"Creating environment from {image_source_label}")

        config = SandboxConfig(
            name=get_sandbox_name_for_task(ctx.task_id),
            template=SandboxTemplate.DEFAULT_BASE,
            environment_variables=environment_variables,
            snapshot_external_id=resume_snapshot_ext_id,
            snapshot_id=str(snapshot.id) if snapshot and not resume_snapshot_ext_id else None,
            metadata={"task_id": ctx.task_id},
        )

        emit_agent_log(
            ctx.run_id,
            "debug",
            f"Provisioning sandbox from {image_source_label} (image build may take a few minutes on first run)",
        )
        with StepTimer("sandbox_creation", used_snapshot=used_snapshot):
            sandbox = Sandbox.create(config)
        _emit_provisioning_diagnostics(ctx, sandbox)
        emit_agent_log(ctx.run_id, "debug", f"Sandbox provisioned: {sandbox.id}")

        if has_repo and not used_snapshot:
            assert repository is not None
            local_bind = parse_sandbox_repo_mount_map().get(repository.lower())
            # Bind mounts are only applied for Docker sandboxes; Modal ignores SANDBOX_REPO_MOUNT_MAP.
            if local_bind is not None and getattr(settings, "SANDBOX_PROVIDER", None) == "docker":
                emit_agent_log(
                    ctx.run_id,
                    "debug",
                    f"Using local checkout for {repository} at {local_bind} (SANDBOX_REPO_MOUNT_MAP); skipping clone from GitHub",
                )
            else:
                emit_agent_log(ctx.run_id, "debug", f"Cloning {repository} into sandbox")
            with StepTimer("repository_clone", used_snapshot=used_snapshot):
                clone_result = sandbox.clone_repository(repository, github_token=github_token, shallow=shallow)
            if clone_result.exit_code != 0:
                sandbox.destroy()
                raise RuntimeError(f"Failed to clone repository {repository}: {clone_result.stderr}")

        if has_repo and ctx.branch:
            assert repository is not None
            emit_agent_log(ctx.run_id, "debug", f"Checking out branch {ctx.branch}")
            org, repo = repository.lower().split("/")
            repo_path = f"/tmp/workspace/repos/{org}/{repo}"

            # For snapshot-based sandboxes, update the remote URL with the fresh token
            # since the snapshotted .git/config may contain an expired token.
            if used_snapshot and github_token:
                update_remote = (
                    f"cd {shlex.quote(repo_path)} && "
                    f"git remote set-url origin https://x-access-token:{shlex.quote(github_token)}@github.com/{shlex.quote(repository)}.git"
                )
                update_result = sandbox.execute(update_remote, timeout_seconds=30)
                if update_result.exit_code != 0:
                    logger.warning(
                        "Failed to update remote URL for snapshot",
                        extra={"branch": ctx.branch, "stderr": update_result.stderr},
                    )

            depth_flag = f" --depth {shlex.quote('1')}" if shallow else ""
            fetch_and_checkout = (
                f"cd {shlex.quote(repo_path)} && "
                f"git fetch{depth_flag} origin -- {shlex.quote(ctx.branch)} && "
                f"git checkout -B {shlex.quote(ctx.branch)} FETCH_HEAD"
            )
            try:
                result = sandbox.execute(fetch_and_checkout, timeout_seconds=5 * 60)
            except Exception:
                sandbox.destroy()
                raise
            if result.exit_code != 0:
                sandbox.destroy()
                logger.warning("Branch checkout failed", extra={"branch": ctx.branch, "stderr": result.stderr})
                raise RuntimeError(f"Failed to checkout branch {ctx.branch}")

        credentials = sandbox.get_connect_credentials()

        sandbox_state = {
            "sandbox_id": sandbox.id,
            "sandbox_url": credentials.url,
        }
        if credentials.token:
            sandbox_state["sandbox_connect_token"] = credentials.token
        TaskRun.update_state_atomic(ctx.run_id, updates=sandbox_state)

        activity.logger.info(f"Created sandbox {sandbox.id} (used_snapshot={used_snapshot})")

        return GetSandboxForRepositoryOutput(
            sandbox_id=sandbox.id,
            sandbox_url=credentials.url,
            connect_token=credentials.token,
            used_snapshot=used_snapshot,
            should_create_snapshot=not used_snapshot,
        )
