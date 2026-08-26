import json
import asyncio
import importlib
from types import SimpleNamespace
from typing import cast

import pytest
from unittest.mock import AsyncMock, MagicMock

import httpx
import httpx_sse
from parameterized import parameterized
from temporalio.exceptions import ApplicationError

from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.constants import INACTIVITY_TIMEOUT_DEFAULT_SECONDS
from products.tasks.backend.temporal.process_task import workflow as process_task_workflow_module
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.activities.relay_sandbox_events import (
    FINAL_MESSAGE_MAX_CHARS,
    HEARTBEAT_INTERVAL_SECONDS,
    FinalMessageTracker,
    RelaySandboxEventsInput,
    TaskRunRedisStream,
    _flush_pending_text,
    _is_active_agent_update,
    _is_end_of_turn,
    _is_keepalive_event,
    _is_session_update,
    _mark_error_unless_run_is_terminal,
    _mark_sandbox_error_best_effort,
    _persist_final_message,
    _relay_loop,
    _sanitize_httpx_error,
    _should_signal_workflow_heartbeat,
    relay_sandbox_events,
)
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
            (
                "pi_turn_complete",
                {"type": "pi_event", "event": {"type": "turn_completed"}},
                True,
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


class TestIsActiveAgentUpdate:
    @staticmethod
    def _su(sub_type: str) -> dict:
        return {
            "type": "notification",
            "notification": {"method": "session/update", "params": {"update": {"sessionUpdate": sub_type}}},
        }

    @parameterized.expand(
        [
            # Generation updates -> active.
            ("agent_message", "agent_message", True),
            ("agent_message_chunk", "agent_message_chunk", True),
            ("agent_thought_chunk", "agent_thought_chunk", True),
            ("tool_call", "tool_call", True),
            ("tool_call_update", "tool_call_update", True),
            ("plan", "plan", True),
            ("user_message_chunk", "user_message_chunk", True),
            # Lifecycle updates -> not active.
            ("available_commands_update", "available_commands_update", False),
            ("current_mode_update", "current_mode_update", False),
            ("config_option_update", "config_option_update", False),
            ("usage_update", "usage_update", False),
            # Allowlist fails safe: an unknown/future sub-type is not active.
            ("unknown_future_subtype", "some_new_lifecycle_event", False),
        ],
    )
    def test_session_update_sub_types(self, _name: str, sub_type: str, expected: bool) -> None:
        assert _is_active_agent_update(self._su(sub_type)) is expected

    def test_pi_generation_event_is_active(self) -> None:
        assert _is_active_agent_update({"type": "pi_event", "event": {"type": "assistant_message_chunk"}})

    @parameterized.expand(
        [
            ("missing_session_update_key", {"update": {}}),
            ("missing_update_key", {}),
            ("null_params", None),
        ],
    )
    def test_missing_session_update_is_not_active(self, _name: str, params: dict | None) -> None:
        # A session/update with no sessionUpdate sub-type must not mark the agent active.
        event = {"type": "notification", "notification": {"method": "session/update", "params": params}}
        assert _is_active_agent_update(event) is False

    def test_non_session_update_is_not_active(self) -> None:
        assert (
            _is_active_agent_update({"type": "notification", "notification": {"method": "_posthog/console"}}) is False
        )


class TestIsKeepaliveEvent:
    @parameterized.expand(
        [
            ("keepalive", {"type": "keepalive"}, True),
            ("notification", {"type": "notification"}, False),
            ("missing_type", {}, False),
        ],
    )
    def test_is_keepalive_event(self, _name: str, event_data: dict, expected: bool) -> None:
        assert _is_keepalive_event(event_data) == expected


class TestSanitizeHttpxError:
    def test_redacts_query_string_carrying_the_transport_token(self) -> None:
        request = httpx.Request("GET", "https://hogland.example/events?token=super-secret-bearer")
        response = httpx.Response(503, request=request)
        error = httpx.HTTPStatusError("boom", request=request, response=response)

        sanitized = _sanitize_httpx_error(error)

        assert "super-secret-bearer" not in sanitized
        assert "hogland.example/events" in sanitized
        assert "503" in sanitized

    def test_leaves_url_without_a_query_string_untouched(self) -> None:
        request = httpx.Request("GET", "https://hogland.example/events")
        response = httpx.Response(500, request=request)
        error = httpx.HTTPStatusError("boom", request=request, response=response)

        sanitized = _sanitize_httpx_error(error)

        assert sanitized == "Server error '500' for url 'https://hogland.example/events'"


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
            def __init__(self, stream_key: str, use_dedicated: bool = False) -> None:
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
                return SimpleNamespace(
                    task=SimpleNamespace(created_by=SimpleNamespace(id=123), origin_product=None), state={}
                )

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


class TestRelaySandboxEventsMissingActor:
    @pytest.mark.django_db
    async def test_missing_slack_actor_fails_non_retryable_with_stream_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        redis_stream = SimpleNamespace(
            initialize=AsyncMock(),
            mark_complete=AsyncMock(),
            mark_error=AsyncMock(),
        )

        class StubTaskRunRedisStream:
            def __init__(self, stream_key: str, use_dedicated: bool = False) -> None:
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
                return SimpleNamespace(
                    task=SimpleNamespace(id="task-id", created_by=None, origin_product=None),
                    # A recorded actor that no longer resolves — deterministic, so the
                    # activity must fail for good instead of retrying forever.
                    state={"interaction_origin": "slack", "slack_actor_user_id": 424_242},
                )

        relay_loop_mock = AsyncMock()
        monkeypatch.setattr(relay_sandbox_events_module, "TaskRunRedisStream", StubTaskRunRedisStream)
        monkeypatch.setattr(
            relay_sandbox_events_module,
            "TaskRunModel",
            SimpleNamespace(objects=StubTaskRunQuerySet()),
        )
        monkeypatch.setattr(relay_sandbox_events_module, "validate_sandbox_url", lambda _url: None)
        monkeypatch.setattr(relay_sandbox_events_module, "_relay_loop", relay_loop_mock)

        with pytest.raises(ApplicationError) as exc_info:
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

        assert exc_info.value.non_retryable is True
        redis_stream.mark_error.assert_awaited_once()
        relay_loop_mock.assert_not_awaited()


class TestRelaySandboxEventsErrorHandling:
    async def test_confirmed_sandbox_loss_survives_redis_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        redis_stream = SimpleNamespace(mark_error=AsyncMock(side_effect=RuntimeError("redis unavailable")))
        logger_mock = MagicMock()
        monkeypatch.setattr(relay_sandbox_events_module, "logger", logger_mock)

        await _mark_sandbox_error_best_effort(
            cast(TaskRunRedisStream, redis_stream), "run-id", "Sandbox returned HTTP 404"
        )

        redis_stream.mark_error.assert_awaited_once_with("Sandbox returned HTTP 404")
        logger_mock.exception.assert_called_once_with(
            "relay_sandbox_events_mark_error_failed",
            run_id="run-id",
            error="redis unavailable",
        )

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

            sandbox_gone = await _relay_loop(
                events_url="https://sandbox.example/events",
                headers={"Authorization": "Bearer token"},
                params={},
                redis_stream=cast(TaskRunRedisStream, redis_stream),
                run_id="run-id",
                task_id="task-id",
            )

        assert connect_attempts == 2
        assert sandbox_gone is False
        sleep_mock.assert_awaited_once_with(2)
        redis_stream.write_event.assert_awaited_once()
        redis_stream.mark_complete.assert_awaited_once()
        redis_stream.mark_error.assert_not_awaited()

    async def test_keepalive_events_are_transport_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        redis_stream = SimpleNamespace(
            write_event=AsyncMock(),
            mark_complete=AsyncMock(),
            mark_error=AsyncMock(),
        )
        terminal_event = {
            "type": "notification",
            "notification": {"method": "_posthog/task_complete"},
        }

        class SuccessfulEventSource:
            response = SimpleNamespace(raise_for_status=lambda: None)

            async def __aenter__(self) -> "SuccessfulEventSource":
                return self

            async def __aexit__(self, *_args: object) -> None:
                return None

            async def aiter_sse(self):
                yield SimpleNamespace(data='{"type":"keepalive"}')
                yield SimpleNamespace(data=json.dumps(terminal_event))

        def fake_connect_sse(*_args: object, **_kwargs: object) -> SuccessfulEventSource:
            return SuccessfulEventSource()

        async def fake_background_heartbeat(*_args: object, **_kwargs: object) -> None:
            return None

        monkeypatch.setattr(relay_sandbox_events_module.httpx_sse, "aconnect_sse", fake_connect_sse)
        monkeypatch.setattr(relay_sandbox_events_module, "_background_heartbeat", fake_background_heartbeat)

        sandbox_gone = await _relay_loop(
            events_url="https://sandbox.example/events",
            headers={"Authorization": "Bearer token"},
            params={},
            redis_stream=cast(TaskRunRedisStream, redis_stream),
            run_id="run-id",
            task_id="task-id",
        )

        redis_stream.write_event.assert_awaited_once_with(terminal_event)
        assert sandbox_gone is False
        redis_stream.mark_complete.assert_awaited_once()
        redis_stream.mark_error.assert_not_awaited()

    async def test_permission_request_dispatches_to_broker(self, monkeypatch: pytest.MonkeyPatch) -> None:
        redis_stream = SimpleNamespace(
            write_event=AsyncMock(),
            mark_complete=AsyncMock(),
            mark_error=AsyncMock(),
        )
        permission_event = {
            "type": "notification",
            "notification": {
                "method": "_posthog/permission_request",
                "params": {
                    "requestId": "perm-1",
                    "options": [{"kind": "allow_once", "optionId": "allow"}],
                    "toolCall": {"_meta": {"claudeCode": {"toolName": "Bash"}}, "rawInput": {"command": "ls"}},
                },
            },
        }
        terminal_event = {
            "type": "notification",
            "notification": {"method": "_posthog/task_complete"},
        }
        # mode="interactive" keeps the turn-complete thread-update path out of
        # this test, which only cares about permission dispatch.
        task_run = SimpleNamespace(id="run-id", mode="interactive")
        dispatch_mock = MagicMock()

        class SuccessfulEventSource:
            response = SimpleNamespace(raise_for_status=lambda: None)

            async def __aenter__(self) -> "SuccessfulEventSource":
                return self

            async def __aexit__(self, *_args: object) -> None:
                return None

            async def aiter_sse(self):
                yield SimpleNamespace(data=json.dumps(permission_event))
                yield SimpleNamespace(data=json.dumps(terminal_event))

        def fake_connect_sse(*_args: object, **_kwargs: object) -> SuccessfulEventSource:
            return SuccessfulEventSource()

        async def fake_background_heartbeat(*_args: object, **_kwargs: object) -> None:
            return None

        async def fake_to_thread(func, *args):
            func(*args)

        monkeypatch.setattr(relay_sandbox_events_module.httpx_sse, "aconnect_sse", fake_connect_sse)
        monkeypatch.setattr(relay_sandbox_events_module, "_background_heartbeat", fake_background_heartbeat)
        monkeypatch.setattr(relay_sandbox_events_module.asyncio, "to_thread", fake_to_thread)
        monkeypatch.setattr(relay_sandbox_events_module, "_broker_permission_request", dispatch_mock)

        await _relay_loop(
            events_url="https://sandbox.example/events",
            headers={"Authorization": "Bearer token"},
            params={},
            redis_stream=cast(TaskRunRedisStream, redis_stream),
            run_id="run-id",
            task_id="task-id",
            task_run=cast(TaskRun, task_run),
        )

        redis_stream.write_event.assert_any_await(permission_event)
        dispatch_mock.assert_called_once_with(
            task_run,
            {
                "request_id": "perm-1",
                "tool_call": {"_meta": {"claudeCode": {"toolName": "Bash"}}, "rawInput": {"command": "ls"}},
                "options": [{"optionId": "allow", "kind": "allow_once", "name": ""}],
            },
        )
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

    async def test_deferred_relay_leaves_terminal_stream_completion_to_workflow(
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

        marked_complete = await _mark_error_unless_run_is_terminal(
            redis_stream,
            "run-id",
            "late relay error",
            finalize_stream=False,
        )

        assert marked_complete is True
        redis_stream_mock.mark_complete.assert_not_awaited()
        redis_stream_mock.mark_error.assert_not_awaited()

    async def test_normal_stream_close_reconnects_before_terminal_event(self, monkeypatch: pytest.MonkeyPatch) -> None:
        redis_stream = SimpleNamespace(
            write_event=AsyncMock(),
            mark_complete=AsyncMock(),
            mark_error=AsyncMock(),
        )
        sleep_mock = AsyncMock()
        connect_attempts = 0

        class EmptyEventSource:
            response = SimpleNamespace(raise_for_status=lambda: None)

            async def __aenter__(self) -> "EmptyEventSource":
                return self

            async def __aexit__(self, *_args: object) -> None:
                return None

            async def aiter_sse(self):
                events: list[SimpleNamespace] = []
                for event in events:
                    yield event

        terminal_event = {
            "type": "notification",
            "notification": {"method": "_posthog/task_complete"},
        }

        class TerminalEventSource(EmptyEventSource):
            async def aiter_sse(self):
                yield SimpleNamespace(data=json.dumps(terminal_event))

        def fake_connect_sse(*_args: object, **_kwargs: object) -> EmptyEventSource:
            nonlocal connect_attempts
            connect_attempts += 1
            return EmptyEventSource() if connect_attempts == 1 else TerminalEventSource()

        async def fake_background_heartbeat(*_args: object, **_kwargs: object) -> None:
            return None

        monkeypatch.setattr(relay_sandbox_events_module.httpx_sse, "aconnect_sse", fake_connect_sse)
        monkeypatch.setattr(relay_sandbox_events_module.asyncio, "sleep", sleep_mock)
        monkeypatch.setattr(relay_sandbox_events_module, "_background_heartbeat", fake_background_heartbeat)

        sandbox_gone = await _relay_loop(
            events_url="https://sandbox.example/events",
            headers={"Authorization": "Bearer token"},
            params={},
            redis_stream=cast(TaskRunRedisStream, redis_stream),
            run_id="run-id",
            task_id="task-id",
        )

        assert connect_attempts == 2
        assert sandbox_gone is False
        sleep_mock.assert_awaited_once_with(2)
        redis_stream.write_event.assert_awaited_once_with(terminal_event)
        redis_stream.mark_complete.assert_awaited_once()
        redis_stream.mark_error.assert_not_awaited()

    async def test_normal_stream_close_marks_sandbox_gone_after_reconnects_exhausted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        redis_stream = SimpleNamespace(
            write_event=AsyncMock(),
            mark_complete=AsyncMock(),
            mark_error=AsyncMock(),
        )
        sleep_mock = AsyncMock()
        connect_attempts = 0

        class EmptyEventSource:
            response = SimpleNamespace(raise_for_status=lambda: None)

            async def __aenter__(self) -> "EmptyEventSource":
                return self

            async def __aexit__(self, *_args: object) -> None:
                return None

            async def aiter_sse(self):
                if getattr(self, "emit_event", False):
                    yield SimpleNamespace()

        def fake_connect_sse(*_args: object, **_kwargs: object) -> EmptyEventSource:
            nonlocal connect_attempts
            connect_attempts += 1
            return EmptyEventSource()

        async def fake_background_heartbeat(*_args: object, **_kwargs: object) -> None:
            return None

        monkeypatch.setattr(relay_sandbox_events_module.httpx_sse, "aconnect_sse", fake_connect_sse)
        monkeypatch.setattr(relay_sandbox_events_module.asyncio, "sleep", sleep_mock)
        monkeypatch.setattr(relay_sandbox_events_module, "_background_heartbeat", fake_background_heartbeat)

        sandbox_gone = await _relay_loop(
            events_url="https://sandbox.example/events",
            headers={"Authorization": "Bearer token"},
            params={},
            redis_stream=cast(TaskRunRedisStream, redis_stream),
            run_id="run-id",
            task_id="task-id",
        )

        assert connect_attempts == relay_sandbox_events_module.MAX_RECONNECT_ATTEMPTS + 1
        assert sandbox_gone is True
        assert [awaited.args[0] for awaited in sleep_mock.await_args_list] == [2, 4, 6, 8, 10]
        redis_stream.write_event.assert_not_awaited()
        redis_stream.mark_complete.assert_not_awaited()
        redis_stream.mark_error.assert_awaited_once_with("Lost connection to sandbox after 5 reconnection attempts")

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
            def __init__(self, stream_key: str, use_dedicated: bool = False) -> None:
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
                return SimpleNamespace(
                    task=SimpleNamespace(created_by=SimpleNamespace(id=123), origin_product=None), state={}
                )

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

        with pytest.raises(ApplicationError, match="relay error") as exc_info:
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

        # An error sentinel was written to the stream, so the failure must be
        # non-retryable — a retried attempt would append events past the
        # sentinel that disconnected consumers never see.
        assert exc_info.value.non_retryable is True
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
        execute_activity_mock.return_value = True
        monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", execute_activity_mock)
        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", MagicMock())

        await workflow._relay_sandbox_events(
            "https://sandbox.example",
            "connect-token",
            sandbox_id="sandbox-123",
        )

        assert execute_activity_mock.await_args is not None
        args, kwargs = execute_activity_mock.await_args
        assert args[0] is relay_sandbox_events_module.relay_sandbox_events_deferred_completion
        assert kwargs["start_to_close_timeout"] == RELAY_SANDBOX_EVENTS_START_TO_CLOSE_TIMEOUT
        assert workflow._sandbox_gone is True


def _agent_chunk_event(text: str) -> dict:
    return {
        "type": "notification",
        "notification": {
            "method": "session/update",
            "params": {"update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": text}}},
        },
    }


