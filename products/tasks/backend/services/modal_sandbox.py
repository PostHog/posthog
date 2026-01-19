import os
import uuid
import logging
from functools import lru_cache
from typing import cast

from django.conf import settings

import modal
import requests

from posthog.exceptions_capture import capture_exception

from products.tasks.backend.constants import SETUP_REPOSITORY_PROMPT
from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.temporal.exceptions import (
    SandboxCleanupError,
    SandboxExecutionError,
    SandboxNotFoundError,
    SandboxProvisionError,
    SandboxTimeoutError,
    SnapshotCreationError,
)

from .sandbox import ExecutionResult, SandboxConfig, SandboxStatus, SandboxTemplate

logger = logging.getLogger(__name__)

WORKING_DIR = "/tmp/workspace"
DEFAULT_TASK_TIMEOUT_SECONDS = 20 * 60  # 20 minutes
DEFAULT_MODAL_APP_NAME = "posthog-sandbox-default"
NOTEBOOK_MODAL_APP_NAME = "posthog-sandbox-notebook"
SANDBOX_BASE_IMAGE = "ghcr.io/posthog/posthog-sandbox-base"
SANDBOX_NOTEBOOK_IMAGE = "ghcr.io/posthog/posthog-sandbox-notebook"
SANDBOX_IMAGE = SANDBOX_BASE_IMAGE


@lru_cache(maxsize=2)
def _get_sandbox_image_reference(image: str = SANDBOX_IMAGE) -> str:
    """Modal caches sandbox images indefinitely. This function resolves the digest of the master tag
    so Modal fetches the correct version. Queries GHCR once per deployment.
    """
    image_repo = image.replace("ghcr.io/", "")
    try:
        token_resp = requests.get(
            f"https://ghcr.io/token?service=ghcr.io&scope=repository:{image_repo}:pull",
            timeout=10,
        )
        if token_resp.status_code != 200:
            logger.warning(f"Failed to get GHCR token: status={token_resp.status_code}")
            return f"{image}:master"

        token = token_resp.json().get("token")
        if not token:
            logger.warning("GHCR token response missing token field")
            return f"{image}:master"

        manifest_resp = requests.get(
            f"https://ghcr.io/v2/{image_repo}/manifests/master",
            headers={
                "Accept": "application/vnd.oci.image.index.v1+json",
                "Authorization": f"Bearer {token}",
            },
            timeout=10,
        )
        if manifest_resp.status_code == 200:
            digest = manifest_resp.headers.get("Docker-Content-Digest")
            if digest:
                logger.info(f"Resolved sandbox image digest for {image_repo}: {digest}")
                return f"{image}@{digest}"
        logger.warning(f"Failed to get sandbox image digest: status={manifest_resp.status_code}")
    except Exception as e:
        logger.warning(f"Failed to fetch sandbox image digest: {e}")

    return f"{image}:master"


def _get_template_image(template: SandboxTemplate) -> modal.Image:
    if template == SandboxTemplate.DEFAULT_BASE:
        if settings.DEBUG:
            dockerfile_path = os.path.join(
                settings.BASE_DIR, "products/tasks/backend/sandbox/images/Dockerfile.sandbox-base"
            )

            if not os.path.exists(dockerfile_path):
                raise FileNotFoundError(f"Dockerfile not found at {dockerfile_path}")

            return modal.Image.from_dockerfile(dockerfile_path, force_build=True)
        else:
            return modal.Image.from_registry(_get_sandbox_image_reference(SANDBOX_BASE_IMAGE))

    if template == SandboxTemplate.NOTEBOOK_BASE:
        if settings.DEBUG:
            dockerfile_path = os.path.join(
                settings.BASE_DIR, "products/tasks/backend/sandbox/images/Dockerfile.sandbox-notebook"
            )

            if not os.path.exists(dockerfile_path):
                raise FileNotFoundError(f"Dockerfile not found at {dockerfile_path}")

            return modal.Image.from_dockerfile(dockerfile_path, force_build=True)
        else:
            return modal.Image.from_registry(_get_sandbox_image_reference(SANDBOX_NOTEBOOK_IMAGE))

    raise ValueError(f"Unknown template: {template}")


