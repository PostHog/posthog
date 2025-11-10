import os
import time
import threading

import pytest

from asgiref.sync import async_to_sync

from products.tasks.backend.services.sandbox import Sandbox, SandboxConfig, SandboxTemplate
from products.tasks.backend.temporal.process_task.activities.cleanup_sandbox import CleanupSandboxInput, cleanup_sandbox


@pytest.mark.skipif(
    not os.environ.get("MODAL_TOKEN_ID") or not os.environ.get("MODAL_TOKEN_SECRET"),
    reason="MODAL_TOKEN_ID and MODAL_TOKEN_SECRET environment variables not set",
)
class TestCleanupSandboxActivity:
    @pytest.mark.django_db
    def test_cleanup_sandbox_success(self, activity_environment):
        config = SandboxConfig(
            name="test-cleanup-sandbox",
            template=SandboxTemplate.DEFAULT_BASE,
        )

        sandbox = Sandbox.create(config)
        sandbox_id = sandbox.id

        existing_sandbox = Sandbox.get_by_id(sandbox_id)
        assert existing_sandbox.id == sandbox_id

        input_data = CleanupSandboxInput(sandbox_id=sandbox_id)

        async_to_sync(activity_environment.run)(cleanup_sandbox, input_data)

        cleaned_sandbox = Sandbox.get_by_id(sandbox_id)
        assert cleaned_sandbox.status.value == "shutdown"

    @pytest.mark.django_db
    def test_cleanup_sandbox_not_found_does_not_raise(self, activity_environment):
        input_data = CleanupSandboxInput(sandbox_id="non-existent-sandbox-id")

        async_to_sync(activity_environment.run)(cleanup_sandbox, input_data)

    @pytest.mark.django_db
    def test_cleanup_sandbox_idempotency(self, activity_environment):
        config = SandboxConfig(
            name="test-cleanup-idempotent",
            template=SandboxTemplate.DEFAULT_BASE,
        )

        sandbox = Sandbox.create(config)
        sandbox_id = sandbox.id

        input_data = CleanupSandboxInput(sandbox_id=sandbox_id)

        async_to_sync(activity_environment.run)(cleanup_sandbox, input_data)

        cleaned_sandbox = Sandbox.get_by_id(sandbox_id)
        assert cleaned_sandbox.status.value == "shutdown"

        async_to_sync(activity_environment.run)(cleanup_sandbox, input_data)

    @pytest.mark.django_db
    def test_cleanup_sandbox_during_execution(self, activity_environment):
        config = SandboxConfig(
            name="test-cleanup-during-execution",
            template=SandboxTemplate.DEFAULT_BASE,
        )

        sandbox = Sandbox.create(config)
        sandbox_id = sandbox.id

        def run_long_command():
            try:
                sandbox.execute("sleep 30", timeout_seconds=60)
            except Exception:
                pass

        long_task = threading.Thread(target=run_long_command)
        long_task.start()

        time.sleep(5)

        input_data = CleanupSandboxInput(sandbox_id=sandbox_id)
        async_to_sync(activity_environment.run)(cleanup_sandbox, input_data)

        long_task.join(timeout=5)

        remaining_sandbox = Sandbox.get_by_id(sandbox_id)

        assert remaining_sandbox.status.value in ["shutdown", "failure"]
