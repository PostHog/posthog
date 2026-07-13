import json

from unittest.mock import AsyncMock, MagicMock, patch

from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, override_settings

from parameterized import parameterized

from products.pulse.backend.agent.async_completion import (
    line_signals_turn_complete,
    pop_completion_context,
    store_completion_context,
)
from products.pulse.backend.agent.sandbox_run import _SandboxRunRef
from products.pulse.backend.api.agent_events import pulse_agent_events
from products.tasks.backend.facade.sandbox import create_sandbox_event_ingest_token
from products.tasks.backend.logic.services.connection_token import reset_sandbox_jwt_key_cache
from products.tasks.backend.tests.test_api import TEST_RSA_PRIVATE_KEY

RUN_ID = "wf-run-1"
TURN_COMPLETE_LINE = json.dumps({"type": "notification", "notification": {"method": "_posthog/turn_complete"}})
PROGRESS_LINE = json.dumps({"type": "notification", "notification": {"method": "session/update"}})


class TestCompletionContextStore(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)

    def test_pop_returns_context_once_then_none(self) -> None:
        # First-wins is what makes a duplicate turn-complete callback complete the activity at most once.
        store_completion_context(RUN_ID, "sb-1", b"token-bytes")

        first = pop_completion_context(RUN_ID)
        assert first is not None
        assert first.sandbox_id == "sb-1"
        assert first.task_token == b"token-bytes"
        assert pop_completion_context(RUN_ID) is None

    def test_pop_missing_run_is_none(self) -> None:
        assert pop_completion_context("never-stored") is None


class TestTurnCompleteDetector(SimpleTestCase):
    @parameterized.expand(
        [
            ("turn_complete", TURN_COMPLETE_LINE, True),
            (
                "end_turn_result",
                json.dumps({"type": "notification", "notification": {"result": {"stopReason": "end_turn"}}}),
                True,
            ),
            ("progress", PROGRESS_LINE, False),
            ("blank", "  ", False),
            ("not_json", "}{", False),
            ("json_array", json.dumps([1, 2, 3]), False),
        ]
    )
    def test_detects_turn_completion(self, _name: str, line: str, expected: bool) -> None:
        assert line_signals_turn_complete(line) is expected


@override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY, SANDBOX_JWT_PUBLIC_KEY=None)
class TestAgentEventsCallback(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        reset_sandbox_jwt_key_cache()
        self.addCleanup(cache.clear)
        self.addCleanup(reset_sandbox_jwt_key_cache)
        self.rf = RequestFactory()

    def _token(self, run_id: str = RUN_ID) -> str:
        ref = _SandboxRunRef(id=run_id, task_id="brief-1", team_id=7, mode="background", state={})
        return create_sandbox_event_ingest_token(ref)

    def _post(self, body: str, token: str | None, run_id: str = RUN_ID):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token is not None else {}
        request = self.rf.post(
            f"/internal/pulse/runs/{run_id}/agent-events/", data=body, content_type="application/x-ndjson", **headers
        )
        return pulse_agent_events(request, run_id)

    def test_turn_complete_line_completes_the_async_activity(self) -> None:
        store_completion_context(RUN_ID, "sb-1", b"token-bytes")
        client = MagicMock()
        handle = client.get_async_activity_handle.return_value
        handle.complete = AsyncMock()
        with patch("posthog.temporal.common.client.sync_connect", return_value=client):
            response = self._post(f"{PROGRESS_LINE}\n{TURN_COMPLETE_LINE}", self._token())

        assert response.status_code == 200
        client.get_async_activity_handle.assert_called_once_with(task_token=b"token-bytes")
        handle.complete.assert_awaited_once()
        assert handle.complete.await_args.args[0] == {"sandbox_id": "sb-1"}
        # Context consumed — a duplicate callback won't double-complete.
        assert pop_completion_context(RUN_ID) is None

    def test_non_terminal_events_do_not_complete(self) -> None:
        store_completion_context(RUN_ID, "sb-1", b"token-bytes")
        with patch("posthog.temporal.common.client.sync_connect") as connect:
            response = self._post(PROGRESS_LINE, self._token())

        assert response.status_code == 200
        connect.assert_not_called()
        assert pop_completion_context(RUN_ID) is not None  # still resolvable

    def test_unknown_run_is_a_noop(self) -> None:
        # Valid token, turn complete, but nothing was launched for this run.
        with patch("posthog.temporal.common.client.sync_connect") as connect:
            response = self._post(TURN_COMPLETE_LINE, self._token())
        assert response.status_code == 200
        connect.assert_not_called()

    def test_missing_token_is_401(self) -> None:
        assert self._post(TURN_COMPLETE_LINE, token=None).status_code == 401

    def test_invalid_token_is_401(self) -> None:
        assert self._post(TURN_COMPLETE_LINE, token="not-a-jwt").status_code == 401

    def test_token_for_other_run_is_403(self) -> None:
        # Token minted for a different run must not drive this run's completion.
        response = self._post(TURN_COMPLETE_LINE, token=self._token(run_id="other-run"))
        assert response.status_code == 403

    def test_oversized_body_is_413(self) -> None:
        # Untrusted agent output must be bounded before buffering; spoof Content-Length so we
        # don't have to build a 5 MB body.
        request = self.rf.post(
            f"/internal/pulse/runs/{RUN_ID}/agent-events/",
            data=TURN_COMPLETE_LINE,
            content_type="application/x-ndjson",
            HTTP_AUTHORIZATION=f"Bearer {self._token()}",
            CONTENT_LENGTH="6000000",
        )
        assert pulse_agent_events(request, RUN_ID).status_code == 413
