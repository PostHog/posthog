from __future__ import annotations

import json
import uuid
import shlex
import shutil
import logging
import tempfile
from collections.abc import Iterable
from functools import lru_cache
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from django.conf import settings

if TYPE_CHECKING:
    from products.tasks.backend.temporal.process_task.utils import McpServerConfig

import modal
import requests

from posthog.exceptions_capture import capture_exception
from posthog.settings import CLOUD_DEPLOYMENT

from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.services.agentsh import (
    ENV_FILE,
    ENV_WRAPPER_SCRIPT,
    SESSION_ID_FILE,
    build_exec_prefix,
    build_setup_script,
    generate_config_yaml,
    generate_env_wrapper,
    generate_policy_yaml,
)
from products.tasks.backend.services.local_packages import get_local_posthog_code_packages
from products.tasks.backend.services.modal_provision_diagnostics import (
    SandboxProvisionDiagnostics,
    capture_modal_output_if_debug,
    summarize_modal_output,
)
from products.tasks.backend.services.sandbox import WORKING_DIR, SandboxBase, wait_for_health_check
from products.tasks.backend.temporal.exceptions import (
    SandboxCleanupError,
    SandboxExecutionError,
    SandboxNotFoundError,
    SandboxProvisionError,
    SandboxTimeoutError,
    SnapshotCreationError,
)

from .sandbox import AgentServerResult, ExecutionResult, ExecutionStream, SandboxConfig, SandboxStatus, SandboxTemplate

logger = logging.getLogger(__name__)

DEFAULT_MODAL_APP_NAME = "posthog-sandbox-default"
NOTEBOOK_MODAL_APP_NAME = "posthog-sandbox-notebook"
SANDBOX_BASE_IMAGE = "ghcr.io/posthog/posthog-sandbox-base"
SANDBOX_NOTEBOOK_IMAGE = "ghcr.io/posthog/posthog-sandbox-notebook"
SANDBOX_IMAGE = SANDBOX_BASE_IMAGE
AGENT_SERVER_PORT = 8080  # Modal connect tokens require port 8080

# Modal region mapping based on cloud deployment
MODAL_REGION_BY_DEPLOYMENT: dict[str | None, str] = {
    "EU": "eu-west",
    "US": "us-east",
}
DEFAULT_MODAL_REGION = "us-east"


def _get_modal_region() -> str:
    return MODAL_REGION_BY_DEPLOYMENT.get(CLOUD_DEPLOYMENT, DEFAULT_MODAL_REGION)


LOCAL_BUILT_SKILLS_PATH = Path("products/posthog_ai/dist/skills")
LOCAL_SOURCE_SKILLS_PATHS = (Path(".agents/skills"), Path("products/posthog_ai/skills"))
LOCAL_MODAL_DOCKERFILES = {
    SandboxTemplate.DEFAULT_BASE: Path("products/tasks/backend/sandbox/images/Dockerfile.sandbox-base"),
    SandboxTemplate.NOTEBOOK_BASE: Path("products/tasks/backend/sandbox/images/Dockerfile.sandbox-notebook"),
}
LOCAL_MODAL_INSTALL_SKILLS_SCRIPT = Path("products/tasks/backend/sandbox/images/install-skills.sh")


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


def _attach_local_package_mounts(image: modal.Image, template: SandboxTemplate) -> modal.Image:
    """Overlay each local package's built `dist/` dir onto the installed package
    via add_local_dir(copy=False). No-op unless `template` is DEFAULT_BASE and
    local packages are available.

    Transitive deps are resolved from the baked /scripts/node_modules/ tree;
    only compiled output is swapped live.
    """
    if template != SandboxTemplate.DEFAULT_BASE:
        return image
    packages = get_local_posthog_code_packages()
    if not packages:
        return image
    for package in packages:
        image = image.add_local_dir(
            str(package.build_output_path),
            package.sandbox_build_output_path,
            copy=False,
        )
    return image


@lru_cache(maxsize=2)
def _get_template_image(template: SandboxTemplate) -> modal.Image:
    registry_image = {
        SandboxTemplate.DEFAULT_BASE: SANDBOX_BASE_IMAGE,
        SandboxTemplate.NOTEBOOK_BASE: SANDBOX_NOTEBOOK_IMAGE,
    }.get(template)
    if registry_image is None:
        raise ValueError(f"Unknown template: {template}")

    if settings.DEBUG:
        dockerfile_path, context_dir = _prepare_local_modal_build_context(template)
        image = modal.Image.from_dockerfile(dockerfile_path, context_dir=context_dir, ignore=[])
    else:
        image = modal.Image.from_registry(_get_sandbox_image_reference(registry_image))

    return _attach_local_package_mounts(image, template)


