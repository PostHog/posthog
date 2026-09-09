import logging
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from django.conf import settings
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models.user import User
from posthog.temporal.oauth import create_wizard_oauth_access_token_for_user

from products.tasks.backend.facade.repo_selection import get_github_token
from products.tasks.backend.facade.sandbox import (
    SandboxBase,
    SandboxConfig,
    SandboxExecutionError,
    SandboxNotFoundError,
    SandboxTimeoutError,
    get_sandbox_class,
    sandbox_repo_path,
)
from products.wizard.backend.logic.artifacts.config import (
    PULL_REQUEST_BODY,
    PULL_REQUEST_COMMIT_MESSAGE,
    PULL_REQUEST_TITLE,
)
from products.wizard.backend.logic.workers.commands import (
    bound_command_output,
    build_git_diff_command,
    build_local_wizard_preparation_command,
    build_read_handoff_command,
    build_sanitize_repository_remote_command,
    build_wizard_command,
    pull_request_branch,
    wizard_handoff_output_path,
)
from products.wizard.backend.logic.workers.config import (
    LOCAL_WIZARD_ARCHIVE_PATH,
    LOCAL_WIZARD_BUILD_TIMEOUT_SECONDS,
    SANDBOX_CPU_CORES,
    SANDBOX_DISK_SIZE_GB,
    SANDBOX_EXECUTION_TIMEOUT_SECONDS,
    SANDBOX_MEMORY_GB,
    SANDBOX_TEMPLATE_BASE,
    SANDBOX_TTL_SECONDS,
    WIZARD_ERROR_DETAIL_LENGTH,
    WIZARD_TIMEOUT_EXIT_CODE,
)
from products.wizard.backend.logic.workers.contracts import (
    RepositoryPullRequest,
    WizardWorkerProvisioning,
    WizardWorkerResourceUsage,
    WizardWorkerUsageMeasurement,
)
from products.wizard.backend.logic.workers.local_package import build_local_wizard_source_archive
from products.wizard.backend.logic.workers.wizard_error_output import stderr_to_wizard_error_code
from products.wizard.backend.observability.service import wizard_observability

from .repository_publisher import RepositoryPublishingError, create_pull_request, create_signed_commit

logger = logging.getLogger(__name__)


@frozen
class WizardWorkerProvisionRequest:
    team_id: int
    created_by_id: int
    run_id: UUID


@frozen
class GitRepositoryCloneRequest:
    sandbox_id: str
    github_integration_id: int
    repository: str


@frozen
class WizardExecutionRequest:
    sandbox_id: str
    workspace_path: str
    team_id: int
    wizard_version: str
    program_command: tuple[str, ...]
    use_local_wizard_source: bool = False


@frozen
class GitRepositoryHandoffRequest:
    team_id: int
    run_id: UUID
    sandbox_id: str
    workspace_path: str
    github_integration_id: int
    repository: str


@frozen
class WizardWorkerResult:
    diff: bytes
    pull_request: RepositoryPullRequest | None


class WizardWorkerExecutionError(Exception):
    def __init__(
        self,
        stage: str,
        exit_code: int,
        detail: str | None = None,
        wizard_error_code: str | None = None,
    ) -> None:
        self.stage = stage
        self.exit_code = exit_code
        self.detail = detail
        self.wizard_error_code = wizard_error_code

        message = f"Wizard Worker {stage} failed with exit code {exit_code}."
        if detail:
            message = f"{message}\n{detail}"

        super().__init__(message)


class WizardWorkerTimeoutError(Exception):
    pass


def provision_wizard_worker(request: WizardWorkerProvisionRequest) -> WizardWorkerProvisioning:
    user = User.objects.get(id=request.created_by_id)
    wizard_token = create_wizard_oauth_access_token_for_user(user, request.team_id)

    config = _build_sandbox_config(request, wizard_token)
    sandbox = get_sandbox_class().create(config)
    provisioned_at = timezone.now()

    return WizardWorkerProvisioning(
        sandbox_id=sandbox.id,
        resource_usage=WizardWorkerResourceUsage(
            cpu_cores=config.cpu_cores,
            memory_gb=config.memory_gb,
            disk_size_gb=config.disk_size_gb,
            ttl_seconds=config.ttl_seconds,
            ttl_expires_at=provisioned_at + timedelta(seconds=config.ttl_seconds),
        ),
    )


