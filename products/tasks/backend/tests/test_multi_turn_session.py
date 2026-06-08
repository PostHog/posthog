import json
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from asgiref.sync import sync_to_async
from parameterized import parameterized
from pydantic import BaseModel

from posthog.models import Integration, Organization, Team
from posthog.models.user import User

from products.tasks.backend.models import TaskRun
from products.tasks.backend.services.custom_prompt_internals import (
    AgentError,
    CustomPromptSandboxContext,
    EmptyAgentTurnError,
    _extract_agent_error,
    create_task_and_trigger,
    poll_for_turn,
)
from products.tasks.backend.services.custom_prompt_multi_turn_runner import _EMPTY_TURN_RETRY_NUDGE, MultiTurnSession
from products.tasks.backend.tests.agent_log_fixtures import (
    FakeTaskRun,
    _agent_error_line,
    _agent_message_line,
    _cost_less_usage_update_line,
    _end_turn_line,
    _usage_update_line,
    _user_message_line,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class _Resp(BaseModel):
    value: str


class TestPollForTurnEmptyEndTurn:
    @pytest.mark.asyncio
    async def test_raises_empty_agent_turn_error_with_offsets(self):
        """poll_for_turn must translate the _check_logs empty-end_turn flag into a
        typed exception so the caller can retry instead of polling until timeout."""
        turn_1 = [_agent_message_line("first"), _end_turn_line()]
        turn_2_empty = [_user_message_line("prompt"), _end_turn_line()]
        log = "\n".join(turn_1 + turn_2_empty)
        skip = len(turn_1)

        with (
            patch("posthog.storage.object_storage.read", return_value=log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch(
                "products.tasks.backend.services.custom_prompt_internals.POLL_INTERVAL_SECONDS",
                0,
            ),
        ):
            with pytest.raises(EmptyAgentTurnError) as exc_info:
                await poll_for_turn(FakeTaskRun(), skip_lines=skip)

        # Carries log offsets so the caller can resume from the tail on retry
        # instead of re-streaming already-printed lines.
        assert exc_info.value.total_lines == len(turn_1) + len(turn_2_empty)
        assert exc_info.value.printed_lines >= 0

    @pytest.mark.asyncio
    async def test_text_before_end_turn_across_polls_is_not_empty(self):
        """When agent_message arrives in one poll and end_turn in the next, poll_for_turn
        must recognize the turn as complete — not raise EmptyAgentTurnError and cause a
        spurious retry."""
        turn_1 = [_agent_message_line("prev"), _end_turn_line()]
        # Current turn: prompt, then text (poll 1 sees this), then end_turn (poll 2 sees this).
        turn_2_with_text = [_user_message_line("next"), _agent_message_line("current-turn-text")]
        turn_2_end_turn = [_end_turn_line()]
        skip = len(turn_1)
        # Log grows monotonically across polls — first poll has no end_turn yet,
        # second poll appends it after the agent_message of poll 1 has already advanced
        # the cursor past it.
        logs = [
            "\n".join(turn_1 + turn_2_with_text),
            "\n".join(turn_1 + turn_2_with_text + turn_2_end_turn),
        ]
        poll_iter = iter(logs)

        def next_log(*_args, **_kwargs):
            return next(poll_iter)

        # Poll 1 returns (False, text, ...) — falls through to the TaskRun refresh
        # to check for terminal status. Patch it to a running status so the loop continues.
        fake_task_run = FakeTaskRun()
        with (
            patch("posthog.storage.object_storage.read", side_effect=next_log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 0),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake_task_run),
        ):
            last_message, _, total_lines, _ = await poll_for_turn(fake_task_run, skip_lines=skip)
        assert last_message == "current-turn-text"
        assert total_lines == len(turn_1) + len(turn_2_with_text) + len(turn_2_end_turn)

    @pytest.mark.asyncio
    async def test_poll_handles_s3_shrink_then_recovery_without_duplicates(self):
        """End-to-end regression: if S3 briefly serves a truncated log between polls,
        cursor clamps in poll_for_turn + _stream_new_lines must prevent already-streamed
        lines from being re-emitted or re-parsed when the log recovers."""
        # Poll 1: user_message only (turn in progress).
        # Poll 2: S3 truncated (1 line instead of 2).
        # Poll 3: full turn visible — agent_message + end_turn appended.
        poll_1_lines = [_user_message_line("prompt"), _agent_message_line("partial-thought")]
        poll_2_lines = [_user_message_line("prompt")]  # S3 shrunk — intentionally missing line 2
        poll_3_lines = [*poll_1_lines, _agent_message_line("final-answer"), _end_turn_line()]
        logs = ["\n".join(poll_1_lines), "\n".join(poll_2_lines), "\n".join(poll_3_lines)]
        poll_iter = iter(logs)

        def next_log(*_args, **_kwargs):
            return next(poll_iter)

        captured: list[str] = []
        fake_task_run = FakeTaskRun()
        with (
            patch("posthog.storage.object_storage.read", side_effect=next_log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 0),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake_task_run),
        ):
            last_message, _, total_lines, printed_lines = await poll_for_turn(
                fake_task_run, skip_lines=0, output_fn=captured.append, verbose=True
            )

        assert last_message == "final-answer"
        # Every raw line streamed exactly once, in log order — no re-emission after the shrink.
        assert captured == poll_3_lines
        # Cursors settled on the final (recovered) line count, not the truncated one.
        assert total_lines == len(poll_3_lines)
        assert printed_lines == len(poll_3_lines)


