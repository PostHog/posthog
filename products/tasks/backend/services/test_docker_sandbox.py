import os
import subprocess

import pytest
from unittest.mock import MagicMock, patch

from products.tasks.backend.services.docker_sandbox import DockerSandbox
from products.tasks.backend.services.sandbox import SandboxConfig, SandboxStatus, SandboxTemplate, get_sandbox_class


def docker_available() -> bool:
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


def is_ci() -> bool:
    return os.environ.get("GITHUB_ACTIONS") is not None or os.environ.get("CI") is not None


@pytest.mark.skipif(is_ci() or not docker_available(), reason="Docker sandbox tests only run locally, not in CI")
class TestSandboxFactory:
    """Tests for sandbox factory and production safety."""

    @patch("products.tasks.backend.services.sandbox.settings")
    def test_docker_sandbox_blocked_in_production(self, mock_settings):
        mock_settings.SANDBOX_PROVIDER = "docker"
        mock_settings.DEBUG = False

        with pytest.raises(RuntimeError, match="DockerSandbox cannot be used in production"):
            get_sandbox_class()

    @patch("products.tasks.backend.services.sandbox.settings")
    def test_docker_sandbox_opt_in_with_debug(self, mock_settings):
        mock_settings.SANDBOX_PROVIDER = "docker"
        mock_settings.DEBUG = True

        sandbox_class = get_sandbox_class()
        assert sandbox_class == DockerSandbox

    @patch("products.tasks.backend.services.sandbox.settings")
    def test_modal_sandbox_default_in_debug(self, mock_settings):
        mock_settings.SANDBOX_PROVIDER = None
        mock_settings.DEBUG = True

        from products.tasks.backend.services.modal_sandbox import ModalSandbox

        sandbox_class = get_sandbox_class()
        assert sandbox_class == ModalSandbox

    @patch("products.tasks.backend.services.sandbox.settings")
    def test_modal_sandbox_default_in_production(self, mock_settings):
        mock_settings.SANDBOX_PROVIDER = None
        mock_settings.DEBUG = False

        from products.tasks.backend.services.modal_sandbox import ModalSandbox

        sandbox_class = get_sandbox_class()
        assert sandbox_class == ModalSandbox


class TestDockerSandboxUnit:
    """Unit tests that don't require Docker."""

    @pytest.mark.parametrize(
        "input_url,expected_url",
        [
            ("http://localhost:8000", "http://host.docker.internal:8000"),
            ("http://127.0.0.1:8000", "http://host.docker.internal:8000"),
            ("https://localhost:8000/api", "https://host.docker.internal:8000/api"),
            ("https://app.posthog.com", "https://app.posthog.com"),
            ("http://localhost:8000/api/v1", "http://host.docker.internal:8000/api/v1"),
        ],
    )
    def test_transform_url_for_docker(self, input_url, expected_url):
        result = DockerSandbox._transform_url_for_docker(input_url)
        assert result == expected_url

    @patch("products.tasks.backend.services.docker_sandbox.subprocess.run")
    @patch("products.tasks.backend.services.docker_sandbox.os.path.exists")
    def test_create_transforms_posthog_api_url(self, mock_exists, mock_run):
        mock_exists.return_value = False
        mock_run.return_value = MagicMock(stdout="abc123container", returncode=0)

        config = SandboxConfig(
            name="test-sandbox",
            template=SandboxTemplate.DEFAULT_BASE,
            environment_variables={
                "POSTHOG_API_URL": "http://localhost:8000",
                "POSTHOG_PROJECT_ID": "1",
            },
        )

        with patch.object(DockerSandbox, "_get_image", return_value="posthog-sandbox-base"):
            DockerSandbox.create(config)

        docker_run_call = mock_run.call_args_list[-1]
        docker_args = docker_run_call[0][0]

        env_args = " ".join(docker_args)
        assert "POSTHOG_API_URL=http://host.docker.internal:8000" in env_args
        assert "POSTHOG_PROJECT_ID=1" in env_args

    @patch("products.tasks.backend.services.docker_sandbox.subprocess.run")
    def test_get_status_running(self, mock_run):
        mock_run.return_value = MagicMock(stdout="true", returncode=0)

        sandbox = DockerSandbox.__new__(DockerSandbox)
        sandbox._container_id = "abc123"
        sandbox.id = "abc123"
        sandbox.config = SandboxConfig(name="test")

        assert sandbox.get_status() == SandboxStatus.RUNNING
        assert sandbox.is_running()

    @patch("products.tasks.backend.services.docker_sandbox.subprocess.run")
    def test_get_status_shutdown(self, mock_run):
        mock_run.return_value = MagicMock(stdout="false", returncode=0)

        sandbox = DockerSandbox.__new__(DockerSandbox)
        sandbox._container_id = "abc123"
        sandbox.id = "abc123"
        sandbox.config = SandboxConfig(name="test")

        assert sandbox.get_status() == SandboxStatus.SHUTDOWN
        assert not sandbox.is_running()

    @patch("products.tasks.backend.services.docker_sandbox.subprocess.run")
    def test_execute_returns_result(self, mock_run):
        mock_run.side_effect = [
            MagicMock(stdout="true", returncode=0),  # is_running check
            MagicMock(stdout="hello world", stderr="", returncode=0),  # execute
        ]

        sandbox = DockerSandbox.__new__(DockerSandbox)
        sandbox._container_id = "abc123"
        sandbox.id = "abc123"
        sandbox.config = SandboxConfig(name="test")

        result = sandbox.execute("echo 'hello world'")

        assert result.exit_code == 0
        assert result.stdout == "hello world"
        assert result.stderr == ""


