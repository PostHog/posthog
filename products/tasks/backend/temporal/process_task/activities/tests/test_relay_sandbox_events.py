import asyncio
import importlib
from types import SimpleNamespace
from typing import cast

import pytest
from unittest.mock import AsyncMock

import httpx
import httpx_sse
from parameterized import parameterized

from products.tasks.backend.temporal.process_task import workflow as process_task_workflow_module
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.activities.relay_sandbox_events import (
    RelaySandboxEventsInput,
    TaskRunRedisStream,
    _is_end_of_turn,
    _is_session_update,
    _mark_error_unless_run_is_terminal,
    _relay_loop,
    relay_sandbox_events,
)
from products.tasks.backend.temporal.process_task.activities.start_agent_server import StartAgentServerOutput
from products.tasks.backend.temporal.process_task.workflow import (
    RELAY_SANDBOX_EVENTS_START_TO_CLOSE_TIMEOUT,
    ProcessTaskWorkflow,
)

from ee.hogai.sandbox import TURN_COMPLETE_METHOD

relay_sandbox_events_module = importlib.import_module(
    "products.tasks.backend.temporal.process_task.activities.relay_sandbox_events"
)


class TestIsEndOfTurn:
    @parameterized.expand(
        [
            (
                "raw_acp_end_turn",
                {"type": "notification", "notification": {"result": {"stopReason": "end_turn"}}},
                True,
            ),
            (
                "raw_acp_non_terminal",
                {"type": "notification", "notification": {"result": {"stopReason": "max_tokens"}}},
                False,
            ),
            (
                "synthetic_turn_complete",
                {"type": "notification", "notification": {"method": TURN_COMPLETE_METHOD}},
                True,
            ),
            (
                "non_notification",
                {"type": "event", "notification": {"result": {"stopReason": "end_turn"}}},
                False,
            ),
        ]
    )
    def test_is_end_of_turn(self, _name: str, event_data: dict, expected: bool):
        assert _is_end_of_turn(event_data) == expected


class TestIsSessionUpdate:
    @parameterized.expand(
        [
            (
                "session_update",
                {"type": "notification", "notification": {"method": "session/update"}},
                True,
            ),
            (
                "console_notification",
                {"type": "notification", "notification": {"method": "_posthog/console"}},
                False,
            ),
            (
                "sandbox_output_notification",
                {"type": "notification", "notification": {"method": "_posthog/sandbox_output"}},
                False,
            ),
            (
                "terminal_task_complete",
                {"type": "notification", "notification": {"method": "_posthog/task_complete"}},
                False,
            ),
            (
                "terminal_error",
                {"type": "notification", "notification": {"method": "_posthog/error"}},
                False,
            ),
            (
                "non_notification_type",
                {"type": "event", "notification": {"method": "session/update"}},
                False,
            ),
            (
                "missing_notification",
                {"type": "notification"},
                False,
            ),
            (
                "empty_dict",
                {},
                False,
            ),
        ],
    )
    def test_is_session_update(self, _name: str, event_data: dict, expected: bool):
        assert _is_session_update(event_data) == expected