class TestPollForTurnStaleSalvage:
    """When the sandbox SDK never emits the closing end_turn after the agent's final
    message (an intermittent race — the turn's cost is left null and the log goes quiet),
    poll_for_turn must salvage the last message once the log is conclusively stale rather
    than polling until MAX_POLL_SECONDS and failing a run that actually completed."""

    @pytest.mark.asyncio
    async def test_salvages_last_message_when_end_turn_never_arrives(self):
        # Agent's close-out message + a final usage_update, but no end_turn line — the
        # exact shape of the prod failures (no result of any stopReason ever written).
        log = "\n".join([_agent_message_line("close-out summary"), _usage_update_line(165000)])
        fake = FakeTaskRun()
        with (
            patch("posthog.storage.object_storage.read", return_value=log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 10),
            patch("products.tasks.backend.services.custom_prompt_internals.STALE_TURN_SALVAGE_SECONDS", 30),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake),
        ):
            last_message, _, total_lines, _ = await poll_for_turn(fake, skip_lines=0)

        assert last_message == "close-out summary"
        assert total_lines == 2

    @pytest.mark.asyncio
    async def test_does_not_salvage_while_log_approaches_threshold(self):
        # New lines arrive after 2 silent polls (stale climbs to 20, one poll short of the
        # 30s threshold) and each tail carries the null-cost usage_update fingerprint. So the
        # ONLY thing keeping this still-active turn from being salvaged is the staleness
        # reset on each new line — it completes via its real end_turn, not the salvage path.
        c1 = [_agent_message_line("working"), _usage_update_line()]
        c2 = [*c1, _agent_message_line("still working"), _usage_update_line()]
        final = [*c2, _agent_message_line("final answer"), _end_turn_line()]
        logs = ["\n".join(c1)] * 3 + ["\n".join(c2)] * 3 + ["\n".join(final)]
        poll_iter = iter(logs)

        def next_log(*_args, **_kwargs):
            return next(poll_iter, "\n".join(final))

        fake = FakeTaskRun()
        with (
            patch("posthog.storage.object_storage.read", side_effect=next_log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 10),
            patch("products.tasks.backend.services.custom_prompt_internals.STALE_TURN_SALVAGE_SECONDS", 30),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake),
        ):
            last_message, _, total_lines, _ = await poll_for_turn(fake, skip_lines=0)

        assert last_message == "final answer"
        assert total_lines == len(final)

    @parameterized.expand(
        [
            ("no_usage_update_tail", []),
            ("populated_cost_tail", [_usage_update_line(1000, cost=0.42)]),
            ("cost_key_absent", [_cost_less_usage_update_line()]),
            ("error_after_usage_update", [_usage_update_line(), _agent_error_line("provider 500", "provider_error")]),
        ]
    )
    async def test_does_not_salvage_without_finalization_fingerprint(self, _name, tail_lines):
        # Agent message present and the log is long-stale, but the tail is not an explicit
        # null-cost usage_update — a mid-turn gap, an old cost-less usage line, or a terminal
        # error after accounting. None are the dropped-finalization case, so keep polling
        # (here to the cap) rather than salvage an unfinished or failed turn.
        log = "\n".join([_agent_message_line("intermediate"), *tail_lines])
        fake = FakeTaskRun()
        with (
            patch("posthog.storage.object_storage.read", return_value=log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 600),
            patch("products.tasks.backend.services.custom_prompt_internals.STALE_TURN_SALVAGE_SECONDS", 30),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake),
        ):
            with pytest.raises(RuntimeError, match="timed out"):
                await poll_for_turn(fake, skip_lines=0)


