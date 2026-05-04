from __future__ import annotations

import os
import json
import uuid
import shlex
import base64
import shutil
import socket
import logging
import tempfile
import subprocess
from collections.abc import Iterable
from typing import TYPE_CHECKING, Optional

from django.conf import settings

if TYPE_CHECKING:
    from products.tasks.backend.temporal.process_task.utils import McpServerConfig

from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.temporal.exceptions import (
    SandboxCleanupError,
    SandboxExecutionError,
    SandboxNotFoundError,
    SandboxProvisionError,
    SandboxTimeoutError,
    SnapshotCreationError,
)

from .agentsh import (
    ENV_FILE,
    ENV_WRAPPER_SCRIPT,
    SESSION_ID_FILE,
    build_exec_prefix,
    build_setup_script,
    generate_config_yaml,
    generate_env_wrapper,
    generate_policy_yaml,
)
from .local_skills import ENV_LOCAL_SKILLS_HOST_PATH, LocalSkillsCache
from .sandbox import (
    WORKING_DIR,
    AgentServerResult,
    ExecutionResult,
    ExecutionStream,
    SandboxBase,
    SandboxConfig,
    SandboxStatus,
    SandboxTemplate,
    build_agent_runtime_env_prefix,
    parse_sandbox_repo_mount_map,
    wait_for_health_check,
)

logger = logging.getLogger(__name__)

DEFAULT_IMAGE_NAME = "posthog-sandbox-base"
NOTEBOOK_IMAGE_NAME = "posthog-sandbox-notebook"
AGENT_SERVER_PORT = 47821  # Arbitrary high port unlikely to conflict with dev servers