def _agent_message_event(text: str) -> dict:
    return {
        "type": "notification",
        "notification": {
            "method": "session/update",
            "params": {"update": {"sessionUpdate": "agent_message", "content": {"type": "text", "text": text}}},
        },
    }


class TestFinalMessageTracker:
    def test_snapshots_joined_prose_at_end_of_turn(self) -> None:
        tracker = FinalMessageTracker()
        tracker.collect(_agent_chunk_event("Weekly "))
        tracker.collect(_agent_chunk_event("summary."))

        assert tracker.end_turn() == "Weekly summary."

    def test_snapshots_full_agent_message_at_end_of_turn(self) -> None:
        tracker = FinalMessageTracker()
        tracker.collect(_agent_message_event("Weekly summary."))

        assert tracker.end_turn() == "Weekly summary."

    def test_tool_only_turn_returns_none_so_prior_report_survives(self) -> None:
        tracker = FinalMessageTracker()
        tracker.collect(_agent_chunk_event("The report."))
        assert tracker.end_turn() == "The report."

        assert tracker.end_turn() is None

    def test_later_turn_replaces_earlier_one(self) -> None:
        tracker = FinalMessageTracker()
        tracker.collect(_agent_chunk_event("First turn."))
        assert tracker.end_turn() == "First turn."
        tracker.collect(_agent_chunk_event("Second turn."))
        assert tracker.end_turn() == "Second turn."

    def test_reset_drops_partial_turn(self) -> None:
        tracker = FinalMessageTracker()
        tracker.collect(_agent_chunk_event("half a mess"))
        tracker.reset()

        assert tracker.end_turn() is None

    def test_truncates_to_cap(self) -> None:
        tracker = FinalMessageTracker()
        tracker.collect(_agent_chunk_event("x" * (FINAL_MESSAGE_MAX_CHARS + 100)))

        result = tracker.end_turn()
        assert result is not None
        assert len(result) == FINAL_MESSAGE_MAX_CHARS

    @parameterized.expand(
        [
            (
                "tool_call_update",
                {
                    "type": "notification",
                    "notification": {"method": "session/update", "params": {"update": {"sessionUpdate": "tool_call"}}},
                },
            ),
            ("non_session_method", {"type": "notification", "notification": {"method": "_posthog/console"}}),
            ("keepalive", {"type": "keepalive"}),
        ]
    )
    def test_non_prose_events_are_ignored(self, _name, event) -> None:
        tracker = FinalMessageTracker()
        tracker.collect(event)

        assert tracker.end_turn() is None