class TestPollForTurnTerminalDrain:
    """Terminal-status drain must recover an agent_message from *this* turn only.

    When the TaskRun reaches a terminal status (FAILED/CANCELLED/COMPLETED) without
    emitting `end_turn`, `_drain_final_log` re-reads the log and walks backward for
    the trailing agent_message. The walk must be bounded by the start-of-turn cursor
    so it never returns a previous turn's response in a multi-turn session.
    """

    @pytest.mark.asyncio
    async def test_terminal_status_does_not_return_previous_turn_message(self):
        """Regression: turn 2 hits terminal status with no agent_message of its own.
        The drain must raise RuntimeError, NOT silently return turn 1's response."""
        turn_1 = [_agent_message_line("turn-1-response"), _end_turn_line()]
        # Turn 2 prompt + tool churn, but the agent died before emitting any agent_message
        # AND before emitting end_turn (so the empty_end_turn path is not what triggers drain).
        turn_2_partial = [_user_message_line("followup question"), _usage_update_line(0)]

        log = "\n".join(turn_1 + turn_2_partial)
        skip = len(turn_1)  # start-of-turn-2 cursor — what MultiTurnSession passes

        # Simulate the task reaching FAILED status mid-poll
        fake_task_run = FakeTaskRun(status="failed", error_message="sandbox killed")

        with (
            patch("posthog.storage.object_storage.read", return_value=log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 0),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake_task_run),
        ):
            with pytest.raises(RuntimeError, match="terminal status"):
                await poll_for_turn(fake_task_run, skip_lines=skip)

    @pytest.mark.asyncio
    async def test_terminal_status_recovers_mid_turn_agent_message(self):
        """The original commit's intent must still hold: when the agent emitted an
        agent_message earlier in *this* turn but the workflow then hit terminal status
        without `end_turn`, the drain recovers that message. Verified with skip_lines>0
        so we're sure the scan walks the current-turn slice, not just [0..end)."""
        turn_1 = [_agent_message_line("turn-1-response"), _end_turn_line()]
        # Turn 2: agent emitted text, then died before end_turn (e.g. inactivity timeout)
        turn_2_recoverable = [
            _user_message_line("followup question"),
            _agent_message_line("turn-2-partial-answer"),
            _usage_update_line(0),  # cursor has advanced past the agent_message by now
        ]

        log = "\n".join(turn_1 + turn_2_recoverable)
        skip = len(turn_1)
        fake_task_run = FakeTaskRun(status="failed", error_message="sandbox killed")

        with (
            patch("posthog.storage.object_storage.read", return_value=log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 0),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake_task_run),
        ):
            last_message, _, _, _ = await poll_for_turn(fake_task_run, skip_lines=skip)

        assert last_message == "turn-2-partial-answer"

    @pytest.mark.asyncio
    async def test_terminal_status_first_turn_still_scans_full_log(self):
        """First-turn case (skip_lines=0): the drain scans from 0 as before — no behavior
        change for single-turn or initial-turn callers."""
        turn_1 = [
            _user_message_line("initial prompt"),
            _agent_message_line("partial-before-death"),
            _usage_update_line(0),
        ]
        log = "\n".join(turn_1)
        fake_task_run = FakeTaskRun(status="failed", error_message="sandbox killed")

        with (
            patch("posthog.storage.object_storage.read", return_value=log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 0),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake_task_run),
        ):
            last_message, _, _, _ = await poll_for_turn(fake_task_run, skip_lines=0)

        assert last_message == "partial-before-death"