class ModalSandbox:
    """
    Modal-based sandbox for production use.
    A box in the cloud. Sand optional.
    """

    id: str
    config: SandboxConfig
    _sandbox: modal.Sandbox
    _app: modal.App

    def __init__(self, sandbox: modal.Sandbox, config: SandboxConfig):
        self.id = sandbox.object_id
        self.config = config
        self._sandbox = sandbox
        self._app = ModalSandbox._get_app_for_template(config.template)

    @staticmethod
    def _get_default_app() -> modal.App:
        return modal.App.lookup(DEFAULT_MODAL_APP_NAME, create_if_missing=True)

    @staticmethod
    def _get_app_for_template(template: SandboxTemplate) -> modal.App:
        if template == SandboxTemplate.NOTEBOOK_BASE:
            return modal.App.lookup(NOTEBOOK_MODAL_APP_NAME, create_if_missing=True)
        return ModalSandbox._get_default_app()

    @staticmethod
    def create(config: SandboxConfig) -> "ModalSandbox":
        try:
            app = ModalSandbox._get_app_for_template(config.template)
            image = _get_template_image(config.template)

            if config.snapshot_id:
                snapshot = SandboxSnapshot.objects.get(id=config.snapshot_id)
                if snapshot.status == SandboxSnapshot.Status.COMPLETE:
                    try:
                        image = modal.Image.from_id(snapshot.external_id)
                    except Exception as e:
                        logger.warning(f"Failed to load snapshot image {snapshot.external_id}: {e}")
                        capture_exception(e)

            secrets = []
            if config.environment_variables:
                env_dict = cast(dict[str, str | None], config.environment_variables)
                secret = modal.Secret.from_dict(env_dict)
                secrets.append(secret)

            sandbox_name = f"{config.name}-{uuid.uuid4().hex[:6]}"

            create_kwargs: dict[str, object] = {
                "app": app,
                "name": sandbox_name,
                "image": image,
                "timeout": config.ttl_seconds,
                "cpu": float(config.cpu_cores),
                "memory": int(config.memory_gb * 1024),
                "verbose": True,
            }

            if secrets:
                create_kwargs["secrets"] = secrets

            sb = modal.Sandbox.create(**create_kwargs)  # type: ignore[arg-type]

            if config.metadata:
                sb.set_tags(config.metadata)

            sandbox = ModalSandbox(sandbox=sb, config=config)

            logger.info(f"Created sandbox {sandbox.id} for {config.name}")

            return sandbox

        except Exception as e:
            logger.exception(f"Failed to create sandbox: {e}")
            raise SandboxProvisionError(
                f"Failed to create sandbox", {"config_name": config.name, "error": str(e)}, cause=e
            )

    @staticmethod
    def get_by_id(sandbox_id: str) -> "ModalSandbox":
        try:
            sb = modal.Sandbox.from_id(sandbox_id)

            config = SandboxConfig(name=getattr(sb, "name", f"sandbox-{sandbox_id}"))

            return ModalSandbox(sandbox=sb, config=config)

        except Exception as e:
            logger.exception(f"Failed to retrieve sandbox {sandbox_id}: {e}")
            raise SandboxNotFoundError(
                f"Sandbox {sandbox_id} not found", {"sandbox_id": sandbox_id, "error": str(e)}, cause=e
            )

    def get_status(self) -> SandboxStatus:
        return SandboxStatus.RUNNING if self._sandbox.poll() is None else SandboxStatus.SHUTDOWN

    def execute(
        self,
        command: str,
        timeout_seconds: int | None = None,
    ) -> ExecutionResult:
        if not self.is_running():
            raise SandboxExecutionError(
                f"Sandbox not in running state.",
                {"sandbox_id": self.id},
                cause=RuntimeError(f"Sandbox {self.id} is not running"),
            )

        if timeout_seconds is None:
            timeout_seconds = self.config.default_execution_timeout_seconds

        try:
            process = self._sandbox.exec("bash", "-c", command, timeout=timeout_seconds)

            process.wait()

            stdout = process.stdout.read()
            stderr = process.stderr.read()

            result = ExecutionResult(
                stdout=stdout.decode("utf-8") if isinstance(stdout, bytes) else stdout,  # type: ignore[unreachable]
                stderr=stderr.decode("utf-8") if isinstance(stderr, bytes) else stderr,  # type: ignore[unreachable]
                exit_code=process.returncode,
                error=None,
            )

            return result

        except TimeoutError as e:
            capture_exception(e)
            raise SandboxTimeoutError(
                f"Execution timed out after {timeout_seconds} seconds",
                {"sandbox_id": self.id, "timeout_seconds": timeout_seconds},
                cause=e,
            )
        except Exception as e:
            capture_exception(e)
            logger.exception(f"Failed to execute command: {e}")
            raise SandboxExecutionError(
                f"Failed to execute command",
                {"sandbox_id": self.id, "command": command, "error": str(e)},
                cause=e,
            )

    def execute_background(self, command: str) -> None:
        if not self.is_running():
            raise SandboxExecutionError(
                f"Sandbox not in running state.",
                {"sandbox_id": self.id},
                cause=RuntimeError(f"Sandbox {self.id} is not running"),
            )

        try:
            bg_command = f"nohup {command} > /tmp/agent-server.log 2>&1 &"
            process = self._sandbox.exec("bash", "-c", bg_command, timeout=10)
            process.wait()
        except Exception as e:
            capture_exception(e)
            logger.exception(f"Failed to execute background command: {e}")
            raise SandboxExecutionError(
                f"Failed to execute background command",
                {"sandbox_id": self.id, "command": command, "error": str(e)},
                cause=e,
            )

    def clone_repository(self, repository: str, github_token: str | None = "") -> ExecutionResult:
        if not self.is_running():
            raise RuntimeError(f"Sandbox not in running state.")

        org, repo = repository.lower().split("/")
        repo_url = (
            f"https://x-access-token:{github_token}@github.com/{org}/{repo}.git"
            if github_token
            else f"https://github.com/{org}/{repo}.git"
        )

        target_path = f"/tmp/workspace/repos/{org}/{repo}"

        clone_command = (
            f"rm -rf {target_path} && "
            f"mkdir -p /tmp/workspace/repos/{org} && "
            f"cd /tmp/workspace/repos/{org} && "
            f"git clone {repo_url} {repo}"
        )

        logger.info(f"Cloning repository {repository} to {target_path} in sandbox {self.id}")
        return self.execute(clone_command, timeout_seconds=5 * 60)

    def setup_repository(self, repository: str) -> ExecutionResult:
        if not self.is_running():
            raise RuntimeError(f"Sandbox not in running state.")

        org, repo = repository.lower().split("/")
        repo_path = f"/tmp/workspace/repos/{org}/{repo}"

        check_result = self.execute(f"test -d {repo_path} && echo 'exists' || echo 'missing'")
        if "missing" in check_result.stdout:
            raise RuntimeError(f"Repository path {repo_path} does not exist. Clone the repository first.")

        agent_setup_command = self._get_setup_command(repo_path)
        setup_command = f"cd {repo_path} && {agent_setup_command}"

        result = self.execute(setup_command, timeout_seconds=15 * 60)

        return result

    def is_git_clean(self, repository: str) -> tuple[bool, str]:
        if not self.is_running():
            raise RuntimeError(f"Sandbox not in running state.")

        org, repo = repository.lower().split("/")
        repo_path = f"/tmp/workspace/repos/{org}/{repo}"

        result = self.execute(f"cd {repo_path} && git status --porcelain")
        is_clean = not result.stdout.strip()

        return is_clean, result.stdout

    def execute_task(self, task_id: str, run_id: str, repository: str, create_pr: bool = True) -> ExecutionResult:
        if not self.is_running():
            raise RuntimeError(f"Sandbox not in running state.")

        org, repo = repository.lower().split("/")
        repo_path = f"/tmp/workspace/repos/{org}/{repo}"

        task_command = self._get_task_command(task_id, run_id, repo_path, create_pr)
        command = f"cd {repo_path} && {task_command}"

        logger.info(f"Executing task {task_id} for run {run_id} in {repo_path} in sandbox {self.id}")
        logger.info(f"Task command: {task_command}")
        logger.info(f"Full command: {command}")

        result = self.execute(command, timeout_seconds=DEFAULT_TASK_TIMEOUT_SECONDS)

        logger.info(f"Task execution completed: exit_code={result.exit_code}")
        logger.info(f"Task stdout length: {len(result.stdout)} chars")
        logger.info(f"Task stderr length: {len(result.stderr)} chars")
        if result.exit_code != 0:
            logger.warning(f"Task stdout preview: {result.stdout[:500]}")
            logger.warning(f"Task stderr preview: {result.stderr[:500]}")

        return result

    def _get_task_command(self, task_id: str, run_id: str, repo_path: str, create_pr: bool = True) -> str:
        create_pr_flag = "true" if create_pr else "false"
        return f"git reset --hard HEAD && IS_SANDBOX=True node /scripts/runAgent.mjs --taskId {task_id} --runId {run_id} --repositoryPath {repo_path} --createPR {create_pr_flag}"

    def _get_setup_command(self, repo_path: str) -> str:
        return f"git reset --hard HEAD && IS_SANDBOX=True && node /scripts/runAgent.mjs --repositoryPath {repo_path} --prompt '{SETUP_REPOSITORY_PROMPT.format(cwd=repo_path, repository=repo_path)}' --max-turns 20"

    def create_snapshot(self) -> str:
        if not self.is_running():
            raise SandboxExecutionError(
                f"Sandbox not in running state.",
                {"sandbox_id": self.id},
                cause=RuntimeError(f"Sandbox {self.id} is not running"),
            )

        try:
            image = self._sandbox.snapshot_filesystem()

            snapshot_id = image.object_id

            logger.info(f"Created snapshot for sandbox {self.id}, snapshot ID: {snapshot_id}")

            return snapshot_id

        except Exception as e:
            logger.exception(f"Failed to create snapshot: {e}")
            raise SnapshotCreationError(
                f"Failed to create snapshot: {e}", {"sandbox_id": self.id, "error": str(e)}, cause=e
            )

    @staticmethod
    def delete_snapshot(external_id: str) -> None:
        logger.info(f"Deleting snapshot {external_id}")
        try:
            logger.info(f"Snapshot {external_id} marked for cleanup")
        except Exception as e:
            logger.warning(f"Failed to delete snapshot {external_id}: {e}")

    def destroy(self) -> None:
        try:
            self._sandbox.terminate()
            logger.info(f"Destroyed sandbox {self.id}")
        except Exception as e:
            logger.exception(f"Failed to destroy sandbox: {e}")
            raise SandboxCleanupError(
                f"Failed to destroy sandbox: {e}", {"sandbox_id": self.id, "error": str(e)}, cause=e
            )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.destroy()

    def is_running(self) -> bool:
        return self.get_status() == SandboxStatus.RUNNING

    @property
    def name(self) -> str:
        return self.config.name
