import os

import pytest

from products.tasks.backend.services.sandbox import Sandbox, SandboxConfig, SandboxStatus, SandboxTemplate


@pytest.mark.asyncio
class TestSandboxIntegration:
    # We only run these tests when we have a Runloop API key set, we don't want to run them in CI since they create real sandbox environments and are slow.
    @pytest.fixture(scope="class", autouse=True)
    def check_api_key(self):
        if not os.environ.get("RUNLOOP_API_KEY"):
            pytest.skip("RUNLOOP_API_KEY not set, skipping integration tests")

    async def test_create_execute_destroy_lifecycle(self):
        config = SandboxConfig(
            name="posthog-test-lifecycle",
            template=SandboxTemplate.DEFAULT_BASE,
        )

        sandbox = await Sandbox.create(config)

        assert sandbox.id is not None
        assert sandbox.status == SandboxStatus.RUNNING
        assert sandbox.is_running

        result = await sandbox.execute("echo 'Hello World'")
        assert result.exit_code == 0
        assert "Hello World" in result.stdout
        assert result.stderr == ""

        await sandbox.destroy()
        assert sandbox.status == SandboxStatus.SHUTDOWN  # type: ignore[comparison-overlap]

    @pytest.mark.parametrize(
        "command,expected_exit_code,expected_in_stdout",
        [
            ("echo 'test'", 0, "test"),
            ("pwd", 0, "/"),
            ("python3 -c 'print(\"python works\")'", 0, "python works"),
        ],
    )
    async def test_command_execution(self, command, expected_exit_code, expected_in_stdout):
        config = SandboxConfig(name="posthog-test-commands")

        async with await Sandbox.create(config) as sandbox:
            result = await sandbox.execute(command)
            assert result.exit_code == expected_exit_code
            assert expected_in_stdout in result.stdout

    async def test_error_command_handling(self):
        config = SandboxConfig(name="posthog-test-error")

        async with await Sandbox.create(config) as sandbox:
            result = await sandbox.execute("nonexistent-command")
            assert result.exit_code == 127
            assert "command not found" in result.stderr.lower()

    async def test_working_directory_navigation(self):
        config = SandboxConfig(name="posthog-test-workdir")

        async with await Sandbox.create(config) as sandbox:
            setup_result = await sandbox.execute("mkdir -p /tmp/test_dir && echo 'content' > /tmp/test_dir/file.txt")
            assert setup_result.exit_code == 0

            result = await sandbox.execute("cd /tmp/test_dir && pwd && cat file.txt")
            assert result.exit_code == 0
            assert "/tmp/test_dir" in result.stdout
            assert "content" in result.stdout

    async def test_timeout_handling(self):
        config = SandboxConfig(name="posthog-test-timeout")

        async with await Sandbox.create(config) as sandbox:
            result = await sandbox.execute("sleep 2 && echo 'completed'", timeout_seconds=5)
            assert result.exit_code == 0
            assert "completed" in result.stdout

    async def test_get_by_id(self):
        config = SandboxConfig(name="posthog-test-get-id")
        original = await Sandbox.create(config)

        try:
            retrieved = await Sandbox.get_by_id(original.id)
            assert retrieved.id == original.id
            assert retrieved.status == SandboxStatus.RUNNING
            assert retrieved.is_running
        finally:
            await original.destroy()

    async def test_context_manager_auto_cleanup(self):
        config = SandboxConfig(name="posthog-test-context")

        async with await Sandbox.create(config) as sandbox:
            assert sandbox.is_running

            result = await sandbox.execute("echo 'context test'")
            assert result.exit_code == 0
            assert "context test" in result.stdout

        assert sandbox.status == SandboxStatus.SHUTDOWN
