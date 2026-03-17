"""Docker integration tests for agentsh domain enforcement.

Uses DockerSandbox to create a real container with --cap-add SYS_PTRACE,
sets up agentsh via _setup_agentsh(), and verifies domain allowlisting
is enforced at the syscall level.

Requires: Docker daemon running + posthog-sandbox-base image built with agentsh.
"""

import shutil
import subprocess

import pytest

from django.test import override_settings

DOCKER_AVAILABLE = shutil.which("docker") is not None


def _image_exists(name: str = "posthog-sandbox-base") -> bool:
    if not DOCKER_AVAILABLE:
        return False
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", name],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


skip_unless_docker_image = pytest.mark.skipif(
    not _image_exists(),
    reason="Docker not available or posthog-sandbox-base image not built",
)


@skip_unless_docker_image
@override_settings(DEBUG=True, SANDBOX_PROVIDER="docker")
class TestAgentshDockerEnforcement:
    """Integration tests that verify agentsh blocks/allows network access via DockerSandbox.

    To build the required image:
        docker build -t posthog-sandbox-base -f posthog/products/tasks/backend/sandbox/images/Dockerfile.sandbox-base .
    """

    def _create_sandbox(self):
        from products.tasks.backend.services.docker_sandbox import DockerSandbox
        from products.tasks.backend.services.sandbox import SandboxConfig

        config = SandboxConfig(name="test-agentsh")
        return DockerSandbox.create(config)

    def _setup_agentsh_and_exec(self, sandbox, test_command: str, allowed_domains: list[str]) -> None:
        repo_path = "/tmp/workspace"
        sandbox._setup_agentsh(repo_path, allowed_domains)
        return sandbox.execute(
            f"agentsh exec $(cat /tmp/agentsh-session-id) -- {test_command}",
            timeout_seconds=30,
        )

    @pytest.mark.django_db
    def test_allows_permitted_domain(self):
        sandbox = self._create_sandbox()
        try:
            result = self._setup_agentsh_and_exec(
                sandbox,
                "curl -s -o /dev/null -w '%{http_code}' https://github.com",
                allowed_domains=[],
            )
            assert result.exit_code == 0, f"Expected success for github.com, got: {result.stderr}"
        finally:
            sandbox.destroy()

    @pytest.mark.django_db
    def test_blocks_denied_domain(self):
        sandbox = self._create_sandbox()
        try:
            result = self._setup_agentsh_and_exec(
                sandbox,
                "curl -s --max-time 5 https://evil.com",
                allowed_domains=[],
            )
            assert result.exit_code != 0, "Expected curl to fail for denied domain"
        finally:
            sandbox.destroy()

    @pytest.mark.django_db
    def test_allows_custom_domain(self):
        sandbox = self._create_sandbox()
        try:
            result = self._setup_agentsh_and_exec(
                sandbox,
                "curl -s -o /dev/null -w '%{http_code}' https://pypi.org",
                allowed_domains=["pypi.org"],
            )
            assert result.exit_code == 0, f"Expected success for allowed custom domain, got: {result.stderr}"
        finally:
            sandbox.destroy()
