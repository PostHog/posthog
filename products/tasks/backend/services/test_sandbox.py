import os

import pytest

from products.tasks.backend.services.sandbox import Sandbox, SandboxConfig, SandboxStatus, SandboxTemplate


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
        assert sandbox.status == SandboxStatus.RUNNING
        assert sandbox.is_running

        result = sandbox.execute("echo 'Hello World'")
        assert result.exit_code == 0
        assert "Hello World" in result.stdout
        assert result.stderr == ""

        sandbox.destroy()
        assert sandbox.status == SandboxStatus.SHUTDOWN

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
            assert retrieved.status == SandboxStatus.RUNNING
            assert retrieved.is_running
        finally:
            original.destroy()

    def test_context_manager_auto_cleanup(self):
        config = SandboxConfig(name="posthog-test-context")

        with Sandbox.create(config) as sandbox:
            assert sandbox.is_running

            result = sandbox.execute("echo 'context test'")
            assert result.exit_code == 0
            assert "context test" in result.stdout

        assert sandbox.status == SandboxStatus.SHUTDOWN