class TestExtractAgentError:
    @parameterized.expand(
        [
            ("upstream_provider_failure", "API Error: 429 rate_limit_error"),
            ("upstream_connection_error", "API Error: Connection error"),
            ("upstream_stream_terminated", "API Error: terminated"),
            ("agent_error", "Something broke inside the agent"),
        ]
    )
    def test_extracts_category_and_message(self, category, message):
        log = "\n".join([_user_message_line("prompt"), _agent_error_line(message, category=category)])
        result = _extract_agent_error(log)
        assert result == AgentError(message=message, category=category)
        assert result.describe() == f"{category}: {message}"

    def test_extracts_message_without_category(self):
        message = "API Error: 429 rate_limit_error"
        result = _extract_agent_error(_agent_error_line(message))
        assert result == AgentError(message=message, category=None)
        assert result.describe() == message

    def test_returns_none_when_no_error_line(self):
        log = "\n".join([_agent_message_line("hello"), _end_turn_line()])
        assert _extract_agent_error(log) is None

    def test_returns_none_for_empty_log(self):
        assert _extract_agent_error(None) is None
        assert _extract_agent_error("") is None

    def test_ignores_error_lines_before_skip_cursor(self):
        # The previous turn's error must not leak into the current turn's drain.
        turn_1 = [_agent_error_line("old failure", category="agent_error")]
        turn_2 = [
            _user_message_line("retry"),
            _agent_error_line("API Error: 429 rate_limit_error", category="upstream_provider_failure"),
        ]
        log = "\n".join(turn_1 + turn_2)
        result = _extract_agent_error(log, skip_lines=len(turn_1))
        assert result == AgentError(message="API Error: 429 rate_limit_error", category="upstream_provider_failure")

    def test_returns_last_error_when_multiple(self):
        log = "\n".join(
            [
                _agent_error_line("first", category="upstream_connection_error"),
                _agent_error_line("API Error: 429 rate_limit_error", category="upstream_provider_failure"),
            ]
        )
        result = _extract_agent_error(log)
        assert result == AgentError(message="API Error: 429 rate_limit_error", category="upstream_provider_failure")


