import os
import time
import threading

import pytest

import modal
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
        test_tag = f"test-cleanup-{time.time()}"
        config = SandboxConfig(
            name=f"test-cleanup-sandbox-{time.time()}",
            template=SandboxTemplate.DEFAULT_BASE,
            metadata={"test_tag": test_tag},
        )

        sandbox = Sandbox.create(config)
        sandbox_id = sandbox.id

        existing_sandbox = Sandbox.get_by_id(sandbox_id)
        assert existing_sandbox.id == sandbox_id

        sandboxes_before = list(modal.Sandbox.list(tags={"test_tag": test_tag}))
        assert len(sandboxes_before) > 0

        input_data = CleanupSandboxInput(sandbox_id=sandbox_id)

        async_to_sync(activity_environment.run)(cleanup_sandbox, input_data)

        sandboxes_after = list(modal.Sandbox.list(tags={"test_tag": test_tag}))
        assert len(sandboxes_after) == 0

    @pytest.mark.django_db
    def test_cleanup_sandbox_not_found_does_not_raise(self, activity_environment):
        input_data = CleanupSandboxInput(sandbox_id="non-existent-sandbox-id")

        async_to_sync(activity_environment.run)(cleanup_sandbox, input_data)

    @pytest.mark.django_db
    def test_cleanup_sandbox_idempotency(self, activity_environment):
        test_tag = f"test-cleanup-idempotent-{time.time()}"
        config = SandboxConfig(
            name=f"test-cleanup-idempotent-{time.time()}",
            template=SandboxTemplate.DEFAULT_BASE,
            metadata={"test_tag": test_tag},
        )

        sandbox = Sandbox.create(config)
        sandbox_id = sandbox.id

        sandboxes_before = list(modal.Sandbox.list(tags={"test_tag": test_tag}))
        assert len(sandboxes_before) > 0

        input_data = CleanupSandboxInput(sandbox_id=sandbox_id)

        async_to_sync(activity_environment.run)(cleanup_sandbox, input_data)

        sandboxes_after = list(modal.Sandbox.list(tags={"test_tag": test_tag}))
        assert len(sandboxes_after) == 0

        async_to_sync(activity_environment.run)(cleanup_sandbox, input_data)

    @pytest.mark.django_db
    def test_cleanup_sandbox_during_execution(self, activity_environment):
        test_tag = f"test-cleanup-during-exec-{time.time()}"
        config = SandboxConfig(
            name=f"test-cleanup-during-execution-{time.time()}",
            template=SandboxTemplate.DEFAULT_BASE,
            metadata={"test_tag": test_tag},
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

        sandboxes_before = list(modal.Sandbox.list(tags={"test_tag": test_tag}))
        assert len(sandboxes_before) > 0

        input_data = CleanupSandboxInput(sandbox_id=sandbox_id)
        async_to_sync(activity_environment.run)(cleanup_sandbox, input_data)

        long_task.join(timeout=5)

        sandboxes_after = list(modal.Sandbox.list(tags={"test_tag": test_tag}))
        assert len(sandboxes_after) == 0