def clone_repository(request: GitRepositoryCloneRequest) -> str:
    sandbox = get_sandbox_class().get_by_id(request.sandbox_id)
    github_token = get_github_token(request.github_integration_id) or ""
    clone_result = sandbox.clone_repository(request.repository, github_token=github_token, shallow=True)

    _raise_for_failure(
        "repository clone",
        clone_result.exit_code,
        stdout=clone_result.stdout,
        stderr=clone_result.stderr,
        sensitive_values=(github_token,),
    )

    workspace_path = sandbox_repo_path(request.repository)
    sanitize_result = sandbox.execute(
        build_sanitize_repository_remote_command(workspace_path, request.repository),
        timeout_seconds=60,
    )
    _raise_for_failure(
        "repository credential cleanup",
        sanitize_result.exit_code,
        stdout=sanitize_result.stdout,
        stderr=sanitize_result.stderr,
        sensitive_values=(github_token,),
    )

    return workspace_path


def prepare_local_wizard(sandbox_id: str, source_root: Path) -> None:
    archive = build_local_wizard_source_archive(source_root)

    try:
        sandbox = get_sandbox_class().get_by_id(sandbox_id)

        upload_result = sandbox.write_file(LOCAL_WIZARD_ARCHIVE_PATH, archive)
        _raise_for_failure(
            "local Wizard source upload",
            upload_result.exit_code,
            stdout=upload_result.stdout,
            stderr=upload_result.stderr,
        )

        build_result = sandbox.execute(
            build_local_wizard_preparation_command(),
            timeout_seconds=LOCAL_WIZARD_BUILD_TIMEOUT_SECONDS,
        )
        _raise_for_failure(
            "local Wizard build",
            build_result.exit_code,
            stdout=build_result.stdout,
            stderr=build_result.stderr,
        )
    except (SandboxExecutionError, SandboxNotFoundError, SandboxTimeoutError) as error:
        raise WizardWorkerExecutionError("local Wizard preparation", 1, str(error)) from error


def execute_wizard(request: WizardExecutionRequest) -> None:
    sandbox = get_sandbox_class().get_by_id(request.sandbox_id)

    wizard_result = sandbox.execute(
        bound_command_output(
            build_wizard_command(
                request.workspace_path,
                request.team_id,
                request.wizard_version,
                request.program_command,
                use_local_wizard_source=request.use_local_wizard_source,
            )
        ),
        timeout_seconds=SANDBOX_EXECUTION_TIMEOUT_SECONDS,
    )

    if wizard_result.exit_code == WIZARD_TIMEOUT_EXIT_CODE:
        raise WizardWorkerTimeoutError

    _raise_for_failure(
        "execution",
        wizard_result.exit_code,
        stdout=wizard_result.stdout,
        stderr=wizard_result.stderr,
    )


def create_git_repository_handoff(request: GitRepositoryHandoffRequest) -> WizardWorkerResult:
    sandbox = get_sandbox_class().get_by_id(request.sandbox_id)

    diff_result = sandbox.execute(
        build_git_diff_command(request.workspace_path),
        timeout_seconds=60,
    )

    _raise_for_failure(
        "diff capture",
        diff_result.exit_code,
        stdout=diff_result.stdout,
        stderr=diff_result.stderr,
    )

    diff = diff_result.stdout.encode("utf-8")

    if not diff:
        return WizardWorkerResult(diff=diff, pull_request=None)

    branch = pull_request_branch(request.run_id)
    handoff_body = _read_handoff_body(sandbox, request.run_id)

    if handoff_body is None:
        wizard_observability.handoff_body_fallback(request.team_id, request.run_id)
        handoff_body = PULL_REQUEST_BODY

    try:
        create_signed_commit(
            sandbox,
            team_id=request.team_id,
            integration_id=request.github_integration_id,
            repository=request.repository,
            branch=branch,
            message=PULL_REQUEST_COMMIT_MESSAGE,
            source="wizard",
        )

        pull_request = create_pull_request(
            team_id=request.team_id,
            integration_id=request.github_integration_id,
            repository=request.repository,
            head_branch=branch,
            title=PULL_REQUEST_TITLE,
            body=handoff_body,
            source="wizard",
        )

    except RepositoryPublishingError as error:
        raise WizardWorkerExecutionError("publishing", 1, str(error)) from error

    return WizardWorkerResult(diff=diff, pull_request=pull_request)


