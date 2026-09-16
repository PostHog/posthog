import os
import time
import uuid
import threading

import pytest

from asgiref.sync import async_to_sync

from products.tasks.backend.exceptions import SandboxNotFoundError
from products.tasks.backend.logic.services.sandbox import Sandbox, SandboxConfig, SandboxTemplate
from products.tasks.backend.logic.stream.redis_stream import TaskRunRedisStream, get_task_run_stream_key
from products.tasks.backend.temporal.process_task.activities.cleanup_sandbox import CleanupSandboxInput, cleanup_sandbox


@pytest.mark.django_db
def test_cleanup_sandbox_skips_agent_server_shutdown_for_regular_cleanup(activity_environment, mocker):
    sandbox = mocker.Mock(id="sandbox-123")
    get_by_id = mocker.patch.object(Sandbox, "get_by_id", return_value=sandbox)

    async_to_sync(activity_environment.run)(cleanup_sandbox, CleanupSandboxInput(sandbox_id="sandbox-123"))

    get_by_id.assert_called_once_with("sandbox-123")
    sandbox.execute.assert_not_called()
    sandbox.destroy.assert_called_once_with()


@pytest.mark.django_db
def test_cleanup_sandbox_records_cpu_usage_before_destroy(activity_environment, mocker):
    sandbox = mocker.Mock(id="sandbox-123")
    sandbox.read_cpu_usage_usec.return_value = 12_345_678
    sandbox.read_billed_cpu_usage_usec.return_value = 15_000_000
    mocker.patch.object(Sandbox, "get_by_id", return_value=sandbox)
    close_session = mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.cleanup_sandbox.close_sandbox_session"
    )

    async_to_sync(activity_environment.run)(cleanup_sandbox, CleanupSandboxInput(sandbox_id="sandbox-123"))

    sandbox.read_cpu_usage_usec.assert_called_once_with()
    sandbox.destroy.assert_called_once_with()
    close_session.assert_called_once_with(
        "sandbox-123",
        reason="cleanup",
        cpu_usage_usec=12_345_678,
        billed_cpu_usage_usec=15_000_000,
        cpu_usage_measured_at=mocker.ANY,
    )


@pytest.mark.django_db
def test_cleanup_sandbox_ignores_cpu_usage_read_failure(activity_environment, mocker):
    sandbox = mocker.Mock(id="sandbox-123")
    sandbox.read_cpu_usage_usec.side_effect = RuntimeError("unavailable")
    mocker.patch.object(Sandbox, "get_by_id", return_value=sandbox)

    async_to_sync(activity_environment.run)(cleanup_sandbox, CleanupSandboxInput(sandbox_id="sandbox-123"))

    sandbox.destroy.assert_called_once_with()


@pytest.mark.django_db
def test_cleanup_sandbox_requests_agent_server_shutdown_when_completing_stream(activity_environment, mocker):
    sandbox = mocker.Mock(id="sandbox-123")
    sandbox.stop_agent_server.return_value.exit_code = 0
    get_by_id = mocker.patch.object(Sandbox, "get_by_id", return_value=sandbox)

    async_to_sync(activity_environment.run)(
        cleanup_sandbox,
        CleanupSandboxInput(sandbox_id="sandbox-123", complete_stream_on_cleanup=True),
    )

    get_by_id.assert_called_once_with("sandbox-123")
    sandbox.stop_agent_server.assert_called_once_with()
    sandbox.execute.assert_not_called()
    sandbox.destroy.assert_called_once_with()


@pytest.mark.django_db
def test_cleanup_sandbox_retries_when_final_destroy_fails(activity_environment, mocker):
    run_id = str(uuid.uuid4())
    sandbox = mocker.Mock(id="sandbox-123")
    sandbox.read_cpu_usage_usec.return_value = 12_345_678
    sandbox.read_billed_cpu_usage_usec.return_value = 15_000_000
    sandbox.destroy.side_effect = RuntimeError("destroy failed")
    mocker.patch.object(Sandbox, "get_by_id", return_value=sandbox)
    close_session = mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.cleanup_sandbox.close_sandbox_session"
    )
    publish_complete = mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.cleanup_sandbox.publish_task_run_stream_complete"
    )

    with pytest.raises(RuntimeError, match="destroy failed"):
        async_to_sync(activity_environment.run)(
            cleanup_sandbox,
            CleanupSandboxInput(
                sandbox_id="sandbox-123",
                run_id=run_id,
                complete_stream_on_cleanup=True,
            ),
        )

    sandbox.destroy.assert_called_once_with()
    sandbox.execute.assert_not_called()
    close_session.assert_called_once_with(
        "sandbox-123",
        reason="cleanup",
        cpu_usage_usec=12_345_678,
        billed_cpu_usage_usec=15_000_000,
        cpu_usage_measured_at=mocker.ANY,
    )
    publish_complete.assert_not_called()