@pytest.mark.skipif(is_ci() or not docker_available(), reason="Docker sandbox tests only run locally, not in CI")
class TestDockerSandboxIntegration:
    """Integration tests that require Docker. Only run locally, not in CI."""

    def test_create_execute_destroy_lifecycle(self):
        config = SandboxConfig(
            name="posthog-test-docker-lifecycle",
            template=SandboxTemplate.DEFAULT_BASE,
        )

        sandbox = DockerSandbox.create(config)

        try:
            assert sandbox.id is not None
            assert sandbox.get_status() == SandboxStatus.RUNNING
            assert sandbox.is_running()

            result = sandbox.execute("echo 'Hello World'")
            assert result.exit_code == 0
            assert "Hello World" in result.stdout
        finally:
            sandbox.destroy()

        assert sandbox.get_status() == SandboxStatus.SHUTDOWN

    @pytest.mark.parametrize(
        "command,expected_exit_code,expected_in_stdout",
        [
            ("echo 'test'", 0, "test"),
            ("pwd", 0, "/tmp/workspace"),
        ],
    )
    def test_command_execution(self, command, expected_exit_code, expected_in_stdout):
        config = SandboxConfig(name="posthog-test-docker-commands")

        with DockerSandbox.create(config) as sandbox:
            result = sandbox.execute(command)
            assert result.exit_code == expected_exit_code
            assert expected_in_stdout in result.stdout

    def test_context_manager_auto_cleanup(self):
        config = SandboxConfig(name="posthog-test-docker-context")

        with DockerSandbox.create(config) as sandbox:
            assert sandbox.is_running()
            sandbox_id = sandbox._container_id

        result = subprocess.run(
            ["docker", "inspect", sandbox_id],
            capture_output=True,
        )
        assert result.returncode != 0

    def test_environment_variables_passed(self):
        config = SandboxConfig(
            name="posthog-test-docker-env",
            environment_variables={
                "TEST_VAR": "test_value",
                "POSTHOG_API_URL": "http://localhost:8000",
            },
        )

        with DockerSandbox.create(config) as sandbox:
            result = sandbox.execute("echo $TEST_VAR")
            assert "test_value" in result.stdout

            result = sandbox.execute("echo $POSTHOG_API_URL")
            assert "host.docker.internal" in result.stdout

    def test_snapshot_create_and_use(self):
        config = SandboxConfig(name="posthog-test-docker-snapshot")

        with DockerSandbox.create(config) as sandbox:
            sandbox.execute("echo 'snapshot test' > /tmp/snapshot_file.txt")
            snapshot_id = sandbox.create_snapshot()

        assert snapshot_id is not None

        try:
            result = subprocess.run(
                ["docker", "images", "-q", f"posthog-sandbox-snapshot:{snapshot_id}"],
                capture_output=True,
                text=True,
            )
            assert result.stdout.strip() != ""
        finally:
            DockerSandbox.delete_snapshot(snapshot_id)