def destroy_worker(sandbox_id: str) -> None:
    try:
        sandbox = get_sandbox_class().get_by_id(sandbox_id)
    except SandboxNotFoundError:
        return
    sandbox.destroy()


def measure_worker_usage(sandbox_id: str) -> WizardWorkerUsageMeasurement | None:
    try:
        sandbox = get_sandbox_class().get_by_id(sandbox_id)
        cpu_usage_usec = sandbox.read_cpu_usage_usec()
        billed_cpu_usage_usec = sandbox.read_billed_cpu_usage_usec()
    except (SandboxExecutionError, SandboxNotFoundError, SandboxTimeoutError):
        logger.exception("wizard_worker_usage_measurement_failed", extra={"sandbox_id": sandbox_id})
        return None

    if cpu_usage_usec is None and billed_cpu_usage_usec is None:
        return None

    return WizardWorkerUsageMeasurement(
        cpu_usage_usec=cpu_usage_usec,
        billed_cpu_usage_usec=billed_cpu_usage_usec,
        measured_at=timezone.now(),
    )


def _raise_for_failure(
    stage: str,
    exit_code: int,
    *,
    stdout: str = "",
    stderr: str = "",
    sensitive_values: tuple[str, ...] = (),
) -> None:
    if exit_code != 0:
        raise WizardWorkerExecutionError(
            stage,
            exit_code,
            _failure_detail(stdout, stderr, sensitive_values),
            stderr_to_wizard_error_code(stderr),
        )


def _failure_detail(stdout: str, stderr: str, sensitive_values: tuple[str, ...]) -> str | None:
    output = "\n".join(value for value in (stdout.strip(), stderr.strip()) if value)
    for sensitive_value in sensitive_values:
        if sensitive_value:
            output = output.replace(sensitive_value, "[REDACTED]")
    return output[-WIZARD_ERROR_DETAIL_LENGTH:] or None


def _read_handoff_body(sandbox: SandboxBase, run_id: UUID) -> str | None:
    handoff_result = sandbox.execute(build_read_handoff_command(run_id), timeout_seconds=10)
    if handoff_result.exit_code != 0:
        return None

    handoff_body = handoff_result.stdout.strip()
    return handoff_body or None


def _build_sandbox_config(request: WizardWorkerProvisionRequest, wizard_token: str) -> SandboxConfig:
    environment_variables = {
        "POSTHOG_API_URL": settings.SANDBOX_API_URL or settings.SITE_URL,
        "POSTHOG_PROJECT_ID": str(request.team_id),
        "POSTHOG_WIZARD_API_KEY": wizard_token,
        "POSTHOG_HANDOFF_OUTPUT_PATH": wizard_handoff_output_path(request.run_id),
    }
    if settings.DEBUG and settings.SANDBOX_MCP_URL:
        environment_variables["MCP_URL"] = settings.SANDBOX_MCP_URL

    return SandboxConfig(
        name=f"wizard-{request.run_id}",
        template=SANDBOX_TEMPLATE_BASE,
        default_execution_timeout_seconds=SANDBOX_EXECUTION_TIMEOUT_SECONDS,
        ttl_seconds=SANDBOX_TTL_SECONDS,
        memory_gb=SANDBOX_MEMORY_GB,
        cpu_cores=SANDBOX_CPU_CORES,
        disk_size_gb=SANDBOX_DISK_SIZE_GB,
        environment_variables=environment_variables,
        metadata={
            "purpose": "wizard_run",
            "team_id": str(request.team_id),
            "wizard_run_id": str(request.run_id),
        },
    )
