import shlex
import logging
from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.models import SandboxSnapshot, Task, TaskRun
from products.tasks.backend.services.sandbox import Sandbox, SandboxConfig, SandboxTemplate
from products.tasks.backend.temporal.exceptions import GitHubAuthenticationError, OAuthTokenError, TaskNotFoundError
from products.tasks.backend.temporal.metrics import StepTimer, increment_snapshot_usage
from products.tasks.backend.temporal.oauth import create_oauth_access_token
from products.tasks.backend.temporal.observability import emit_agent_log, log_activity_execution
from products.tasks.backend.temporal.process_task.utils import (
    build_sandbox_environment_variables,
    get_github_token,
    get_sandbox_name_for_task,
)

from .get_task_processing_context import TaskProcessingContext

logger = logging.getLogger(__name__)


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
        has_repo = ctx.repository is not None and ctx.github_integration_id is not None
        repository: str | None = ctx.repository
        github_integration_id: int | None = ctx.github_integration_id

        snapshot = None
        used_snapshot = False
        if has_repo:
            assert repository is not None
            assert github_integration_id is not None
            with StepTimer("snapshot_lookup") as snapshot_lookup_timer:
                snapshot = SandboxSnapshot.get_latest_snapshot_with_repos(github_integration_id, [repository])
                used_snapshot = snapshot is not None
                snapshot_lookup_timer.set_used_snapshot(used_snapshot)
            increment_snapshot_usage(used_snapshot)
        else:
            emit_agent_log(ctx.run_id, "info", "Creating environment without repository")

        try:
            task = Task.objects.select_related("created_by").get(id=ctx.task_id)
        except Task.DoesNotExist as e:
            raise TaskNotFoundError(f"Task {ctx.task_id} not found", {"task_id": ctx.task_id}, cause=e)

        github_token = ""
        if has_repo:
            assert github_integration_id is not None
            try:
                github_token = get_github_token(github_integration_id) or ""
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

        sandbox_env = ctx.get_sandbox_environment()
        environment_variables = build_sandbox_environment_variables(
            github_token=github_token,
            access_token=access_token,
            team_id=ctx.team_id,
            sandbox_environment=sandbox_env,
        )

        # Set resume run ID independently of snapshot so conversation history
        # can be rebuilt from logs even when the filesystem snapshot has expired.
        resume_from_run_id = (ctx.state or {}).get("resume_from_run_id", "")
        if resume_from_run_id:
            environment_variables["POSTHOG_RESUME_RUN_ID"] = resume_from_run_id

        # Check for resume snapshot (takes priority over integration-level snapshots)
        resume_snapshot_ext_id = (ctx.state or {}).get("snapshot_external_id")
        if resume_snapshot_ext_id:
            used_snapshot = True

        if resume_snapshot_ext_id:
            emit_agent_log(ctx.run_id, "info", f"Resuming environment from snapshot for {repository}")
        elif has_repo and used_snapshot:
            emit_agent_log(ctx.run_id, "info", f"Found existing environment for {repository}")
        elif has_repo:
            emit_agent_log(ctx.run_id, "debug", f"Creating environment from base image for {repository}")

        config = SandboxConfig(
            name=get_sandbox_name_for_task(ctx.task_id),
            template=SandboxTemplate.DEFAULT_BASE,
            environment_variables=environment_variables,
            snapshot_external_id=resume_snapshot_ext_id,
            snapshot_id=str(snapshot.id) if snapshot and not resume_snapshot_ext_id else None,
            metadata={"task_id": ctx.task_id},
        )

        with StepTimer("sandbox_creation", used_snapshot=used_snapshot):
            sandbox = Sandbox.create(config)

        if has_repo and not used_snapshot:
            assert repository is not None
            emit_agent_log(ctx.run_id, "info", f"Cloning {repository} into sandbox")
            with StepTimer("repository_clone", used_snapshot=used_snapshot):
                clone_result = sandbox.clone_repository(repository, github_token=github_token)
            if clone_result.exit_code != 0:
                sandbox.destroy()
                raise RuntimeError(f"Failed to clone repository {repository}: {clone_result.stderr}")

        if has_repo and ctx.branch:
            assert repository is not None
            emit_agent_log(ctx.run_id, "info", f"Checking out branch {ctx.branch}")
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

            fetch_and_checkout = (
                f"cd {shlex.quote(repo_path)} && "
                f"git fetch --depth 1 origin -- {shlex.quote(ctx.branch)} && "
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

        task_run = TaskRun.objects.get(id=ctx.run_id)
        state = task_run.state or {}
        state["sandbox_id"] = sandbox.id
        state["sandbox_url"] = credentials.url
        if credentials.token:
            state["sandbox_connect_token"] = credentials.token
        task_run.state = state
        task_run.save(update_fields=["state", "updated_at"])

        activity.logger.info(f"Created sandbox {sandbox.id} (used_snapshot={used_snapshot})")

        return GetSandboxForRepositoryOutput(
            sandbox_id=sandbox.id,
            sandbox_url=credentials.url,
            connect_token=credentials.token,
            used_snapshot=used_snapshot,
            should_create_snapshot=not used_snapshot,
        )