class TestPollForTurnSurfacesAgentError:
    """On a FAILED terminal status, the drain must surface the agent's classified error
    (category + raw message) on both TaskRun.error_message and the raised RuntimeError
    that Temporal records — never the opaque 'Activity task failed' wrapper."""

    @parameterized.expand(
        [
            ("upstream_provider_failure", "API Error: 429 rate_limit_error"),
            ("upstream_connection_error", "API Error: Connection error"),
            ("upstream_stream_terminated", "API Error: terminated"),
            ("agent_error", "Unhandled exception in agent loop"),
        ]
    )
    @pytest.mark.asyncio
    async def test_surfaces_classified_error(self, category, message):
        turn_1 = [_agent_message_line("turn-1-response"), _end_turn_line()]
        # Turn 2 died with a classified error and no agent_message / end_turn.
        turn_2 = [_user_message_line("followup"), _usage_update_line(0), _agent_error_line(message, category=category)]
        log = "\n".join(turn_1 + turn_2)
        skip = len(turn_1)
        # The workflow recorded the generic Temporal wrapper — the drain must override it.
        fake_task_run = FakeTaskRun(status="failed", error_message="Activity task failed")

        persist = AsyncMock()
        with (
            patch("posthog.storage.object_storage.read", return_value=log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 0),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake_task_run),
            patch(
                "products.tasks.backend.services.custom_prompt_internals._persist_task_run_error_message",
                new=persist,
            ),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                await poll_for_turn(fake_task_run, skip_lines=skip)

        expected = f"{category}: {message}"
        # Temporal activity failure carries the classified error, not "Activity task failed".
        assert expected in str(exc_info.value)
        assert "Activity task failed" not in str(exc_info.value)
        # The same classified error is persisted onto TaskRun.error_message.
        persist.assert_awaited_once_with(str(fake_task_run.id), expected)

    @pytest.mark.asyncio
    async def test_acceptance_provider_failure_429(self):
        turn = [
            _user_message_line("summarize"),
            _agent_error_line("API Error: 429 rate_limit_error", category="upstream_provider_failure"),
        ]
        fake_task_run = FakeTaskRun(status="failed", error_message="Activity task failed")

        persist = AsyncMock()
        with (
            patch("posthog.storage.object_storage.read", return_value="\n".join(turn)),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 0),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake_task_run),
            patch(
                "products.tasks.backend.services.custom_prompt_internals._persist_task_run_error_message",
                new=persist,
            ),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                await poll_for_turn(fake_task_run, skip_lines=0)

        # The value persisted to TaskRun.error_message carries the category + 429 text.
        expected = "upstream_provider_failure: API Error: 429 rate_limit_error"
        persist.assert_awaited_once_with(str(fake_task_run.id), expected)
        assert "upstream_provider_failure" in str(exc_info.value)
        assert "429 rate_limit_error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_error_without_category_falls_back_to_message(self):
        # Older agent build: no error_category, but the raw message still beats the wrapper.
        turn = [_user_message_line("summarize"), _agent_error_line("API Error: 429 rate_limit_error")]
        fake_task_run = FakeTaskRun(status="failed", error_message="Activity task failed")

        persist = AsyncMock()
        with (
            patch("posthog.storage.object_storage.read", return_value="\n".join(turn)),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 0),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake_task_run),
            patch(
                "products.tasks.backend.services.custom_prompt_internals._persist_task_run_error_message",
                new=persist,
            ),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                await poll_for_turn(fake_task_run, skip_lines=0)

        # No category prefix — the raw message is persisted and surfaced.
        persist.assert_awaited_once_with(str(fake_task_run.id), "API Error: 429 rate_limit_error")
        assert "API Error: 429 rate_limit_error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_missing_structured_error_keeps_generic_behavior(self):
        # No _posthog/error line: the drain must keep today's generic message and
        # must not touch TaskRun.error_message.
        turn = [_user_message_line("summarize"), _usage_update_line(0)]
        fake_task_run = FakeTaskRun(status="failed", error_message="Activity task failed")

        persist = AsyncMock()
        with (
            patch("posthog.storage.object_storage.read", return_value="\n".join(turn)),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 0),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake_task_run),
            patch(
                "products.tasks.backend.services.custom_prompt_internals._persist_task_run_error_message",
                new=persist,
            ),
        ):
            with pytest.raises(RuntimeError, match="no agent message") as exc_info:
                await poll_for_turn(fake_task_run, skip_lines=0)

        assert "Activity task failed" in str(exc_info.value)
        persist.assert_not_awaited()
        assert fake_task_run.error_message == "Activity task failed"

    @pytest.mark.asyncio
    async def test_cancelled_status_does_not_surface_agent_error(self):
        # CANCELLED is a user action — even with an agent error present, keep generic behavior.
        turn = [
            _user_message_line("summarize"),
            _agent_error_line("API Error: terminated", category="upstream_stream_terminated"),
        ]
        fake_task_run = FakeTaskRun(status="cancelled", error_message="cancelled by user")

        persist = AsyncMock()
        with (
            patch("posthog.storage.object_storage.read", return_value="\n".join(turn)),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 0),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake_task_run),
            patch(
                "products.tasks.backend.services.custom_prompt_internals._persist_task_run_error_message",
                new=persist,
            ),
        ):
            with pytest.raises(RuntimeError, match="no agent message"):
                await poll_for_turn(fake_task_run, skip_lines=0)

        persist.assert_not_awaited()