class TestAgentActiveReactivation:
    """Verify that agent_active is only re-activated by session/update events.

    This tests the logic from lines 231-232 of relay_sandbox_events.py:
        elif not agent_active[0] and _is_session_update(event_data):
            agent_active[0] = True
    """

    @staticmethod
    def _simulate_reactivation(event_data: dict, agent_active: bool) -> bool:
        """Replicate the inline re-activation logic from _relay_loop."""
        active = [agent_active]
        if _is_end_of_turn(event_data):
            active[0] = False
        elif not active[0] and _is_session_update(event_data):
            active[0] = True
        return active[0]

    def test_session_update_reactivates_after_end_turn(self):
        event = {"type": "notification", "notification": {"method": "session/update"}}
        assert self._simulate_reactivation(event, agent_active=False) is True

    def test_console_event_does_not_reactivate(self):
        event = {"type": "notification", "notification": {"method": "_posthog/console"}}
        assert self._simulate_reactivation(event, agent_active=False) is False

    def test_sandbox_output_does_not_reactivate(self):
        event = {"type": "notification", "notification": {"method": "_posthog/sandbox_output"}}
        assert self._simulate_reactivation(event, agent_active=False) is False

    def test_end_turn_deactivates(self):
        end_turn = {
            "type": "notification",
            "notification": {"result": {"stopReason": "end_turn"}},
        }
        assert self._simulate_reactivation(end_turn, agent_active=True) is False

    def test_full_lifecycle_turn_then_idle_then_resume(self):
        """Simulate: agent active → end_turn → console noise → session/update resumes."""
        active = [True]

        # Agent finishes turn
        end_turn = {"type": "notification", "notification": {"result": {"stopReason": "end_turn"}}}
        if _is_end_of_turn(end_turn):
            active[0] = False
        assert active[0] is False

        # Console events should NOT re-activate
        for method in ("_posthog/console", "_posthog/sandbox_output"):
            event = {"type": "notification", "notification": {"method": method}}
            if not active[0] and _is_session_update(event):
                active[0] = True
            assert active[0] is False, f"{method} should not re-activate agent"

        # session/update from new user message SHOULD re-activate
        session_event = {"type": "notification", "notification": {"method": "session/update"}}
        if not active[0] and _is_session_update(session_event):
            active[0] = True
        assert active[0] is True


class TestRelaySandboxEventsCancellation:
    async def test_cancelled_relay_marks_stream_complete_without_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        redis_stream = SimpleNamespace(
            initialize=AsyncMock(),
            mark_complete=AsyncMock(),
            mark_error=AsyncMock(),
        )

        class StubTaskRunRedisStream:
            def __init__(self, stream_key: str) -> None:
                self.stream_key = stream_key

            async def initialize(self) -> None:
                await redis_stream.initialize()

            async def mark_complete(self) -> None:
                await redis_stream.mark_complete()

            async def mark_error(self, error: str) -> None:
                await redis_stream.mark_error(error)

        class StubTaskRunQuerySet:
            def select_related(self, *_args: str) -> "StubTaskRunQuerySet":
                return self

            async def aget(self, id: str) -> SimpleNamespace:
                return SimpleNamespace(task=SimpleNamespace(created_by=SimpleNamespace(id=123)))

        async def fake_relay_loop(**_kwargs: object) -> None:
            raise asyncio.CancelledError

        monkeypatch.setattr(relay_sandbox_events_module, "TaskRunRedisStream", StubTaskRunRedisStream)
        monkeypatch.setattr(
            relay_sandbox_events_module,
            "TaskRunModel",
            SimpleNamespace(objects=StubTaskRunQuerySet()),
        )
        monkeypatch.setattr(relay_sandbox_events_module, "create_sandbox_connection_token", lambda **_kwargs: "token")
        monkeypatch.setattr(relay_sandbox_events_module, "validate_sandbox_url", lambda _url: None)
        monkeypatch.setattr(relay_sandbox_events_module, "_relay_loop", fake_relay_loop)

        with pytest.raises(asyncio.CancelledError):
            await relay_sandbox_events(
                RelaySandboxEventsInput(
                    run_id="run-id",
                    task_id="task-id",
                    sandbox_url="https://sandbox.example",
                    sandbox_connect_token=None,
                    team_id=1,
                    distinct_id="distinct-id",
                )
            )

        redis_stream.mark_complete.assert_awaited_once()
        redis_stream.mark_error.assert_not_awaited()


