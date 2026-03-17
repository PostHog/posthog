"""Docker integration tests for agentsh domain enforcement.

Uses DockerSandbox to create a real container with --cap-add SYS_PTRACE,
sets up agentsh via _setup_agentsh(), and verifies domain allowlisting
is enforced at the syscall level.

The image is built from the Dockerfile on first run (or when stale).
Requires Docker daemon to be running.
"""

import shutil
import hashlib
import subprocess

import pytest

DOCKER_AVAILABLE = shutil.which("docker") is not None
IMAGE_NAME = "posthog-sandbox-base-test"
DOCKERFILE_PATH = "products/tasks/backend/sandbox/images/Dockerfile.sandbox-base"


def _dockerfile_hash() -> str:
    try:
        with open(DOCKERFILE_PATH, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:12]
    except FileNotFoundError:
        return ""


def _build_image_if_needed() -> bool:
    if not DOCKER_AVAILABLE:
        return False

    tag = f"{IMAGE_NAME}:{_dockerfile_hash()}"

    inspect = subprocess.run(
        ["docker", "image", "inspect", tag],
        capture_output=True,
        timeout=10,
    )
    if inspect.returncode == 0:
        return True

    result = subprocess.run(
        [
            "docker",
            "build",
            "-t",
            tag,
            "-t",
            f"{IMAGE_NAME}:latest",
            "-f",
            DOCKERFILE_PATH,
            "--build-arg",
            "COMMIT_HASH=test",
            ".",
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        pytest.skip(f"Failed to build sandbox image: {result.stderr[-500:]}")
    return True


@pytest.fixture(scope="session", autouse=False)
def sandbox_image():
    if not DOCKER_AVAILABLE:
        pytest.skip("Docker not available")
    _build_image_if_needed()
    return IMAGE_NAME


@pytest.mark.skipif(not DOCKER_AVAILABLE, reason="Docker not available")
class TestAgentshDockerEnforcement:
    """Integration tests that verify agentsh blocks/allows network access via DockerSandbox."""

    @pytest.fixture(autouse=True)
    def _settings(self, settings):
        settings.DEBUG = True
        settings.SANDBOX_PROVIDER = "docker"

    def _create_sandbox(self, sandbox_image):
        from products.tasks.backend.services.docker_sandbox import DockerSandbox
        from products.tasks.backend.services.sandbox import SandboxConfig

        config = SandboxConfig(name="test-agentsh")
        return DockerSandbox.create(config)

    def _setup_agentsh_and_exec(self, sandbox, test_command: str, allowed_domains: list[str]):
        repo_path = "/tmp/workspace"
        sandbox._setup_agentsh(repo_path, allowed_domains)
        return sandbox.execute(
            f"agentsh exec $(cat /tmp/agentsh-session-id) -- {test_command}",
            timeout_seconds=30,
        )

    @pytest.mark.django_db
    def test_allows_permitted_domain(self, sandbox_image):
        sandbox = self._create_sandbox(sandbox_image)
        try:
            result = self._setup_agentsh_and_exec(
                sandbox,
                "curl -s -o /dev/null -w '%{http_code}' https://github.com",
                allowed_domains=["github.com"],
            )
            assert result.exit_code == 0, f"Expected success for github.com, got: {result.stderr}"
        finally:
            sandbox.destroy()

    @pytest.mark.django_db
    def test_blocks_denied_domain(self, sandbox_image):
        sandbox = self._create_sandbox(sandbox_image)
        try:
            result = self._setup_agentsh_and_exec(
                sandbox,
                "curl -s --max-time 5 https://evil.com",
                allowed_domains=["github.com"],
            )
            assert result.exit_code != 0, "Expected curl to fail for denied domain"
        finally:
            sandbox.destroy()

    @pytest.mark.django_db
    def test_allows_custom_domain(self, sandbox_image):
        sandbox = self._create_sandbox(sandbox_image)
        try:
            result = self._setup_agentsh_and_exec(
                sandbox,
                "curl -s -o /dev/null -w '%{http_code}' https://pypi.org",
                allowed_domains=["pypi.org"],
            )
            assert result.exit_code == 0, f"Expected success for allowed custom domain, got: {result.stderr}"
        finally:
            sandbox.destroy()

    @pytest.mark.django_db
    def test_full_access_skips_agentsh(self, sandbox_image):
        """When no domains are provided (full access), agentsh should not be set up."""
        sandbox = self._create_sandbox(sandbox_image)
        try:
            result = sandbox.execute("test -f /tmp/agentsh-session-id", timeout_seconds=5)
            assert result.exit_code != 0, "agentsh session file should not exist without setup"
        finally:
            sandbox.destroy()