@pytest.mark.django_db
def test_cleanup_sandbox_completes_stream_when_requested(activity_environment, mocker):
    run_id = str(uuid.uuid4())
    sandbox = mocker.Mock(id="sandbox-123")
    mocker.patch.object(Sandbox, "get_by_id", return_value=sandbox)
    publish_complete = mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.cleanup_sandbox.publish_task_run_stream_complete"
    )

    async_to_sync(activity_environment.run)(
        cleanup_sandbox,
        CleanupSandboxInput(
            sandbox_id="sandbox-123",
            run_id=run_id,
            complete_stream_on_cleanup=True,
        ),
    )

    sandbox.execute.assert_not_called()
    sandbox.destroy.assert_called_once_with()
    publish_complete.assert_called_once_with(run_id, False)


@pytest.mark.django_db
def test_cleanup_sandbox_writes_real_completion_sentinel_when_requested(activity_environment, mocker):
    run_id = str(uuid.uuid4())
    stream_key = get_task_run_stream_key(run_id)
    sandbox = mocker.Mock(id="sandbox-123")
    mocker.patch.object(Sandbox, "get_by_id", return_value=sandbox)

    async def _read_stream_events():
        redis_stream = TaskRunRedisStream(stream_key)
        messages = await redis_stream._redis_client.xrange(stream_key)
        await redis_stream.delete_stream()
        return [message[b"data"] for _stream_id, message in messages]

    async_to_sync(activity_environment.run)(
        cleanup_sandbox,
        CleanupSandboxInput(
            sandbox_id="sandbox-123",
            run_id=run_id,
            complete_stream_on_cleanup=True,
        ),
    )

    assert async_to_sync(_read_stream_events)() == [b'{"type": "STREAM_STATUS", "status": "complete"}']


@pytest.mark.django_db
def test_cleanup_sandbox_completes_stream_when_sandbox_is_already_gone(activity_environment, mocker):
    run_id = str(uuid.uuid4())
    mocker.patch.object(
        Sandbox,
        "get_by_id",
        side_effect=SandboxNotFoundError(
            "Sandbox sandbox-123 not found",
            {"sandbox_id": "sandbox-123"},
            cause=RuntimeError("not found"),
        ),
    )
    publish_complete = mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.cleanup_sandbox.publish_task_run_stream_complete"
    )

    async_to_sync(activity_environment.run)(
        cleanup_sandbox,
        CleanupSandboxInput(
            sandbox_id="sandbox-123",
            run_id=run_id,
            complete_stream_on_cleanup=True,
        ),
    )

    publish_complete.assert_called_once_with(run_id, False)


@pytest.mark.skipif(
    not os.environ.get("MODAL_TOKEN_ID") or not os.environ.get("MODAL_TOKEN_SECRET"),
    reason="MODAL_TOKEN_ID and MODAL_TOKEN_SECRET environment variables not set",
)
class TestCleanupSandboxActivity:
    @pytest.mark.django_db
    def test_cleanup_sandbox_success(self, activity_environment, assert_sandbox_shutdown):
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
        assert existing_sandbox.is_running()

        input_data = CleanupSandboxInput(sandbox_id=sandbox_id)

        async_to_sync(activity_environment.run)(cleanup_sandbox, input_data)

        assert_sandbox_shutdown(sandbox_id)

    @pytest.mark.django_db
    def test_cleanup_sandbox_not_found_does_not_raise(self, activity_environment):
        input_data = CleanupSandboxInput(sandbox_id="non-existent-sandbox-id")

        async_to_sync(activity_environment.run)(cleanup_sandbox, input_data)

    @pytest.mark.django_db
    def test_cleanup_sandbox_idempotency(self, activity_environment, assert_sandbox_shutdown):
        test_tag = f"test-cleanup-idempotent-{time.time()}"
        config = SandboxConfig(
            name=f"test-cleanup-idempotent-{time.time()}",
            template=SandboxTemplate.DEFAULT_BASE,
            metadata={"test_tag": test_tag},
        )

        sandbox = Sandbox.create(config)
        sandbox_id = sandbox.id

        assert Sandbox.get_by_id(sandbox_id).is_running()

        input_data = CleanupSandboxInput(sandbox_id=sandbox_id)

        async_to_sync(activity_environment.run)(cleanup_sandbox, input_data)

        assert_sandbox_shutdown(sandbox_id)

        async_to_sync(activity_environment.run)(cleanup_sandbox, input_data)

    @pytest.mark.django_db
    def test_cleanup_sandbox_during_execution(self, activity_environment, assert_sandbox_shutdown):
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

        assert Sandbox.get_by_id(sandbox_id).is_running()

        input_data = CleanupSandboxInput(sandbox_id=sandbox_id)
        async_to_sync(activity_environment.run)(cleanup_sandbox, input_data)

        long_task.join(timeout=5)

        assert_sandbox_shutdown(sandbox_id)
