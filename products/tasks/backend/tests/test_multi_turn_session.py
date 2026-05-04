import json
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from asgiref.sync import sync_to_async
from pydantic import BaseModel

from posthog.models import Integration, Organization, Team
from posthog.models.user import User

from products.tasks.backend.models import TaskRun
from products.tasks.backend.services.custom_prompt_multi_turn_runner import _EMPTY_TURN_RETRY_NUDGE, MultiTurnSession
from products.tasks.backend.services.custom_prompt_runner import (
    CustomPromptSandboxContext,
    EmptyAgentTurnError,
    _poll_for_turn,
)
from products.tasks.backend.tests.agent_log_fixtures import (
    FakeTaskRun,
    _agent_message_line,
    _end_turn_line,
    _user_message_line,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class _Resp(BaseModel):
    value: str


class TestPollForTurnEmptyEndTurn:
    @pytest.mark.asyncio
    async def test_raises_empty_agent_turn_error_with_offsets(self):
        """_poll_for_turn must translate the _check_logs empty-end_turn flag into a
        typed exception so the caller can retry instead of polling until timeout."""
        turn_1 = [_agent_message_line("first"), _end_turn_line()]
        turn_2_empty = [_user_message_line("prompt"), _end_turn_line()]
        log = "\n".join(turn_1 + turn_2_empty)
        skip = len(turn_1)

        with (
            patch("posthog.storage.object_storage.read", return_value=log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch(
                "products.tasks.backend.services.custom_prompt_runner.POLL_INTERVAL_SECONDS",
                0,
            ),
        ):
            with pytest.raises(EmptyAgentTurnError) as exc_info:
                await _poll_for_turn(FakeTaskRun(), skip_lines=skip)

        # Carries log offsets so the caller can resume from the tail on retry
        # instead of re-streaming already-printed lines.
        assert exc_info.value.total_lines == len(turn_1) + len(turn_2_empty)
        assert exc_info.value.printed_lines >= 0

    @pytest.mark.asyncio
    async def test_text_before_end_turn_across_polls_is_not_empty(self):
        """When agent_message arrives in one poll and end_turn in the next, _poll_for_turn
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
            patch("products.tasks.backend.services.custom_prompt_runner.POLL_INTERVAL_SECONDS", 0),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake_task_run),
        ):
            last_message, _, total_lines, _ = await _poll_for_turn(fake_task_run, skip_lines=skip)
        assert last_message == "current-turn-text"
        assert total_lines == len(turn_1) + len(turn_2_with_text) + len(turn_2_end_turn)

    @pytest.mark.asyncio
    async def test_poll_handles_s3_shrink_then_recovery_without_duplicates(self):
        """End-to-end regression: if S3 briefly serves a truncated log between polls,
        cursor clamps in _poll_for_turn + _stream_new_lines must prevent already-streamed
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
            patch("products.tasks.backend.services.custom_prompt_runner.POLL_INTERVAL_SECONDS", 0),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake_task_run),
        ):
            last_message, _, total_lines, printed_lines = await _poll_for_turn(
                fake_task_run, skip_lines=0, output_fn=captured.append, verbose=True
            )

        assert last_message == "final-answer"
        # Every raw line streamed exactly once, in log order — no re-emission after the shrink.
        assert captured == poll_3_lines
        # Cursors settled on the final (recovered) line count, not the truncated one.
        assert total_lines == len(poll_3_lines)
        assert printed_lines == len(poll_3_lines)


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
            "products.tasks.backend.services.custom_prompt_multi_turn_runner._poll_for_turn",
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
            "products.tasks.backend.services.custom_prompt_multi_turn_runner._poll_for_turn",
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
            "products.tasks.backend.services.custom_prompt_multi_turn_runner._poll_for_turn",
            new=poll_mock,
        ):
            with pytest.raises(EmptyAgentTurnError, match="twice"):
                await session.send_followup("x", _Resp, label="priority")

        # Still signaled twice — we *tried* to retry before giving up
        assert session._workflow_handle.signal.await_count == 2  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_full_retry_path_with_real_poll_loop(self):
        """End-to-end integration: send_followup → real _poll_for_turn → real _check_logs
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
            patch("products.tasks.backend.services.custom_prompt_runner.POLL_INTERVAL_SECONDS", 0),
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
            "products.tasks.backend.services.custom_prompt_multi_turn_runner._poll_for_turn",
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
                "products.tasks.backend.services.custom_prompt_multi_turn_runner._poll_for_turn",
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