class DockerSandbox(SandboxBase):
    """
    Docker-based sandbox for local development and testing.
    Implements the same interface as the Modal-based Sandbox.
    """

    id: str
    config: SandboxConfig
    _container_id: str
    _host_port: int | None
    _registry: dict[str, DockerSandbox] = {}

    def __init__(self, container_id: str, config: SandboxConfig, host_port: int | None = None):
        self._container_id = container_id
        self.id = container_id[:12]
        self.config = config
        self._host_port = host_port
        DockerSandbox._registry[self.id] = self

    @property
    def sandbox_url(self) -> str | None:
        """Return the URL for connecting to the agent server, or None if not available."""
        if self._host_port is None:
            return None
        return f"http://localhost:{self._host_port}"

    @staticmethod
    def _find_available_port() -> int:
        """Find an available port on the host machine."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            return s.getsockname()[1]

    @staticmethod
    def _run(args: list[str], check: bool = False, timeout: int | None = None) -> subprocess.CompletedProcess:
        """Run a subprocess command with logging."""
        logger.debug(f"Running: {' '.join(args)}")
        result = subprocess.run(args, capture_output=True, text=True, check=check, timeout=timeout)
        if result.stdout:
            logger.debug(f"stdout: {result.stdout[:500]}")
        if result.stderr:
            logger.debug(f"stderr: {result.stderr[:500]}")
        if result.returncode != 0:
            logger.debug(f"exit code: {result.returncode}")
        return result

    @staticmethod
    def _get_local_posthog_code_packages() -> tuple[str, str, str, str] | None:
        """
        Get paths to local PostHog Code packages for development builds.

        Configure via LOCAL_POSTHOG_CODE_MONOREPO_ROOT pointing to the PostHog Code monorepo root.
        Returns tuple of (agent_path, shared_path, git_path, enricher_path) or None if not configured.
        """
        monorepo_root = os.environ.get(
            "LOCAL_POSTHOG_CODE_MONOREPO_ROOT", os.environ.get("LOCAL_TWIG_MONOREPO_ROOT", "")
        )
        if not monorepo_root or not os.path.isdir(monorepo_root):
            return None

        monorepo_root = os.path.abspath(monorepo_root)
        agent_path = os.path.join(monorepo_root, "packages", "agent")
        shared_path = os.path.join(monorepo_root, "packages", "shared")
        git_path = os.path.join(monorepo_root, "packages", "git")
        enricher_path = os.path.join(monorepo_root, "packages", "enricher")

        missing = []
        if not os.path.isdir(agent_path):
            missing.append(f"agent: {agent_path}")
        if not os.path.isdir(shared_path):
            missing.append(f"shared: {shared_path}")
        if not os.path.isdir(git_path):
            missing.append(f"git: {git_path}")
        if not os.path.isdir(enricher_path):
            missing.append(f"enricher: {enricher_path}")

        if missing:
            raise SandboxProvisionError(
                f"LOCAL_POSTHOG_CODE_MONOREPO_ROOT is set but required packages not found: {', '.join(missing)}",
                {"monorepo_root": monorepo_root, "missing": missing},
                cause=RuntimeError(f"Missing packages: {', '.join(missing)}"),
            )

        return agent_path, shared_path, git_path, enricher_path

    @staticmethod
    def _build_image_if_needed(image_name: str, dockerfile_path: str) -> None:
        """Build a sandbox image if it doesn't exist."""
        result = DockerSandbox._run(["docker", "images", "-q", image_name])
        if result.stdout.strip():
            return

        logger.info(f"Building {image_name} image (this may take a few minutes)...")

        # Ensure the skills dist directory is populated so the Dockerfile's
        # unconditional COPY picks up real content instead of an empty dir.
        # In CI the directory is pre-populated by the release workflow; in
        # local dev checkouts this triggers a cached build via
        # hogli build:skills.
        LocalSkillsCache().ensure_built()

        DockerSandbox._run(
            [
                "docker",
                "build",
                "-f",
                dockerfile_path,
                "-t",
                image_name,
                str(settings.BASE_DIR),
            ],
            check=True,
        )

    @staticmethod
    def _build_local_image(agent_path: str, shared_path: str, git_path: str, enricher_path: str) -> None:
        """Build the local sandbox image with local PostHog Code packages."""
        logger.info("Building posthog-sandbox-base-local image with local PostHog Code packages...")
        dockerfile_path = os.path.join(
            settings.BASE_DIR, "products/tasks/backend/sandbox/images/Dockerfile.sandbox-local"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            shutil.copytree(
                agent_path,
                os.path.join(tmpdir, "local-agent"),
                ignore=shutil.ignore_patterns("node_modules"),
            )
            shutil.copytree(
                shared_path,
                os.path.join(tmpdir, "local-shared"),
                ignore=shutil.ignore_patterns("node_modules"),
            )
            shutil.copytree(
                git_path,
                os.path.join(tmpdir, "local-git"),
                ignore=shutil.ignore_patterns("node_modules"),
            )
            shutil.copytree(
                enricher_path,
                os.path.join(tmpdir, "local-enricher"),
                ignore=shutil.ignore_patterns("node_modules"),
            )

            DockerSandbox._run(
                [
                    "docker",
                    "build",
                    "-f",
                    dockerfile_path,
                    "-t",
                    "posthog-sandbox-base-local",
                    tmpdir,
                ],
                check=True,
            )

    @staticmethod
    def _ensure_image_exists(template: SandboxTemplate) -> str:
        """Build the sandbox image, using local packages if LOCAL_POSTHOG_CODE_MONOREPO_ROOT is set."""
        if template == SandboxTemplate.NOTEBOOK_BASE:
            dockerfile_path = os.path.join(
                settings.BASE_DIR, "products/tasks/backend/sandbox/images/Dockerfile.sandbox-notebook"
            )
            DockerSandbox._build_image_if_needed(NOTEBOOK_IMAGE_NAME, dockerfile_path)
            return NOTEBOOK_IMAGE_NAME

        dockerfile_path = os.path.join(
            settings.BASE_DIR, "products/tasks/backend/sandbox/images/Dockerfile.sandbox-base"
        )
        DockerSandbox._build_image_if_needed(DEFAULT_IMAGE_NAME, dockerfile_path)

        local_packages = DockerSandbox._get_local_posthog_code_packages()
        if local_packages:
            agent_path, shared_path, git_path, enricher_path = local_packages
            DockerSandbox._build_local_image(agent_path, shared_path, git_path, enricher_path)
            return "posthog-sandbox-base-local"

        return DEFAULT_IMAGE_NAME

    @staticmethod
    def _get_image(config: SandboxConfig) -> str:
        """Get the image to use, checking for snapshots first."""
        if config.snapshot_external_id:
            snapshot_image = f"posthog-sandbox-snapshot:{config.snapshot_external_id}"
            result = DockerSandbox._run(["docker", "images", "-q", snapshot_image])
            if result.stdout.strip():
                return snapshot_image
            logger.warning(f"Resume snapshot image {snapshot_image} not found locally, using base image")

        if config.snapshot_id:
            try:
                snapshot = SandboxSnapshot.objects.get(id=config.snapshot_id)
                if snapshot.status == SandboxSnapshot.Status.COMPLETE:
                    snapshot_image = f"posthog-sandbox-snapshot:{snapshot.external_id}"
                    result = DockerSandbox._run(["docker", "images", "-q", snapshot_image])
                    if result.stdout.strip():
                        return snapshot_image
                    logger.warning(f"Snapshot image {snapshot_image} not found locally, using base image")
            except SandboxSnapshot.DoesNotExist:
                logger.warning(f"Snapshot {config.snapshot_id} not found, using base image")
            except Exception as e:
                logger.warning(f"Failed to load snapshot {config.snapshot_id}: {e}")

        return DockerSandbox._ensure_image_exists(config.template)

    @staticmethod
    def _transform_url_for_docker(url: str) -> str:
        """Transform localhost URLs to be accessible from inside Docker container."""
        url = url.replace("localhost", "host.docker.internal").replace("127.0.0.1", "host.docker.internal")
        # Caddy (port 8010) returns empty responses from inside Docker, use 8000 directly
        url = url.replace(":8010", ":8000")
        return url

    @staticmethod
    def create(config: SandboxConfig) -> DockerSandbox:
        try:
            image = DockerSandbox._get_image(config)
            container_name = f"{config.name}-{uuid.uuid4().hex[:6]}"

            env_args = []
            if config.environment_variables:
                for key, value in config.environment_variables.items():
                    if value is not None:
                        if key == "POSTHOG_API_URL":
                            value = DockerSandbox._transform_url_for_docker(value)
                        env_args.extend(["-e", f"{key}={value}"])

            host_port = DockerSandbox._find_available_port()
            port_args = ["-p", f"{host_port}:{AGENT_SERVER_PORT}"]

            mount_map = parse_sandbox_repo_mount_map()
            volume_args: list[str] = []
            for repo_key, local_path in mount_map.items():
                org, repo = repo_key.split("/", 1)
                container_path = f"{WORKING_DIR}/repos/{org}/{repo}"
                volume_args.extend(["-v", f"{local_path}:{container_path}"])

            # Opt-in bind-mount for local skills. Set by the eval harness so
            # sandboxes see the working-tree skills without rebuilding the
            # base image. Mounts per-subdirectory rather than the parent so
            # the baked-in rendered skills in the image stay visible — only
            # the specific skills the user has on disk get overlaid.
            local_skills_host = os.environ.get(ENV_LOCAL_SKILLS_HOST_PATH)
            if local_skills_host and os.path.isdir(local_skills_host):
                for entry in sorted(os.listdir(local_skills_host)):
                    if entry.startswith(".") or entry == "__pycache__":
                        continue
                    host_skill = os.path.join(local_skills_host, entry)
                    if not os.path.isdir(host_skill):
                        continue
                    container_skill = f"/scripts/plugins/posthog/skills/{entry}"
                    volume_args.extend(["-v", f"{host_skill}:{container_skill}:ro"])

            docker_args = [
                "docker",
                "run",
                "-d",
                "--name",
                container_name,
                "--add-host",
                "host.docker.internal:host-gateway",
                "--cap-add",
                "SYS_PTRACE",
                "-w",
                WORKING_DIR,
                f"--memory={config.memory_gb}g",
                f"--cpus={config.cpu_cores}",
                *env_args,
                *port_args,
                *volume_args,
                image,
                "tail",
                "-f",
                "/dev/null",  # Keep container running
            ]

            result = DockerSandbox._run(docker_args, check=True)
            container_id = result.stdout.strip()

            sandbox = DockerSandbox(container_id=container_id, config=config, host_port=host_port)
            logger.info(f"Created Docker sandbox {sandbox.id} for {config.name} (port {host_port})")

            return sandbox

        except subprocess.CalledProcessError as e:
            logger.exception(f"Failed to create Docker sandbox: {e.stderr}")
            raise SandboxProvisionError(
                "Failed to create Docker sandbox",
                {"config_name": config.name, "error": e.stderr},
                cause=e,
            )
        except Exception as e:
            logger.exception(f"Failed to create Docker sandbox: {e}")
            raise SandboxProvisionError(
                "Failed to create Docker sandbox",
                {"config_name": config.name, "error": str(e)},
                cause=e,
            )

    @staticmethod
    def get_by_id(sandbox_id: str) -> DockerSandbox:
        if sandbox_id in DockerSandbox._registry:
            return DockerSandbox._registry[sandbox_id]

        try:
            result = DockerSandbox._run(
                ["docker", "inspect", "--format", "{{.Id}}", sandbox_id],
                check=True,
            )
            full_id = result.stdout.strip()
            config = SandboxConfig(name=f"sandbox-{sandbox_id}")
            return DockerSandbox(container_id=full_id, config=config)

        except subprocess.CalledProcessError as e:
            raise SandboxNotFoundError(
                f"Docker sandbox {sandbox_id} not found",
                {"sandbox_id": sandbox_id, "error": e.stderr},
                cause=e,
            )

    def get_status(self) -> SandboxStatus:
        try:
            result = DockerSandbox._run(
                ["docker", "inspect", "--format", "{{.State.Running}}", self._container_id],
                check=True,
            )
            is_running = result.stdout.strip().lower() == "true"
            return SandboxStatus.RUNNING if is_running else SandboxStatus.SHUTDOWN
        except subprocess.CalledProcessError:
            return SandboxStatus.SHUTDOWN

    def execute(
        self,
        command: str,
        timeout_seconds: Optional[int] = None,
    ) -> ExecutionResult:
        if not self.is_running():
            raise SandboxExecutionError(
                "Sandbox not in running state.",
                {"sandbox_id": self.id},
                cause=RuntimeError(f"Sandbox {self.id} is not running"),
            )

        if timeout_seconds is None:
            timeout_seconds = self.config.default_execution_timeout_seconds

        try:
            logger.debug(f"Executing in sandbox {self.id}: {command[:100]}...")
            result = DockerSandbox._run(
                ["docker", "exec", self._container_id, "bash", "-c", command],
                timeout=timeout_seconds,
            )

            return ExecutionResult(
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.returncode,
                error=None,
            )

        except subprocess.TimeoutExpired as e:
            raise SandboxTimeoutError(
                f"Execution timed out after {timeout_seconds} seconds",
                {"sandbox_id": self.id, "timeout_seconds": timeout_seconds},
                cause=e,
            )
        except Exception as e:
            logger.exception(f"Failed to execute command: {e}")
            raise SandboxExecutionError(
                "Failed to execute command",
                {"sandbox_id": self.id, "command": command, "error": str(e)},
                cause=e,
            )

    def execute_stream(
        self,
        command: str,
        timeout_seconds: Optional[int] = None,
    ) -> ExecutionStream:
        if not self.is_running():
            raise SandboxExecutionError(
                "Sandbox not in running state.",
                {"sandbox_id": self.id},
                cause=RuntimeError(f"Sandbox {self.id} is not running"),
            )

        if timeout_seconds is None:
            timeout_seconds = self.config.default_execution_timeout_seconds

        try:
            logger.debug(f"Streaming execution in sandbox {self.id}: {command[:100]}...")
            process = subprocess.Popen(
                ["docker", "exec", self._container_id, "bash", "-c", command],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except Exception as e:
            logger.exception(f"Failed to start streaming command: {e}")
            raise SandboxExecutionError(
                "Failed to execute command",
                {"sandbox_id": self.id, "command": command, "error": str(e)},
                cause=e,
            )

        class _DockerExecutionStream:
            def __init__(self, process: subprocess.Popen, timeout: int, sandbox_id: str):
                self._process = process
                self._timeout = timeout
                self._sandbox_id = sandbox_id
                self._stdout_buffer: list[str] = []
                self._stdout_iterated = False

            def iter_stdout(self) -> Iterable[str]:
                if not self._process.stdout:
                    return
                self._stdout_iterated = True
                for line in iter(self._process.stdout.readline, ""):
                    if line == "" and self._process.poll() is not None:
                        break
                    self._stdout_buffer.append(line)
                    yield line
                self._process.stdout.close()

            def wait(self) -> ExecutionResult:
                try:
                    self._process.wait(timeout=self._timeout)
                except subprocess.TimeoutExpired as e:
                    self._process.kill()
                    raise SandboxTimeoutError(
                        f"Execution timed out after {self._timeout} seconds",
                        {"sandbox_id": self._sandbox_id, "timeout_seconds": self._timeout},
                        cause=e,
                    )

                stdout = ""
                if not self._stdout_iterated and self._process.stdout:
                    stdout = self._process.stdout.read()
                else:
                    stdout = "".join(self._stdout_buffer)
                stderr = self._process.stderr.read() if self._process.stderr else ""
                return ExecutionResult(
                    stdout=stdout,
                    stderr=stderr,
                    exit_code=self._process.returncode or 0,
                    error=None,
                )

        return _DockerExecutionStream(process, timeout_seconds, self.id)

    def write_file(self, path: str, payload: bytes) -> ExecutionResult:
        if not self.is_running():
            raise SandboxExecutionError(
                "Sandbox not in running state.",
                {"sandbox_id": self.id},
                cause=RuntimeError(f"Sandbox {self.id} is not running"),
            )

        chunk_size = 50000
        encoded_payload = base64.b64encode(payload).decode("utf-8")
        temp_path = f"{path}.tmp-{uuid.uuid4().hex}"
        result = ExecutionResult(stdout="", stderr="", exit_code=0, error=None)
        for index in range(0, len(encoded_payload), chunk_size):
            chunk = encoded_payload[index : index + chunk_size]
            write_mode = "wb" if index == 0 else "ab"
            command = (
                "python3 - <<'EOF_SANDBOX_WRITE'\n"
                "import base64\n"
                "from pathlib import Path\n"
                f"path = Path({json.dumps(temp_path)})\n"
                "path.parent.mkdir(parents=True, exist_ok=True)\n"
                f"payload = base64.b64decode('{chunk}')\n"
                f"with path.open({json.dumps(write_mode)}) as response_file:\n"
                "    response_file.write(payload)\n"
                "EOF_SANDBOX_WRITE"
            )
            result = self.execute(command, timeout_seconds=self.config.default_execution_timeout_seconds)
            if result.exit_code != 0:
                logger.warning(
                    "sandbox_write_failed",
                    extra={"stdout": result.stdout, "stderr": result.stderr, "sandbox_id": self.id},
                )
                break

        if result.exit_code == 0:
            move_command = f"mv {shlex.quote(temp_path)} {shlex.quote(path)}"
            result = self.execute(move_command, timeout_seconds=self.config.default_execution_timeout_seconds)
            if result.exit_code != 0:
                logger.warning(
                    "sandbox_write_failed",
                    extra={"stdout": result.stdout, "stderr": result.stderr, "sandbox_id": self.id},
                )

        return result

    def clone_repository(self, repository: str, github_token: str | None = "", shallow: bool = True) -> ExecutionResult:
        mount_map = parse_sandbox_repo_mount_map()
        if repository.lower() in mount_map:
            logger.info(f"Repository {repository} is bind-mounted from host, skipping clone")
            return ExecutionResult(stdout="", stderr="", exit_code=0, error=None)
        return super().clone_repository(repository, github_token, shallow)

    def setup_repository(self, repository: str) -> ExecutionResult:
        """No-op: Repository setup is now handled by agent-server."""
        return ExecutionResult(stdout="", stderr="", exit_code=0, error=None)

    def is_git_clean(self, repository: str) -> tuple[bool, str]:
        if not self.is_running():
            raise RuntimeError("Sandbox not in running state.")

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
        """Get connect credentials (URL) for this sandbox.

        For Docker sandboxes, the URL is the localhost URL with the exposed port.
        No token is needed for local Docker sandboxes.
        """
        if not self.is_running():
            raise RuntimeError("Sandbox not in running state.")

        if self._host_port is None:
            raise RuntimeError("Sandbox was not created with port exposure.")

        url = f"http://localhost:{self._host_port}"
        logger.info(f"Got connect credentials for sandbox {self.id}: {url}")
        return AgentServerResult(url=url, token=None)

    def _build_agent_server_command(
        self,
        repo_path: str | None,
        task_id: str,
        run_id: str,
        mode: str,
        create_pr: bool,
        interaction_origin: str | None = None,
        branch: str | None = None,
        runtime_adapter: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        mcp_servers_arg: str = "",
        allowed_domains: list[str] | None = None,
    ) -> str:
        env_prefix = build_agent_runtime_env_prefix(
            interaction_origin=interaction_origin,
            runtime_adapter=runtime_adapter,
            provider=provider,
            model=model,
            reasoning_effort=reasoning_effort,
        )
        create_pr_flag = f" --createPr {shlex.quote('true' if create_pr else 'false')}"
        branch_flag = f" --baseBranch {shlex.quote(branch)}" if branch else ""
        repo_flag = f" --repositoryPath {shlex.quote(repo_path)}" if repo_path else ""
        domains_flag = f" --allowedDomains {shlex.quote(','.join(allowed_domains))}" if allowed_domains else ""
        server_cmd = (
            f"{env_prefix}./node_modules/.bin/agent-server --port {AGENT_SERVER_PORT}{repo_flag} "
            f"--taskId {shlex.quote(task_id)} --runId {shlex.quote(run_id)} --mode {shlex.quote(mode)}"
            f"{create_pr_flag}{branch_flag}{mcp_servers_arg}{domains_flag}"
        )

        inner = f"cd /scripts && {server_cmd} > /tmp/agent-server.log 2>&1"

        if allowed_domains is not None:
            return (
                f"cd /scripts && env -0 > {ENV_FILE} && "
                f"{build_exec_prefix()} {ENV_WRAPPER_SCRIPT} bash -c {shlex.quote(inner)} &"
            )
        else:
            return f"cd /scripts && nohup {server_cmd} > /tmp/agent-server.log 2>&1 &"

    def _launch_and_check(self, command: str) -> bool:
        """Execute the agent-server command and wait for the health check.

        Returns True if the server started successfully, False otherwise.
        """
        result = self.execute(command, timeout_seconds=30)
        if result.exit_code != 0:
            logger.warning(f"Agent-server process failed to launch in sandbox {self.id}: {result.stderr}")
            return False
        return self._wait_for_health_check(max_attempts=20)

    def start_agent_server(
        self,
        repository: str | None,
        task_id: str,
        run_id: str,
        mode: str = "background",
        create_pr: bool = True,
        interaction_origin: str | None = None,
        branch: str | None = None,
        runtime_adapter: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        mcp_configs: list[McpServerConfig] | None = None,
        allowed_domains: list[str] | None = None,
    ) -> None:
        """Start the agent-server HTTP server in the sandbox.

        The sandbox URL should be obtained via get_connect_credentials()
        before calling this method.
        """
        if not self.is_running():
            raise RuntimeError("Sandbox not in running state.")

        if self._host_port is None:
            raise RuntimeError("Sandbox was not created with port exposure.")

        repo_path: str | None = None
        if repository:
            org, repo = repository.lower().split("/")
            repo_path = f"/tmp/workspace/repos/{org}/{repo}"

        if allowed_domains is not None:
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
            runtime_adapter,
            provider,
            model,
            reasoning_effort,
            mcp_servers_arg,
            allowed_domains=allowed_domains,
        )

        logger.info(f"Starting agent-server in sandbox {self.id} for {repository or 'no-repo'}")

        if self._launch_and_check(command):
            logger.info(f"Agent-server started on port {self._host_port}")
            return

        # If branch flag was used, the installed agent-server version may not support --baseBranch.
        # Kill the failed process and retry without it.
        if branch:
            log_result = self.execute("cat /tmp/agent-server.log 2>/dev/null || echo 'No log file'", timeout_seconds=5)
            logger.warning(
                f"Agent-server health check failed for sandbox {self.id} with --baseBranch. "
                f"Retrying without branch flag. Log output:\n{log_result.stdout}"
            )
            self.execute("pkill -f agent-server || true", timeout_seconds=5)

            command = self._build_agent_server_command(
                repo_path,
                task_id,
                run_id,
                mode,
                create_pr,
                interaction_origin,
                branch=None,
                runtime_adapter=runtime_adapter,
                provider=provider,
                model=model,
                reasoning_effort=reasoning_effort,
                mcp_servers_arg=mcp_servers_arg,
                allowed_domains=allowed_domains,
            )
            if self._launch_and_check(command):
                logger.info(f"Agent-server started on port {self._host_port} (without --baseBranch)")
                return

        log_result = self.execute("cat /tmp/agent-server.log 2>/dev/null || echo 'No log file'", timeout_seconds=5)
        logger.warning(f"Agent-server health check failed for sandbox {self.id}. Log output:\n{log_result.stdout}")

        raise SandboxExecutionError(
            "Agent-server failed to start",
            {"sandbox_id": self.id, "log": log_result.stdout},
            cause=RuntimeError("Health check failed after retries"),
        )

    def _setup_agentsh(self, workspace_path: str, allowed_domains: list[str] | None = None) -> None:
        if allowed_domains is not None:
            logger.info(
                "Configuring agentsh in Docker sandbox %s for %d allowed domain(s)", self.id, len(allowed_domains)
            )
        else:
            logger.info("Configuring agentsh in Docker sandbox %s (allow-all mode)", self.id)

        config_yaml = generate_config_yaml(enable_ptrace=False)
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

        logger.info("agentsh daemon started and session created in Docker sandbox %s", self.id)

    def _wait_for_health_check(self, max_attempts: int = 60, poll_interval: float = 0.5) -> bool:
        """Poll health endpoint until server is ready (single remote call)."""

        return wait_for_health_check(self.execute, self.id, AGENT_SERVER_PORT, max_attempts, poll_interval)

    def create_snapshot(self) -> str:
        if not self.is_running():
            raise SandboxExecutionError(
                "Sandbox not in running state.",
                {"sandbox_id": self.id},
                cause=RuntimeError(f"Sandbox {self.id} is not running"),
            )

        try:
            snapshot_id = uuid.uuid4().hex[:12]
            tag = f"posthog-sandbox-snapshot:{snapshot_id}"

            DockerSandbox._run(["docker", "commit", self._container_id, tag], check=True)

            logger.info(f"Created snapshot for sandbox {self.id}, snapshot ID: {snapshot_id}")

            return snapshot_id

        except subprocess.CalledProcessError as e:
            logger.exception(f"Failed to create snapshot: {e.stderr}")
            raise SnapshotCreationError(
                f"Failed to create snapshot: {e.stderr}",
                {"sandbox_id": self.id, "error": e.stderr},
                cause=e,
            )
        except Exception as e:
            logger.exception(f"Failed to create snapshot: {e}")
            raise SnapshotCreationError(
                f"Failed to create snapshot: {e}",
                {"sandbox_id": self.id, "error": str(e)},
                cause=e,
            )

    @staticmethod
    def delete_snapshot(external_id: str) -> None:
        logger.info(f"Deleting snapshot {external_id}")
        try:
            DockerSandbox._run(["docker", "rmi", f"posthog-sandbox-snapshot:{external_id}"])
            logger.info(f"Snapshot {external_id} deleted")
        except Exception as e:
            logger.warning(f"Failed to delete snapshot {external_id}: {e}")

    def destroy(self) -> None:
        try:
            DockerSandbox._run(["docker", "stop", self._container_id], timeout=30)
            DockerSandbox._run(["docker", "rm", self._container_id])
            DockerSandbox._registry.pop(self.id, None)
            logger.info(f"Destroyed Docker sandbox {self.id}")
        except Exception as e:
            logger.exception(f"Failed to destroy Docker sandbox: {e}")
            raise SandboxCleanupError(
                f"Failed to destroy Docker sandbox: {e}",
                {"sandbox_id": self.id, "error": str(e)},
                cause=e,
            )

    def is_running(self) -> bool:
        return self.get_status() == SandboxStatus.RUNNING

    @property
    def name(self) -> str:
        return self.config.name