class TestMultiTurnSessionRetry:
    """send_followup must retry once on EmptyAgentTurnError and propagate if the retry
    also fails, so upstream sees a typed failure rather than a timeout or parse error."""

    def _make_session(self) -> MultiTurnSession:
        # Bypass MultiTurnSession.start (which creates a real Task) by building the
        # dataclass directly — the retry logic only needs task_run + workflow_handle.
        workflow_handle = AsyncMock()
        workflow_handle.signal = AsyncMock()
        session = MultiTurnSession(
            task=object(),  # type: ignore[arg-type]
            task_run=FakeTaskRun(),  # type: ignore[arg-type]
            _workflow_handle=workflow_handle,
        )
        return session

    @pytest.mark.asyncio
    async def test_happy_path_no_retry(self):
        session = self._make_session()
        agent_response = json.dumps({"value": "ok"})

        with patch(
            "products.tasks.backend.services.custom_prompt_multi_turn_runner.poll_for_turn",
            new=AsyncMock(return_value=(agent_response, None, 10, 5)),
        ):
            result = await session.send_followup("hello", _Resp, label="unit")

        assert result == _Resp(value="ok")
        # Signal sent exactly once on happy path
        assert session._workflow_handle.signal.await_count == 1  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_retries_once_on_empty_end_turn(self):
        session = self._make_session()
        agent_response = json.dumps({"value": "retry-success"})

        poll_mock = AsyncMock(
            side_effect=[
                EmptyAgentTurnError("empty", total_lines=12, printed_lines=7),
                (agent_response, None, 20, 10),
            ]
        )
        with patch(
            "products.tasks.backend.services.custom_prompt_multi_turn_runner.poll_for_turn",
            new=poll_mock,
        ):
            result = await session.send_followup("please prioritize", _Resp, label="priority")

        assert result == _Resp(value="retry-success")
        # Signal sent twice: original + retry with nudge suffix
        assert session._workflow_handle.signal.await_count == 2  # type: ignore[union-attr]
        retry_call = session._workflow_handle.signal.await_args_list[1]  # type: ignore[union-attr]
        retry_message = retry_call.args[1]
        assert retry_message == "please prioritize" + _EMPTY_TURN_RETRY_NUDGE
        # Offsets must advance past the empty-turn lines so the retry polls from the tail
        assert session.log_lines_seen == 20
        assert session.printed_lines == 10

    @pytest.mark.asyncio
    async def test_raises_after_two_consecutive_empty_turns(self):
        session = self._make_session()

        poll_mock = AsyncMock(
            side_effect=[
                EmptyAgentTurnError("empty-1", total_lines=12, printed_lines=7),
                EmptyAgentTurnError("empty-2", total_lines=15, printed_lines=8),
            ]
        )
        with patch(
            "products.tasks.backend.services.custom_prompt_multi_turn_runner.poll_for_turn",
            new=poll_mock,
        ):
            with pytest.raises(EmptyAgentTurnError, match="twice"):
                await session.send_followup("x", _Resp, label="priority")

        # Still signaled twice — we *tried* to retry before giving up
        assert session._workflow_handle.signal.await_count == 2  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_full_retry_path_with_real_poll_loop(self):
        """End-to-end integration: send_followup → real poll_for_turn → real _check_logs
        → EmptyAgentTurnError → retry → real _check_logs finds agent_message → parsed.

        The log fixture mirrors the production incident: initial turn with a real
        agent_message, then an empty turn (usage_update + end_turn, no agent_message),
        then a recovered turn on retry. Log visibility grows as send_followup_message
        signals arrive — simulating how the sandbox appends lines after each prompt.
        """
        fixture_lines = (FIXTURES_DIR / "agent_log_empty_end_turn_retry.jsonl").read_text().strip().split("\n")
        assert len(fixture_lines) == 8  # sanity: fixture hasn't drifted

        # Log state evolves with each followup signal. Heartbeat signals (1 positional
        # arg) don't advance; send_followup_message signals (2 positional args) do.
        followup_signals = {"count": 0}

        async def record_signal(*args, **kwargs):
            if len(args) >= 2:
                followup_signals["count"] += 1

        def current_log(*_args, **_kwargs):
            n = followup_signals["count"]
            if n == 0:
                visible = 2  # only the prior completed turn
            elif n == 1:
                visible = 5  # empty turn appended (user_message_chunk + usage_update + end_turn)
            else:
                visible = 8  # recovered turn appended (user_message_chunk + agent_message + end_turn)
            return "\n".join(fixture_lines[:visible])

        session = self._make_session()
        session._workflow_handle.signal = AsyncMock(side_effect=record_signal)  # type: ignore[union-attr,method-assign]  # ty: ignore[invalid-assignment]
        # Session state as if MultiTurnSession.start already consumed the initial turn.
        session.log_lines_seen = 2
        session.printed_lines = 2

        with (
            patch("posthog.storage.object_storage.read", side_effect=current_log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 0),
        ):
            result = await session.send_followup("please respond", _Resp, label="priority")

        assert result == _Resp(value="recovered-after-retry")
        # Two followup signals: the original + the retry with nudge suffix.
        assert followup_signals["count"] == 2
        signal_calls = session._workflow_handle.signal.await_args_list  # type: ignore[union-attr]
        followup_calls = [c for c in signal_calls if len(c.args) >= 2]
        assert followup_calls[0].args[1] == "please respond"
        assert followup_calls[1].args[1] == "please respond" + _EMPTY_TURN_RETRY_NUDGE
        # Offsets advanced past the recovered turn.
        assert session.log_lines_seen == 8

    @pytest.mark.asyncio
    async def test_advances_offsets_from_error_before_retrying(self):
        """Regression: the retry must poll from the updated tail. Otherwise it would
        re-see the previous turn's end_turn and think that's still the current turn."""
        session = self._make_session()
        session.log_lines_seen = 5
        session.printed_lines = 3
        agent_response = json.dumps({"value": "ok"})

        captured_skip_lines: list[int] = []

        async def fake_poll(task_run, *, skip_lines=0, printed_lines=0, **kwargs):
            captured_skip_lines.append(skip_lines)
            if len(captured_skip_lines) == 1:
                raise EmptyAgentTurnError("empty", total_lines=99, printed_lines=50)
            return (agent_response, None, 120, 60)

        with patch(
            "products.tasks.backend.services.custom_prompt_multi_turn_runner.poll_for_turn",
            new=fake_poll,
        ):
            await session.send_followup("x", _Resp, label="priority")

        assert captured_skip_lines == [5, 99]


