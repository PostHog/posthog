import shlex
import logging
from dataclasses import dataclass

from django.conf import settings

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.models import SandboxEnvironment, SandboxSnapshot, Task, TaskRun
from products.tasks.backend.services.connection_token import get_sandbox_jwt_public_key
from products.tasks.backend.services.sandbox import Sandbox, SandboxConfig, SandboxTemplate
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


@dataclass
class CreateSandboxForRepositoryInput:
    context: TaskProcessingContext
    prepared: PrepareSandboxForRepositoryOutput


@dataclass
class CreateSandboxForRepositoryOutput:
    sandbox_id: str
    sandbox_url: str
    connect_token: str | None


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


def _load_task(ctx: TaskProcessingContext) -> Task:
    try:
        return Task.objects.select_related("created_by").get(id=ctx.task_id)
    except Task.DoesNotExist as e:
        raise TaskNotFoundError(f"Task {ctx.task_id} not found", {"task_id": ctx.task_id}, cause=e)


def _get_image_source_label(
    *,
    has_repo: bool,
    provider: str | None,
    resume_snapshot_external_id: str | None,
    snapshot: SandboxSnapshot | None,
) -> tuple[str, str]:
    if resume_snapshot_external_id:
        return "resume_snapshot", f"resume snapshot {resume_snapshot_external_id}"

    if snapshot is not None:
        external_id = snapshot.external_id or str(snapshot.id)
        return "repository_snapshot", f"repository snapshot {external_id}"

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
        "JWT_PUBLIC_KEY": get_sandbox_jwt_public_key(),
    }

    sandbox_environment = None
    if ctx.sandbox_environment_id:
        sandbox_environment = SandboxEnvironment.objects.filter(id=ctx.sandbox_environment_id, team=task.team).first()
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
    if run_state.resume_from_run_id:
        environment_variables["POSTHOG_RESUME_RUN_ID"] = run_state.resume_from_run_id

    return environment_variables


def _emit_image_source_log(ctx: TaskProcessingContext, prepared: PrepareSandboxForRepositoryOutput) -> None:
    if prepared.image_source == "resume_snapshot":
        emit_agent_log(ctx.run_id, "info", f"Resuming environment from snapshot for {prepared.repository}")
    elif prepared.image_source == "repository_snapshot":
        emit_agent_log(ctx.run_id, "info", f"Found existing environment for {prepared.repository}")
    elif prepared.repository:
        emit_agent_log(
            ctx.run_id, "debug", f"Creating environment from {prepared.image_source_label} for {prepared.repository}"
        )
    else:
        emit_agent_log(ctx.run_id, "debug", f"Creating environment from {prepared.image_source_label}")


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
        if has_repo and ctx.github_integration_id is not None:
            assert repository is not None
            with StepTimer("snapshot_lookup") as snapshot_lookup_timer:
                snapshot = SandboxSnapshot.get_latest_snapshot_with_repos(ctx.github_integration_id, [repository])
                used_snapshot = snapshot is not None
                snapshot_lookup_timer.set_used_snapshot(used_snapshot)
            increment_snapshot_usage(used_snapshot)
        elif not has_repo:
            emit_agent_log(ctx.run_id, "info", "Creating environment without repository")

        task = _load_task(ctx)
        shallow_clone = task.origin_product != Task.OriginProduct.SIGNAL_REPORT

        github_token = ""
        if has_repo and ctx.github_integration_id is not None:
            try:
                github_token = (
                    get_sandbox_github_token(
                        ctx.github_integration_id,
                        run_id=ctx.run_id,
                        state=ctx.state,
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
            access_token = create_oauth_access_token(task)
        except Exception as e:
            raise OAuthTokenError(
                f"Failed to create OAuth access token for task {ctx.task_id}",
                {"task_id": ctx.task_id, "error": str(e)},
                cause=e,
            )

        environment_variables = _build_environment_variables(ctx, task, github_token, access_token)

        run_state = parse_run_state(ctx.state)
        resume_snapshot_external_id = run_state.snapshot_external_id
        if resume_snapshot_external_id:
            used_snapshot = True

        provider = getattr(settings, "SANDBOX_PROVIDER", None)
        image_source, image_source_label = _get_image_source_label(
            has_repo=has_repo,
            provider=provider,
            resume_snapshot_external_id=resume_snapshot_external_id,
            snapshot=snapshot if not resume_snapshot_external_id else None,
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

        config = SandboxConfig(
            name=prepared.sandbox_name,
            template=SandboxTemplate.DEFAULT_BASE,
            environment_variables=prepared.environment_variables,
            snapshot_id=prepared.snapshot_id,
            snapshot_external_id=prepared.snapshot_external_id,
            metadata={"task_id": ctx.task_id},
        )

        with StepTimer("sandbox_creation", used_snapshot=prepared.used_snapshot):
            sandbox = Sandbox.create(config)

        credentials = sandbox.get_connect_credentials()

        try:
            task_run = TaskRun.objects.get(id=ctx.run_id)
            state = task_run.state or {}
            state["sandbox_id"] = sandbox.id
            state["sandbox_url"] = credentials.url
            if credentials.token:
                state["sandbox_connect_token"] = credentials.token
            task_run.state = state
            task_run.save(update_fields=["state", "updated_at"])
        except Exception:
            sandbox.destroy()
            raise

        emit_agent_log(ctx.run_id, "debug", f"Sandbox provisioned: {sandbox.id}")
        activity.logger.info(f"Created sandbox {sandbox.id} (used_snapshot={prepared.used_snapshot})")

        return CreateSandboxForRepositoryOutput(
            sandbox_id=sandbox.id,
            sandbox_url=credentials.url,
            connect_token=credentials.token,
        )


@activity.defn
@asyncify
def clone_repository_in_sandbox(input: CloneRepositoryInSandboxInput) -> None:
    ctx = input.context

    with log_activity_execution(
        "clone_repository_in_sandbox",
        sandbox_id=input.sandbox_id,
        **ctx.to_log_context(),
    ):
        emit_agent_log(ctx.run_id, "info", f"Cloning {input.repository} into sandbox")
        sandbox = Sandbox.get_by_id(input.sandbox_id)

        with StepTimer("repository_clone", used_snapshot=False):
            clone_result = sandbox.clone_repository(
                input.repository,
                github_token=input.github_token,
                shallow=input.shallow_clone,
            )

        if clone_result.exit_code != 0:
            raise RuntimeError(f"Failed to clone repository {input.repository}: {clone_result.stderr}")


@activity.defn
@asyncify
def checkout_branch_in_sandbox(input: CheckoutBranchInSandboxInput) -> None:
    ctx = input.context

    with log_activity_execution(
        "checkout_branch_in_sandbox",
        sandbox_id=input.sandbox_id,
        branch=input.branch,
        **ctx.to_log_context(),
    ):
        emit_agent_log(ctx.run_id, "info", f"Checking out branch {input.branch}")
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

        with StepTimer("branch_checkout", used_snapshot=input.used_snapshot):
            result = sandbox.execute(fetch_and_checkout, timeout_seconds=5 * 60)

        if result.exit_code != 0:
            logger.warning("Branch checkout failed", extra={"branch": input.branch, "stderr": result.stderr})
            raise RuntimeError(f"Failed to checkout branch {input.branch}")
