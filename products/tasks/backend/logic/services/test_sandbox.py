import os

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.tasks.backend.exceptions import SandboxTimeoutError
from products.tasks.backend.logic.services.sandbox import (
    CLONE_MAX_ATTEMPTS,
    ExecutionResult,
    Sandbox,
    SandboxBase,
    SandboxConfig,
    SandboxStatus,
    SandboxTemplate,
    is_transient_clone_error,
)


def _clone_stub(execute: MagicMock) -> MagicMock:
    """A stand-in with just the attributes SandboxBase.clone_repository touches, so the retry
    loop can be exercised without a real (Modal/Docker) sandbox."""
    stub = MagicMock()
    stub.id = "sb-test"
    stub.is_running.return_value = True
    stub.execute = execute
    return stub


class TestIsTransientCloneError:
    @parameterized.expand(
        [
            # Connectivity blips a retry can recover from.
            ("fatal: unable to access '...': Couldn't connect to server", True),
            ("fatal: unable to access '...': Could not resolve host: github.com", True),
            ("fatal: unable to access '...': Failed to connect to github.com port 443: Connection timed out", True),
            ("error: RPC failed; curl 92 HTTP/2 stream 0 was not closed cleanly", True),
            ("fatal: The remote end hung up unexpectedly\nfatal: early EOF", True),
            ("fatal: unable to access '...': The requested URL returned error: 503", True),
            # Deterministic failures no retry can fix.
            ("remote: Repository not found.\nfatal: repository '...' not found", False),
            ("fatal: Authentication failed for 'https://github.com/org/repo.git/'", False),
            ("remote: Invalid username or password.", False),
            ("fatal: unable to access '...': The requested URL returned error: 403", False),
            ("fatal: could not read Username for 'https://github.com': terminal prompts disabled", False),
        ]
    )
    def test_classification(self, stderr: str, expected_transient: bool):
        assert is_transient_clone_error(stderr) is expected_transient


class TestCloneRepositoryRetry:
    def _fail(self, stderr: str) -> ExecutionResult:
        return ExecutionResult(stdout="", stderr=stderr, exit_code=128, error=None)

    def _ok(self) -> ExecutionResult:
        return ExecutionResult(stdout="", stderr="", exit_code=0, error=None)

    def test_transient_failure_is_retried_then_succeeds(self):
        execute = MagicMock(side_effect=[self._fail("Couldn't connect to server"), self._ok()])
        stub = _clone_stub(execute)

        with patch("products.tasks.backend.logic.services.sandbox.time.sleep") as mock_sleep:
            result = SandboxBase.clone_repository(stub, "PostHog/posthog", github_token="tok")

        assert result.exit_code == 0
        assert execute.call_count == 2
        assert mock_sleep.call_count == 1

    def test_deterministic_failure_is_not_retried(self):
        execute = MagicMock(return_value=self._fail("remote: Repository not found"))
        stub = _clone_stub(execute)

        with patch("products.tasks.backend.logic.services.sandbox.time.sleep") as mock_sleep:
            result = SandboxBase.clone_repository(stub, "PostHog/posthog", github_token="tok")

        assert result.exit_code == 128
        assert execute.call_count == 1
        mock_sleep.assert_not_called()

    def test_persistent_transient_failure_exhausts_attempts(self):
        execute = MagicMock(return_value=self._fail("Could not resolve host: github.com"))
        stub = _clone_stub(execute)

        with patch("products.tasks.backend.logic.services.sandbox.time.sleep"):
            result = SandboxBase.clone_repository(stub, "PostHog/posthog", github_token="tok")

        assert result.exit_code == 128
        assert execute.call_count == CLONE_MAX_ATTEMPTS

    def test_execution_timeout_is_retried_then_reraised(self):
        execute = MagicMock(side_effect=SandboxTimeoutError("timed out", {}, cause=RuntimeError()))
        stub = _clone_stub(execute)

        with patch("products.tasks.backend.logic.services.sandbox.time.sleep"):
            with pytest.raises(SandboxTimeoutError):
                SandboxBase.clone_repository(stub, "PostHog/posthog", github_token="tok")

        assert execute.call_count == CLONE_MAX_ATTEMPTS


class TestSandboxIntegration:
    @pytest.fixture(scope="class", autouse=True)
    def check_api_key(self):
        if not os.environ.get("MODAL_TOKEN_ID") or not os.environ.get("MODAL_TOKEN_SECRET"):
            pytest.skip("MODAL_TOKEN_ID and MODAL_TOKEN_SECRET not set, skipping integration tests")

    def test_create_execute_destroy_lifecycle(self):
        config = SandboxConfig(
            name="posthog-test-lifecycle",
            template=SandboxTemplate.DEFAULT_BASE,
        )

        sandbox = Sandbox.create(config)

        assert sandbox.id is not None
        assert sandbox.get_status() == SandboxStatus.RUNNING
        assert sandbox.is_running()

        result = sandbox.execute("echo 'Hello World'")
        assert result.exit_code == 0
        assert "Hello World" in result.stdout
        assert result.stderr == ""

        sandbox.destroy()
        assert sandbox.get_status() == SandboxStatus.SHUTDOWN

    @pytest.mark.parametrize(
        "command,expected_exit_code,expected_in_stdout",
        [
            ("echo 'test'", 0, "test"),
            ("pwd", 0, "/tmp/workspace"),
            ("python3 -c 'print(\"python works\")'", 0, "python works"),
        ],
    )
    def test_command_execution(self, command, expected_exit_code, expected_in_stdout):
        config = SandboxConfig(name="posthog-test-commands")

        with Sandbox.create(config) as sandbox:
            result = sandbox.execute(command)
            assert result.exit_code == expected_exit_code
            assert expected_in_stdout in result.stdout

    def test_error_command_handling(self):
        config = SandboxConfig(name="posthog-test-error")

        with Sandbox.create(config) as sandbox:
            result = sandbox.execute("nonexistent-command")
            assert result.exit_code == 127
            assert "command not found" in result.stderr.lower()

    def test_working_directory_navigation(self):
        config = SandboxConfig(name="posthog-test-workdir")

        with Sandbox.create(config) as sandbox:
            setup_result = sandbox.execute("mkdir -p /tmp/test_dir && echo 'content' > /tmp/test_dir/file.txt")
            assert setup_result.exit_code == 0

            result = sandbox.execute("cd /tmp/test_dir && pwd && cat file.txt")
            assert result.exit_code == 0
            assert "/tmp/test_dir" in result.stdout
            assert "content" in result.stdout

    def test_timeout_handling(self):
        config = SandboxConfig(name="posthog-test-timeout")

        with Sandbox.create(config) as sandbox:
            result = sandbox.execute("sleep 2 && echo 'completed'", timeout_seconds=5)
            assert result.exit_code == 0
            assert "completed" in result.stdout

    def test_get_by_id(self):
        config = SandboxConfig(name="posthog-test-get-id")
        original = Sandbox.create(config)

        try:
            retrieved = Sandbox.get_by_id(original.id)
            assert retrieved.id == original.id
            assert retrieved.get_status() == SandboxStatus.RUNNING
            assert retrieved.is_running()
        finally:
            original.destroy()

    def test_context_manager_auto_cleanup(self):
        config = SandboxConfig(name="posthog-test-context")

        with Sandbox.create(config) as sandbox:
            assert sandbox.is_running()

            result = sandbox.execute("echo 'context test'")
            assert result.exit_code == 0
            assert "context test" in result.stdout

        assert sandbox.get_status() == SandboxStatus.SHUTDOWN
