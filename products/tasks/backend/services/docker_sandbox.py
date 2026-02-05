import os
<<<<<<< ours
import json
||||||| ancestor
=======
import time
>>>>>>> theirs
import uuid
import shlex
import base64
import shutil
import socket
import logging
import tempfile
import subprocess
from collections.abc import Iterable
from typing import Optional

from django.conf import settings

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

from .sandbox import AgentServerResult, ExecutionResult, ExecutionStream, SandboxConfig, SandboxStatus, SandboxTemplate

logger = logging.getLogger(__name__)

WORKING_DIR = "/tmp/workspace"
DEFAULT_TASK_TIMEOUT_SECONDS = 20 * 60  # 20 minutes
DEFAULT_IMAGE_NAME = "posthog-sandbox-base"
NOTEBOOK_IMAGE_NAME = "posthog-sandbox-notebook"
AGENT_SERVER_PORT = 47821  # Arbitrary high port unlikely to conflict with dev servers


class DockerSandbox:
    """
    Docker-based sandbox for local development and testing.
    Implements the same interface as the Modal-based Sandbox.
    """

    id: str
    config: SandboxConfig
    _container_id: str
    _host_port: int | None
    _registry: dict[str, "DockerSandbox"] = {}

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
    def _get_local_twig_packages() -> tuple[str, str, str] | None:
        """
        Get paths to local twig packages for development builds.

        Configure via LOCAL_TWIG_MONOREPO_ROOT pointing to the twig monorepo root.
        Returns tuple of (agent_path, shared_path, git_path) or None if not configured.
        """
        monorepo_root = os.environ.get("LOCAL_TWIG_MONOREPO_ROOT")
        if not monorepo_root or not os.path.isdir(monorepo_root):
            return None

        monorepo_root = os.path.abspath(monorepo_root)
        agent_path = os.path.join(monorepo_root, "packages", "agent")
        shared_path = os.path.join(monorepo_root, "packages", "shared")
        git_path = os.path.join(monorepo_root, "packages", "git")

        missing = []
        if not os.path.isdir(agent_path):
            missing.append(f"agent: {agent_path}")
        if not os.path.isdir(shared_path):
            missing.append(f"shared: {shared_path}")
        if not os.path.isdir(git_path):
            missing.append(f"git: {git_path}")

        if missing:
            raise SandboxProvisionError(
                f"LOCAL_TWIG_MONOREPO_ROOT is set but required packages not found: {', '.join(missing)}",
                {"monorepo_root": monorepo_root, "missing": missing},
            )

        return agent_path, shared_path, git_path

    @staticmethod
    def _build_image_if_needed(image_name: str, dockerfile_path: str) -> None:
        """Build a sandbox image if it doesn't exist."""
        result = DockerSandbox._run(["docker", "images", "-q", image_name])
        if result.stdout.strip():
            return

        logger.info(f"Building {image_name} image (this may take a few minutes)...")

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
    def _build_local_image(agent_path: str, shared_path: str, git_path: str) -> None:
        """Build the local sandbox image with local twig packages."""
        logger.info("Building posthog-sandbox-base-local image with local twig packages...")
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
        """Build the sandbox image, using local packages if LOCAL_TWIG_MONOREPO_ROOT is set."""
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

        local_packages = DockerSandbox._get_local_twig_packages()
        if local_packages:
            agent_path, shared_path, git_path = local_packages
            DockerSandbox._build_local_image(agent_path, shared_path, git_path)
            return "posthog-sandbox-base-local"

        return DEFAULT_IMAGE_NAME

    @staticmethod
    def _get_image(config: SandboxConfig) -> str:
        """Get the image to use, checking for snapshots first."""
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
    def create(config: SandboxConfig) -> "DockerSandbox":
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

            volume_args = []
            runagent_path = os.path.join(settings.BASE_DIR, "products/tasks/scripts/runAgent.mjs")
            if os.path.exists(runagent_path):
                volume_args.extend(["-v", f"{runagent_path}:/scripts/runAgent.mjs:ro"])

            host_port = DockerSandbox._find_available_port()
            port_args = ["-p", f"{host_port}:{AGENT_SERVER_PORT}"]

            docker_args = [
                "docker",
                "run",
                "-d",
                "--name",
                container_name,
                "--add-host",
                "host.docker.internal:host-gateway",
                "-w",
                WORKING_DIR,
                f"--memory={config.memory_gb}g",
                f"--cpus={config.cpu_cores}",
                *env_args,
                *volume_args,
                *port_args,
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
    def get_by_id(sandbox_id: str) -> "DockerSandbox":
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

    def clone_repository(self, repository: str, github_token: Optional[str] = "") -> ExecutionResult:
        if not self.is_running():
            raise RuntimeError("Sandbox not in running state.")

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
            raise RuntimeError("Sandbox not in running state.")

        org, repo = repository.lower().split("/")
        repo_path = f"/tmp/workspace/repos/{org}/{repo}"

        check_result = self.execute(f"test -d {repo_path} && echo 'exists' || echo 'missing'")
        if "missing" in check_result.stdout:
            raise RuntimeError(f"Repository path {repo_path} does not exist. Clone the repository first.")

        agent_setup_command = self._get_setup_command(repo_path)
        setup_command = f"cd {repo_path} && {agent_setup_command}"

        logger.info(f"Setting up repository {repository} in sandbox {self.id}")
        result = self.execute(setup_command, timeout_seconds=15 * 60)

        logger.info(f"Setup completed: exit_code={result.exit_code}")
        if result.exit_code != 0:
            logger.warning(f"Setup stdout:\n{result.stdout}")
            logger.warning(f"Setup stderr:\n{result.stderr}")

        return result

    def is_git_clean(self, repository: str) -> tuple[bool, str]:
        if not self.is_running():
            raise RuntimeError("Sandbox not in running state.")

        org, repo = repository.lower().split("/")
        repo_path = f"/tmp/workspace/repos/{org}/{repo}"

        result = self.execute(f"cd {repo_path} && git status --porcelain")
        is_clean = not result.stdout.strip()

        return is_clean, result.stdout

    def execute_task(self, task_id: str, run_id: str, repository: str, create_pr: bool = True) -> ExecutionResult:
        if not self.is_running():
            raise RuntimeError("Sandbox not in running state.")

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
            logger.warning(f"Task stdout:\n{result.stdout}")
            logger.warning(f"Task stderr:\n{result.stderr}")

        return result

    def start_agent_server(
        self, repository: str, task_id: str, run_id: str, mode: str = "background"
    ) -> AgentServerResult:
        """
        Start the agent-server HTTP server in the sandbox.

        Args:
            repository: Repository in org/repo format
            task_id: Task ID
            run_id: Task run ID
            mode: Execution mode ('background' or 'interactive')

        Returns:
            AgentServerResult with sandbox URL (token is None for Docker)
        """
        if not self.is_running():
            raise RuntimeError("Sandbox not in running state.")

        if self._host_port is None:
            raise RuntimeError("Sandbox was not created with port exposure.")

        org, repo = repository.lower().split("/")
        repo_path = f"/tmp/workspace/repos/{org}/{repo}"

        command = (
            f"cd /scripts && "
            f"nohup npx agent-server --port {AGENT_SERVER_PORT} --repositoryPath {repo_path} "
            f"--taskId {task_id} --runId {run_id} --mode {mode} "
            f"> /tmp/agent-server.log 2>&1 &"
        )

        logger.info(f"Starting agent-server in sandbox {self.id} for {repository}")
        result = self.execute(command, timeout_seconds=30)

        if result.exit_code != 0:
            raise SandboxExecutionError(
                "Failed to start agent-server",
                {"sandbox_id": self.id, "stderr": result.stderr},
                cause=RuntimeError(result.stderr),
            )

        if not self._wait_for_health_check():
            log_result = self.execute("cat /tmp/agent-server.log 2>/dev/null || echo 'No log file'", timeout_seconds=5)
            raise SandboxExecutionError(
                "Agent-server failed to start",
                {"sandbox_id": self.id, "log": log_result.stdout},
                cause=RuntimeError("Health check failed after retries"),
            )

        logger.info(f"Agent-server started on port {self._host_port}")
        return AgentServerResult(url=self.sandbox_url, token=None)  # type: ignore

    def _wait_for_health_check(self, max_attempts: int = 10, delay_seconds: float = 0.5) -> bool:
        """Poll health endpoint until server is ready."""
        health_cmd = f"curl -s -o /dev/null -w '%{{http_code}}' http://localhost:{AGENT_SERVER_PORT}/health"
        for _ in range(max_attempts):
            result = self.execute(health_cmd, timeout_seconds=5)
            if result.stdout.strip() == "200":
                return True
            time.sleep(delay_seconds)
        return False

    def _get_task_command(self, task_id: str, run_id: str, repo_path: str, create_pr: bool = True) -> str:
        create_pr_flag = "true" if create_pr else "false"
        return f"git reset --hard HEAD && IS_SANDBOX=True node /scripts/runAgent.mjs --taskId {task_id} --runId {run_id} --repositoryPath {repo_path} --createPR {create_pr_flag}"

    def _get_setup_command(self, repo_path: str) -> str:
        return f"git reset --hard HEAD && IS_SANDBOX=True && node /scripts/runAgent.mjs --repositoryPath {repo_path} --prompt '{SETUP_REPOSITORY_PROMPT.format(cwd=repo_path, repository=repo_path)}' --max-turns 20"

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

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.destroy()

    def is_running(self) -> bool:
        return self.get_status() == SandboxStatus.RUNNING

    @property
    def name(self) -> str:
        return self.config.name