def _copy_directory_contents(source: Path, destination: Path) -> None:
    if not source.exists():
        return

    destination.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        if child.name == "__pycache__":
            continue

        target = destination / child.name
        if child.is_dir():
            shutil.copytree(child, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
        elif child.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child, target)


def _populate_local_skills_directory(destination: Path) -> None:
    built_skills_dir = Path(settings.BASE_DIR) / LOCAL_BUILT_SKILLS_PATH
    if built_skills_dir.exists() and any(built_skills_dir.iterdir()):
        logger.info(f"Using pre-built skills from {built_skills_dir} for local Modal sandbox builds")
        _copy_directory_contents(built_skills_dir, destination)
        return

    logger.info("Built skills directory empty or missing; falling back to local skill sources for Modal sandbox builds")
    for relative_path in LOCAL_SOURCE_SKILLS_PATHS:
        _copy_directory_contents(Path(settings.BASE_DIR) / relative_path, destination)


@lru_cache(maxsize=2)
def _prepare_local_modal_build_context(template: SandboxTemplate) -> tuple[str, str]:
    dockerfile_relative_path = LOCAL_MODAL_DOCKERFILES.get(template)
    if dockerfile_relative_path is None:
        raise ValueError(f"Unknown template: {template}")

    base_dir = Path(settings.BASE_DIR)
    source_dockerfile_path = base_dir / dockerfile_relative_path
    if not source_dockerfile_path.exists():
        raise FileNotFoundError(f"Dockerfile not found at {source_dockerfile_path}")

    context_dir = Path(tempfile.mkdtemp(prefix=f"posthog-modal-build-{template.value}-"))
    destination_dockerfile_path = context_dir / dockerfile_relative_path
    destination_dockerfile_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_dockerfile_path, destination_dockerfile_path)

    if template == SandboxTemplate.DEFAULT_BASE:
        source_install_script_path = base_dir / LOCAL_MODAL_INSTALL_SKILLS_SCRIPT
        destination_install_script_path = context_dir / LOCAL_MODAL_INSTALL_SKILLS_SCRIPT
        destination_install_script_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_install_script_path, destination_install_script_path)

        _populate_local_skills_directory(context_dir / LOCAL_BUILT_SKILLS_PATH)

    return str(destination_dockerfile_path), str(context_dir)