class TestRelaySandboxEventsErrorHandling:
    @parameterized.expand(
        [
            ("read_error", httpx.ReadError),
            ("connect_error", httpx.ConnectError),
            ("remote_protocol_error", httpx.RemoteProtocolError),
            ("sse_error", httpx_sse.SSEError),
        ],
    )
    async def test_relay_loop_retries_retryable_stream_errors(
        self,
        _name: str,
        exception_class: type[Exception],
    ) -> None:
        redis_stream = SimpleNamespace(
            write_event=AsyncMock(),
            mark_complete=AsyncMock(),
            mark_error=AsyncMock(),
        )
        sleep_mock = AsyncMock()
        connect_attempts = 0
        terminal_event = SimpleNamespace(
            data='{"type":"notification","notification":{"method":"_posthog/task_complete"}}'
        )

        class FailingEventSource:
            async def __aenter__(self) -> "FailingEventSource":
                raise exception_class("terminated")

            async def __aexit__(self, *_args: object) -> None:
                return None

        class SuccessfulEventSource:
            response = SimpleNamespace(raise_for_status=lambda: None)

            async def __aenter__(self) -> "SuccessfulEventSource":
                return self

            async def __aexit__(self, *_args: object) -> None:
                return None

            async def aiter_sse(self):
                yield terminal_event

        def fake_connect_sse(*_args: object, **_kwargs: object):
            nonlocal connect_attempts
            connect_attempts += 1
            if connect_attempts == 1:
                return FailingEventSource()
            return SuccessfulEventSource()

        async def fake_background_heartbeat(*_args: object, **_kwargs: object) -> None:
            return None

        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(relay_sandbox_events_module.httpx_sse, "aconnect_sse", fake_connect_sse)
            monkeypatch.setattr(relay_sandbox_events_module.asyncio, "sleep", sleep_mock)
            monkeypatch.setattr(relay_sandbox_events_module, "_background_heartbeat", fake_background_heartbeat)

            await _relay_loop(
                events_url="https://sandbox.example/events",
                headers={"Authorization": "Bearer token"},
                params={},
                redis_stream=cast(TaskRunRedisStream, redis_stream),
                run_id="run-id",
                task_id="task-id",
            )

        assert connect_attempts == 2
        sleep_mock.assert_awaited_once_with(2)
        redis_stream.write_event.assert_awaited_once()
        redis_stream.mark_complete.assert_awaited_once()
        redis_stream.mark_error.assert_not_awaited()

    async def test_terminal_run_marks_stream_complete_on_late_relay_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        redis_stream_mock = SimpleNamespace(mark_complete=AsyncMock(), mark_error=AsyncMock())
        redis_stream = cast(TaskRunRedisStream, redis_stream_mock)

        class StubTaskRunQuerySet:
            def only(self, *_fields: str) -> "StubTaskRunQuerySet":
                return self

            async def aget(self, id: str) -> SimpleNamespace:
                return SimpleNamespace(status="cancelled")

        monkeypatch.setattr(
            relay_sandbox_events_module,
            "TaskRunModel",
            SimpleNamespace(
                Status=SimpleNamespace(COMPLETED="completed", FAILED="failed", CANCELLED="cancelled"),
                DoesNotExist=Exception,
                objects=StubTaskRunQuerySet(),
            ),
        )

        marked_complete = await _mark_error_unless_run_is_terminal(redis_stream, "run-id", "late relay error")

        assert marked_complete is True
        redis_stream_mock.mark_complete.assert_awaited_once()
        redis_stream_mock.mark_error.assert_not_awaited()

    async def test_in_progress_run_marks_stream_error_on_relay_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        redis_stream_mock = SimpleNamespace(mark_complete=AsyncMock(), mark_error=AsyncMock())
        redis_stream = cast(TaskRunRedisStream, redis_stream_mock)

        class StubTaskRunQuerySet:
            def only(self, *_fields: str) -> "StubTaskRunQuerySet":
                return self

            async def aget(self, id: str) -> SimpleNamespace:
                return SimpleNamespace(status="in_progress")

        monkeypatch.setattr(
            relay_sandbox_events_module,
            "TaskRunModel",
            SimpleNamespace(
                Status=SimpleNamespace(COMPLETED="completed", FAILED="failed", CANCELLED="cancelled"),
                DoesNotExist=Exception,
                objects=StubTaskRunQuerySet(),
            ),
        )

        marked_complete = await _mark_error_unless_run_is_terminal(redis_stream, "run-id", "relay error")

        assert marked_complete is False
        redis_stream_mock.mark_complete.assert_not_awaited()
        redis_stream_mock.mark_error.assert_awaited_once_with("relay error")

    async def test_missing_run_marks_stream_error_on_relay_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        redis_stream_mock = SimpleNamespace(mark_complete=AsyncMock(), mark_error=AsyncMock())
        redis_stream = cast(TaskRunRedisStream, redis_stream_mock)

        class DoesNotExist(Exception):
            pass

        class StubTaskRunQuerySet:
            def only(self, *_fields: str) -> "StubTaskRunQuerySet":
                return self

            async def aget(self, id: str) -> SimpleNamespace:
                raise DoesNotExist

        monkeypatch.setattr(
            relay_sandbox_events_module,
            "TaskRunModel",
            SimpleNamespace(
                Status=SimpleNamespace(COMPLETED="completed", FAILED="failed", CANCELLED="cancelled"),
                DoesNotExist=DoesNotExist,
                objects=StubTaskRunQuerySet(),
            ),
        )

        marked_complete = await _mark_error_unless_run_is_terminal(redis_stream, "run-id", "relay error")

        assert marked_complete is False
        redis_stream_mock.mark_complete.assert_not_awaited()
        redis_stream_mock.mark_error.assert_awaited_once_with("relay error")

    async def test_terminal_status_check_failure_reraises_original_relay_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        redis_stream = SimpleNamespace(
            initialize=AsyncMock(),
            mark_complete=AsyncMock(),
            mark_error=AsyncMock(),
        )

        class StubTaskRunRedisStream:
            def __init__(self, stream_key: str) -> None:
                self.stream_key = stream_key

            async def initialize(self) -> None:
                await redis_stream.initialize()

            async def mark_complete(self) -> None:
                await redis_stream.mark_complete()

            async def mark_error(self, error: str) -> None:
                await redis_stream.mark_error(error)

        class StubTaskRunQuerySet:
            def select_related(self, *_args: str) -> "StubTaskRunQuerySet":
                return self

            async def aget(self, id: str) -> SimpleNamespace:
                return SimpleNamespace(task=SimpleNamespace(created_by=SimpleNamespace(id=123)))

        async def fake_relay_loop(**_kwargs: object) -> None:
            raise RuntimeError("relay error")

        async def fake_mark_error_unless_run_is_terminal(_redis_stream: object, _run_id: str, _error: str) -> bool:
            raise RuntimeError("status check failed")

        monkeypatch.setattr(relay_sandbox_events_module, "TaskRunRedisStream", StubTaskRunRedisStream)
        monkeypatch.setattr(
            relay_sandbox_events_module,
            "TaskRunModel",
            SimpleNamespace(objects=StubTaskRunQuerySet()),
        )
        monkeypatch.setattr(relay_sandbox_events_module, "create_sandbox_connection_token", lambda **_kwargs: "token")
        monkeypatch.setattr(relay_sandbox_events_module, "validate_sandbox_url", lambda _url: None)
        monkeypatch.setattr(relay_sandbox_events_module, "_relay_loop", fake_relay_loop)
        monkeypatch.setattr(
            relay_sandbox_events_module,
            "_mark_error_unless_run_is_terminal",
            fake_mark_error_unless_run_is_terminal,
        )

        with pytest.raises(RuntimeError, match="relay error"):
            await relay_sandbox_events(
                RelaySandboxEventsInput(
                    run_id="run-id",
                    task_id="task-id",
                    sandbox_url="https://sandbox.example",
                    sandbox_connect_token=None,
                    team_id=1,
                    distinct_id="distinct-id",
                )
            )

        redis_stream.mark_complete.assert_not_awaited()
        redis_stream.mark_error.assert_awaited_once_with("relay error")


class TestRelaySandboxEventsWorkflowOptions:
    async def test_relay_sandbox_events_uses_extended_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        workflow = ProcessTaskWorkflow()
        workflow._context = TaskProcessingContext(
            task_id="task-id",
            run_id="run-id",
            team_id=1,
            team_uuid="team-uuid",
            organization_id="organization-id",
            github_integration_id=123,
            repository="posthog/posthog-js",
            distinct_id="distinct-id",
            create_pr=True,
            state={},
            _branch="feature-branch",
        )
        execute_activity_mock = AsyncMock()
        monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", execute_activity_mock)

        await workflow._relay_sandbox_events(
            StartAgentServerOutput(sandbox_url="https://sandbox.example", connect_token="connect-token"),
            sandbox_id="sandbox-123",
        )

        assert execute_activity_mock.await_args is not None
        _, kwargs = execute_activity_mock.await_args
        assert kwargs["start_to_close_timeout"] == RELAY_SANDBOX_EVENTS_START_TO_CLOSE_TIMEOUT