@pytest.mark.django_db(transaction=True)
class TestMultiTurnSessionStartBranch:
    """Regression: an earlier impl rewrote branch='master' to None as a sentinel for
    'use repo default'. That sentinel was removed once callers stopped defaulting to
    'master'. The branch arg must now reach TaskRun.branch unchanged so repos with
    non-master defaults aren't forced into a failing checkout."""

    @staticmethod
    def _setup_team_and_user() -> tuple[Team, User]:
        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team")
        user = User.objects.create(email="branch-test@example.com")
        Integration.objects.create(team=team, kind="github", config={})
        return team, user

    @pytest.mark.asyncio
    @pytest.mark.parametrize("branch", [None, "master", "main", "feature/x"])
    async def test_branch_passed_through_to_task_run(self, branch):
        team, user = await sync_to_async(self._setup_team_and_user)()
        context = CustomPromptSandboxContext(team_id=team.id, user_id=user.id, repository="posthog/posthog")
        agent_response = json.dumps({"value": "ok"})

        with (
            patch("products.tasks.backend.temporal.client.execute_task_processing_workflow"),
            patch(
                "products.tasks.backend.services.custom_prompt_multi_turn_runner.async_connect",
                new=AsyncMock(return_value=MagicMock(get_workflow_handle=MagicMock(return_value=AsyncMock()))),
            ),
            patch(
                "products.tasks.backend.services.custom_prompt_multi_turn_runner.poll_for_turn",
                new=AsyncMock(return_value=(agent_response, None, 1, 1)),
            ),
        ):
            kwargs = {"branch": branch} if branch is not None else {}
            session, _ = await MultiTurnSession.start(
                prompt="hello",
                context=context,
                model=_Resp,
                **kwargs,
            )

        # Re-fetch from DB to confirm the value was actually persisted, not just
        # held in memory by the in-process Task object.
        persisted = await sync_to_async(TaskRun.objects.get)(id=session.task_run.id)
        assert persisted.branch == branch