@pytest.mark.django_db
class TestPersistFinalMessage:
    def _make_run(self, **kwargs) -> TaskRun:
        from posthog.models import Organization, Team

        organization = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=organization, name="Test Team")
        task = Task.objects.create(team=team, title="t", description="d")
        return task.create_run(mode="background", **kwargs)

    def test_merges_final_message_into_existing_output(self) -> None:
        run = self._make_run()
        run.output = {"pr_url": "https://github.com/o/r/pull/1"}
        run.save(update_fields=["output", "updated_at"])

        _persist_final_message(str(run.id), "The report.")

        run.refresh_from_db()
        assert run.output == {"pr_url": "https://github.com/o/r/pull/1", "final_message": "The report."}

    def test_sets_output_when_none(self) -> None:
        run = self._make_run()

        _persist_final_message(str(run.id), "The report.")

        run.refresh_from_db()
        assert run.output == {"final_message": "The report."}

    def test_missing_run_does_not_raise(self) -> None:
        _persist_final_message("00000000-0000-0000-0000-000000000000", "The report.")


class TestFlushPendingText:
    """Coalescing many chunks into one agent_text_delta signal keeps the parent workflow's
    history small enough to replay under the 2s deadlock budget."""

    async def test_coalesces_buffered_parts_into_one_signal(self) -> None:
        handle = AsyncMock()
        parts = ["Hel", "lo, ", "world"]
        last_flush = [0.0]

        await _flush_pending_text(handle, parts, last_flush)

        # One signal carrying the joined prose; buffer drained; flush time advanced.
        handle.signal.assert_awaited_once_with("agent_text_delta", arg="Hello, world")
        assert parts == []
        assert last_flush[0] > 0.0

    async def test_empty_buffer_sends_no_signal_but_records_flush(self) -> None:
        handle = AsyncMock()
        last_flush = [0.0]

        await _flush_pending_text(handle, [], last_flush)

        # Recording the flush time even on an empty buffer keeps the interval honest.
        assert last_flush[0] > 0.0
        handle.signal.assert_not_awaited()

    async def test_no_handle_still_clears_buffer(self) -> None:
        parts = ["dropped"]
        await _flush_pending_text(None, parts, [0.0])
        assert parts == []