class ModalSandbox(SandboxBase):
    """
    Modal-based sandbox for production use.
    A box in the cloud. Sand optional.
    """

    id: str
    config: SandboxConfig
    _sandbox: modal.Sandbox
    _app: modal.App
    _sandbox_url: str | None
    provision_diagnostics: SandboxProvisionDiagnostics | None
    DEFAULT_APP_NAME = DEFAULT_MODAL_APP_NAME
    NOTEBOOK_APP_NAME = NOTEBOOK_MODAL_APP_NAME

    def __init__(self, sandbox: modal.Sandbox, config: SandboxConfig, sandbox_url: str | None = None):
        self.id = sandbox.object_id
        self.config = config
        self._sandbox = sandbox
        self._app = type(self)._get_app_for_template(config.template)
        self._sandbox_url = sandbox_url
        self.provision_diagnostics = None

    @property
    def sandbox_url(self) -> str | None:
        """Return the URL for connecting to the agent server, or None if not available."""
        return self._sandbox_url

    @classmethod
    def _get_default_app(cls) -> modal.App:
        return modal.App.lookup(cls.DEFAULT_APP_NAME, create_if_missing=True)

    @classmethod
    def _get_app_for_template(cls, template: SandboxTemplate) -> modal.App:
        if template == SandboxTemplate.NOTEBOOK_BASE:
            return modal.App.lookup(cls.NOTEBOOK_APP_NAME, create_if_missing=True)
        return cls._get_default_app()

    @classmethod
    def create(cls, config: SandboxConfig) -> ModalSandbox:
        try:
            app = cls._get_app_for_template(config.template)
            base_image = _get_template_image(config.template)
            image = base_image
            used_snapshot_image = False

            if config.snapshot_external_id:
                try:
                    image = _attach_local_package_mounts(
                        modal.Image.from_id(config.snapshot_external_id), config.template
                    )
                    used_snapshot_image = True
                except Exception as e:
                    logger.warning(f"Failed to load resume snapshot image {config.snapshot_external_id}: {e}")
                    capture_exception(e)
            elif config.snapshot_id:
                snapshot = SandboxSnapshot.objects.get(id=config.snapshot_id)
                if snapshot.status == SandboxSnapshot.Status.COMPLETE:
                    try:
                        image = _attach_local_package_mounts(modal.Image.from_id(snapshot.external_id), config.template)
                        used_snapshot_image = True
                    except Exception as e:
                        logger.warning(f"Failed to load snapshot image {snapshot.external_id}: {e}")
                        capture_exception(e)

            secrets = []
            if config.environment_variables:
                env_dict = cast(dict[str, str | None], config.environment_variables)
                secret = modal.Secret.from_dict(env_dict)
                secrets.append(secret)

            sandbox_name = f"{config.name}-{uuid.uuid4().hex[:6]}"

            region = _get_modal_region()

            create_kwargs: dict[str, object] = {
                "app": app,
                "name": sandbox_name,
                "image": image,
                "timeout": config.ttl_seconds,
                "cpu": float(config.cpu_cores),
                "memory": int(config.memory_gb * 1024),
                "region": region,
                "verbose": True,
            }

            if secrets:
                create_kwargs["secrets"] = secrets

            try:
                modal_output: StringIO | None
                with capture_modal_output_if_debug() as modal_output:
                    sb = modal.Sandbox.create(**create_kwargs)  # type: ignore[arg-type]
            except Exception as e:
                if not used_snapshot_image:
                    raise
                logger.warning(f"Failed to create sandbox with snapshot image, falling back to base image: {e}")
                capture_exception(e)
                create_kwargs["image"] = base_image
                with capture_modal_output_if_debug() as modal_output:
                    sb = modal.Sandbox.create(**create_kwargs)  # type: ignore[arg-type]

            if config.metadata:
                sb.set_tags(config.metadata)

            sandbox = cls(sandbox=sb, config=config)
            if modal_output is not None:
                sandbox.provision_diagnostics = summarize_modal_output(modal_output.getvalue())

            logger.info(f"Created sandbox {sandbox.id} for {config.name}")

            return sandbox

        except Exception as e:
            logger.exception(f"Failed to create sandbox: {e}")
            raise SandboxProvisionError(
                f"Failed to create sandbox", {"config_name": config.name, "error": str(e)}, cause=e
            )

    @staticmethod
    def get_by_id(sandbox_id: str) -> ModalSandbox:
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

    def execute_stream(
        self,
        command: str,
        timeout_seconds: int | None = None,
    ) -> ExecutionStream:
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

        class _ModalExecutionStream:
            def __init__(self, process: Any):
                self._process = process
                self._stdout_buffer: list[str] = []
                self._stdout_iterated = False

            def iter_stdout(self) -> Iterable[str]:
                self._stdout_iterated = True
                for line in self._process.stdout:
                    output = line.decode("utf-8") if isinstance(line, bytes) else line
                    self._stdout_buffer.append(output)
                    yield output

            def wait(self) -> ExecutionResult:
                self._process.wait()
                if not self._stdout_iterated:
                    stdout = self._process.stdout.read()
                    stdout_text = stdout.decode("utf-8") if isinstance(stdout, bytes) else stdout
                else:
                    stdout_text = "".join(self._stdout_buffer)

                stderr = self._process.stderr.read()
                stderr_text = stderr.decode("utf-8") if isinstance(stderr, bytes) else stderr
                return ExecutionResult(
                    stdout=stdout_text,
                    stderr=stderr_text,
                    exit_code=self._process.returncode,
                    error=None,
                )

        return _ModalExecutionStream(process)

    def write_file(self, path: str, payload: bytes) -> ExecutionResult:
        if not self.is_running():
            raise SandboxExecutionError(
                "Sandbox not in running state.",
                {"sandbox_id": self.id},
                cause=RuntimeError(f"Sandbox {self.id} is not running"),
            )

        temp_path = f"{path}.tmp-{uuid.uuid4().hex}"
        try:
            with self._sandbox.open(temp_path, "wb") as file_handle:
                file_handle.write(payload)
            mv_command = f"mv {shlex.quote(temp_path)} {shlex.quote(path)}"
            result = self.execute(mv_command, timeout_seconds=self.config.default_execution_timeout_seconds)
            if result.exit_code != 0:
                logger.warning(
                    "sandbox_write_failed",
                    extra={"stdout": result.stdout, "stderr": result.stderr, "sandbox_id": self.id},
                )
            return result
        except Exception as e:
            capture_exception(e)
            logger.exception(f"Failed to write file to sandbox: {e}")
            raise SandboxExecutionError(
                "Failed to write file",
                {"sandbox_id": self.id, "path": path, "error": str(e)},
                cause=e,
            )

    def setup_repository(self, repository: str) -> ExecutionResult:
        """No-op: Repository setup is now handled by agent-server."""
        return ExecutionResult(stdout="", stderr="", exit_code=0, error=None)

    def is_git_clean(self, repository: str) -> tuple[bool, str]:
        if not self.is_running():
            raise RuntimeError(f"Sandbox not in running state.")

        org, repo = repository.lower().split("/")
        repo_path = f"/tmp/workspace/repos/{org}/{repo}"

        result = self.execute(f"cd {shlex.quote(repo_path)} && git status --porcelain")
        is_clean = not result.stdout.strip()

        return is_clean, result.stdout

    def execute_task(
        self, task_id: str, run_id: str, repository: str | None = None, create_pr: bool = True
    ) -> ExecutionResult:
        """No-op: Task execution is now handled by agent-server."""
        return ExecutionResult(stdout="", stderr="", exit_code=0, error=None)

    def get_connect_credentials(self) -> AgentServerResult:
        """Get connect credentials (URL and token) for this sandbox.

        Modal connect tokens provide authenticated HTTP access to port 8080 in the sandbox.
        Should be called after sandbox creation to get the URL and token needed for connection.
        """
        if not self.is_running():
            raise RuntimeError("Sandbox not in running state.")

        credentials = self._sandbox.create_connect_token()
        self._sandbox_url = credentials.url

        logger.info(f"Got connect credentials for sandbox {self.id}: {credentials.url}")
        return AgentServerResult(url=credentials.url, token=credentials.token)

    def _build_agent_server_command(
        self,
        repo_path: str | None,
        task_id: str,
        run_id: str,
        mode: str,
        create_pr: bool,
        interaction_origin: str | None = None,
        branch: str | None = None,
        mcp_servers_arg: str = "",
        allowed_domains: list[str] | None = None,
    ) -> str:
        env_prefix = (
            f"env POSTHOG_CODE_INTERACTION_ORIGIN={shlex.quote(interaction_origin)} " if interaction_origin else ""
        )
        create_pr_flag = f" --createPr {shlex.quote('true' if create_pr else 'false')}"
        repo_flag = f" --repositoryPath {shlex.quote(repo_path)}" if repo_path else ""
        branch_flag = f" --baseBranch {shlex.quote(branch)}" if branch else ""
        domains_flag = f" --allowedDomains {shlex.quote(','.join(allowed_domains))}" if allowed_domains else ""
        server_cmd = (
            f"{env_prefix}./node_modules/.bin/agent-server --port {AGENT_SERVER_PORT}{repo_flag} "
            f"--taskId {shlex.quote(task_id)} --runId {shlex.quote(run_id)} --mode {shlex.quote(mode)}"
            f"{create_pr_flag}{branch_flag}{mcp_servers_arg}{domains_flag}"
        )

        inner = f"cd /scripts && {server_cmd} > /tmp/agent-server.log 2>&1"

        if allowed_domains:
            return (
                f"cd /scripts && env -0 > {ENV_FILE} && "
                f"{build_exec_prefix()} {ENV_WRAPPER_SCRIPT} bash -c {shlex.quote(inner)} &"
            )
        else:
            return f"cd /scripts && nohup {server_cmd} > /tmp/agent-server.log 2>&1 &"

    def _launch_and_check(self, command: str) -> bool:
        result = self.execute(command, timeout_seconds=30)
        if result.exit_code != 0:
            logger.warning(f"Agent-server process failed to launch in sandbox {self.id}: {result.stderr}")
            return False
        return self._wait_for_health_check()

    def start_agent_server(
        self,
        repository: str | None,
        task_id: str,
        run_id: str,
        mode: str = "background",
        create_pr: bool = True,
        interaction_origin: str | None = None,
        branch: str | None = None,
        mcp_configs: list[McpServerConfig] | None = None,
        allowed_domains: list[str] | None = None,
    ) -> None:
        """Start the agent-server HTTP server in the sandbox.

        The sandbox URL and token should be obtained via get_connect_credentials()
        before calling this method. The agent-server runs on port 8080 which is
        exposed via Modal's connect token mechanism.
        """
        if not self.is_running():
            raise RuntimeError("Sandbox not in running state.")

        repo_path: str | None = None
        if repository:
            org, repo = repository.lower().split("/")
            repo_path = f"/tmp/workspace/repos/{org}/{repo}"

        if allowed_domains:
            self._setup_agentsh(WORKING_DIR, allowed_domains)

        mcp_servers_arg = ""
        if mcp_configs:
            mcp_json = json.dumps([c.to_dict() for c in mcp_configs])
            mcp_servers_arg = f" --mcpServers {shlex.quote(mcp_json)}"

        command = self._build_agent_server_command(
            repo_path,
            task_id,
            run_id,
            mode,
            create_pr,
            interaction_origin,
            branch,
            mcp_servers_arg,
            allowed_domains=allowed_domains,
        )

        logger.info(f"Starting agent-server in sandbox {self.id} for {repository or 'no-repo'}")
        if not self._launch_and_check(command):
            log_result = self.execute("cat /tmp/agent-server.log 2>/dev/null || echo 'No log file'", timeout_seconds=5)
            raise SandboxExecutionError(
                "Agent-server failed to start",
                {"sandbox_id": self.id, "log": log_result.stdout},
                cause=RuntimeError("Health check failed after retries"),
            )

        logger.info(f"Agent-server started in sandbox {self.id}")

    def _setup_agentsh(self, workspace_path: str, allowed_domains: list[str] | None = None) -> None:
        if allowed_domains:
            logger.info("Configuring agentsh in sandbox %s for %d allowed domain(s)", self.id, len(allowed_domains))
        else:
            logger.info("Configuring agentsh in sandbox %s (allow-all mode)", self.id)

        config_yaml = generate_config_yaml(enable_ptrace=True, full_trace=True)
        policy_yaml = generate_policy_yaml(allowed_domains)

        self.execute("pkill -f 'agentsh server' || true", timeout_seconds=5)
        self.execute("mkdir -p /etc/agentsh/policies /var/log/agentsh /var/lib/agentsh/sessions", timeout_seconds=5)
        self.write_file("/etc/agentsh/config.yaml", config_yaml.encode())
        self.write_file("/etc/agentsh/policies/default.yaml", policy_yaml.encode())
        self.write_file(ENV_WRAPPER_SCRIPT, generate_env_wrapper().encode())
        self.execute(f"chmod +x {ENV_WRAPPER_SCRIPT}", timeout_seconds=5)

        setup_script = build_setup_script(workspace_path)
        result = self.execute(setup_script, timeout_seconds=30)
        if result.exit_code != 0:
            agentsh_log = self.execute("cat /var/log/agentsh/agentsh.log 2>/dev/null || true", timeout_seconds=5)
            raise SandboxExecutionError(
                "Failed to start agentsh daemon",
                {
                    "sandbox_id": self.id,
                    "stderr": result.stderr,
                    "stdout": result.stdout,
                    "agentsh_log": agentsh_log.stdout,
                },
                cause=RuntimeError(result.stderr),
            )

        session_check = self.execute(f"cat {SESSION_ID_FILE}", timeout_seconds=5)
        if session_check.exit_code != 0 or not session_check.stdout.strip():
            agentsh_log = self.execute("cat /var/log/agentsh/agentsh.log 2>/dev/null || true", timeout_seconds=5)
            raise SandboxExecutionError(
                "Failed to create agentsh session",
                {
                    "sandbox_id": self.id,
                    "stderr": session_check.stderr,
                    "agentsh_log": agentsh_log.stdout,
                },
                cause=RuntimeError("agentsh session create failed"),
            )

        logger.info("agentsh daemon started and session created in sandbox %s", self.id)

    def _wait_for_health_check(self, max_attempts: int = 60, poll_interval: float = 0.5) -> bool:
        """Poll health endpoint until server is ready (single remote call)."""
        return wait_for_health_check(self.execute, self.id, AGENT_SERVER_PORT, max_attempts, poll_interval)

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

    def is_running(self) -> bool:
        return self.get_status() == SandboxStatus.RUNNING

    @property
    def name(self) -> str:
        return self.config.name
