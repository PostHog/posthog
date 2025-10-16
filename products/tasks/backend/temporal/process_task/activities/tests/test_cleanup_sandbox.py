import os
import asyncio

import pytest

from products.tasks.backend.services.sandbox_environment import (
    SandboxEnvironment,
    SandboxEnvironmentConfig,
    SandboxEnvironmentTemplate,
)
from products.tasks.backend.temporal.process_task.activities.cleanup_sandbox import CleanupSandboxInput, cleanup_sandbox


@pytest.mark.skipif(not os.environ.get("RUNLOOP_API_KEY"), reason="RUNLOOP_API_KEY environment variable not set")
class TestCleanupSandboxActivity:
    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_cleanup_sandbox_success(self, activity_environment):
        config = SandboxEnvironmentConfig(
            name="test-cleanup-sandbox",
            template=SandboxEnvironmentTemplate.DEFAULT_BASE,
        )

        sandbox = await SandboxEnvironment.create(config)
        sandbox_id = sandbox.id

        existing_sandbox = await SandboxEnvironment.get_by_id(sandbox_id)
        assert existing_sandbox.id == sandbox_id

        input_data = CleanupSandboxInput(sandbox_id=sandbox_id)

        await activity_environment.run(cleanup_sandbox, input_data)

        cleaned_sandbox = await SandboxEnvironment.get_by_id(sandbox_id)
        assert cleaned_sandbox.status.value == "shutdown"

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_cleanup_sandbox_not_found_does_not_raise(self, activity_environment):
        input_data = CleanupSandboxInput(sandbox_id="non-existent-sandbox-id")

        # cleanup_sandbox is idempotent and doesn't raise if sandbox doesn't exist
        await activity_environment.run(cleanup_sandbox, input_data)

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_cleanup_sandbox_idempotency(self, activity_environment):
        config = SandboxEnvironmentConfig(
            name="test-cleanup-idempotent",
            template=SandboxEnvironmentTemplate.DEFAULT_BASE,
        )

        sandbox = await SandboxEnvironment.create(config)
        sandbox_id = sandbox.id

        input_data = CleanupSandboxInput(sandbox_id=sandbox_id)

        # First cleanup - should succeed
        await activity_environment.run(cleanup_sandbox, input_data)

        cleaned_sandbox = await SandboxEnvironment.get_by_id(sandbox_id)
        assert cleaned_sandbox.status.value == "shutdown"

        # Second cleanup - should still work on shutdown sandbox
        await activity_environment.run(cleanup_sandbox, input_data)

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_cleanup_sandbox_during_execution(self, activity_environment):
        config = SandboxEnvironmentConfig(
            name="test-cleanup-during-execution",
            template=SandboxEnvironmentTemplate.DEFAULT_BASE,
        )

        sandbox = await SandboxEnvironment.create(config)
        sandbox_id = sandbox.id

        async def run_long_command():
            try:
                await sandbox.execute("sleep 30", timeout_seconds=60)
            except Exception:
                pass

        long_task = asyncio.create_task(run_long_command())

        # Give it a moment to start
        await asyncio.sleep(5)

        input_data = CleanupSandboxInput(sandbox_id=sandbox_id)
        await activity_environment.run(cleanup_sandbox, input_data)

        long_task.cancel()
        try:
            await long_task
        except asyncio.CancelledError:
            pass

        remaining_sandbox = await SandboxEnvironment.get_by_id(sandbox_id)

        assert remaining_sandbox.status.value in ["shutdown", "failure"]