class TestShouldSignalWorkflowHeartbeat:
    @parameterized.expand(
        [
            # Loop runs carry a 2-minute idle window; a quiet in-flight turn past that
            # window must still keep the workflow alive (the mid-turn teardown bug).
            ("mid_turn_quiet_past_short_run_window", True, 300.0, 120.0, True),
            # The floor is the background default, not unbounded: a turn that hung
            # without an end_of_turn stops pinning the sandbox past that window.
            (
                "mid_turn_quiet_past_default_window",
                True,
                float(INACTIVITY_TIMEOUT_DEFAULT_SECONDS) + 60.0,
                120.0,
                False,
            ),
            # Idle after end_of_turn: the short loop window applies and the run winds down.
            ("idle_agent_stale_events", False, 300.0, 120.0, False),
            ("mid_turn_fresh_events", True, 30.0, 120.0, True),
            # Runs with a window above the default keep their longer window mid-turn.
            ("mid_turn_long_window_still_fresh", True, float(INACTIVITY_TIMEOUT_DEFAULT_SECONDS) + 60.0, 3600.0, True),
        ]
    )
    def test_freshness_gating(
        self,
        _name: str,
        agent_active: bool,
        event_age_seconds: float,
        inactivity_timeout_seconds: float,
        expected: bool,
    ) -> None:
        now = 100_000.0
        assert (
            _should_signal_workflow_heartbeat(
                now=now,
                last_event_time=[now - event_age_seconds],
                last_workflow_signal=[now - HEARTBEAT_INTERVAL_SECONDS - 1.0],
                agent_active=[agent_active],
                inactivity_timeout_seconds=inactivity_timeout_seconds,
            )
            is expected
        )

    @parameterized.expand(
        [
            ("no_events_yet", [0.0], None, False),
            ("signaled_within_interval", None, [100_000.0 - 1.0], False),
        ]
    )
    def test_rate_and_bootstrap_gating(
        self,
        _name: str,
        last_event_time: list[float] | None,
        last_workflow_signal: list[float] | None,
        expected: bool,
    ) -> None:
        now = 100_000.0
        assert (
            _should_signal_workflow_heartbeat(
                now=now,
                last_event_time=last_event_time if last_event_time is not None else [now - 10.0],
                last_workflow_signal=last_workflow_signal,
                agent_active=[True],
                inactivity_timeout_seconds=120.0,
            )
            is expected
        )