class TestMultiTurnSessionStartCleanup:
    """Regression: if MultiTurnSession.start raises after create_task_and_trigger
    has already started the workflow (e.g. poll_for_turn fails), the failure path
    must signal completion so the orphaned workflow doesn't run until its
    inactivity timeout."""

    @pytest.mark.asyncio
    async def test_cleans_up_when_initial_poll_fails(self):
        fake_task = MagicMock()
        fake_task.id = "task-id"
        fake_run = MagicMock()
        fake_run.id = "run-id"

        mock_handle = MagicMock()
        mock_handle.signal = AsyncMock()
        mock_client = MagicMock(get_workflow_handle=MagicMock(return_value=mock_handle))

        with (
            patch(
                "products.tasks.backend.services.custom_prompt_multi_turn_runner.create_task_and_trigger",
                new=AsyncMock(return_value=(fake_task, fake_run)),
            ),
            patch(
                "products.tasks.backend.services.custom_prompt_multi_turn_runner.async_connect",
                new=AsyncMock(return_value=mock_client),
            ),
            patch(
                "products.tasks.backend.services.custom_prompt_multi_turn_runner.poll_for_turn",
                new=AsyncMock(side_effect=RuntimeError("storage explode")),
            ),
            pytest.raises(RuntimeError, match="storage explode"),
        ):
            await MultiTurnSession.start(
                prompt="test",
                context=CustomPromptSandboxContext(team_id=1, user_id=2),
                model=_Resp,
            )

        # session.end() must have signalled the workflow exactly once on the cleanup path.
        mock_handle.signal.assert_called_once()


@pytest.mark.django_db(transaction=True)
class TestCreateTaskAndTriggerForwardsContext:
    """Regression: CustomPromptSandboxContext.sandbox_environment_id and
    posthog_mcp_scopes were silently dropped by create_task_and_trigger, so
    least-privilege configs at call sites (e.g. Signals' GitHub-only sandbox,
    repo-selection's read_only MCP scope) had no effect downstream."""

    @staticmethod
    def _setup_team_and_user() -> tuple[Team, User]:
        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team")
        user = User.objects.create(email="ctx-fwd@example.com")
        return team, user

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "ctx_env, ctx_scopes, expected_env, expected_scopes",
        [
            ("env-uuid-abc", "read_only", "env-uuid-abc", "read_only"),
            (None, None, None, "full"),
        ],
    )
    async def test_forwards_sandbox_env_and_scopes(self, ctx_env, ctx_scopes, expected_env, expected_scopes):
        team, user = await sync_to_async(self._setup_team_and_user)()
        context = CustomPromptSandboxContext(
            team_id=team.id,
            user_id=user.id,
            repository="posthog/posthog",
            sandbox_environment_id=ctx_env,
            posthog_mcp_scopes=ctx_scopes,
        )

        mock_task = MagicMock()
        mock_task.latest_run = MagicMock()
        with patch(
            "products.tasks.backend.services.custom_prompt_internals.Task.create_and_run",
            return_value=mock_task,
        ) as mock_create:
            await create_task_and_trigger("prompt", context)

        kwargs = mock_create.call_args.kwargs
        assert kwargs["sandbox_environment_id"] == expected_env
        assert kwargs["posthog_mcp_scopes"] == expected_scopes
