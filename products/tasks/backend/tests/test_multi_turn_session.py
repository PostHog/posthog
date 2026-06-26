import json
import asyncio
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.db import OperationalError

from asgiref.sync import sync_to_async
from parameterized import parameterized
from pydantic import BaseModel

from posthog.models import Integration, Organization, Team
from posthog.models.user import User
from posthog.storage.object_storage import ObjectStorageError

from products.tasks.backend.logic.services.custom_prompt_internals import (
    AgentError,
    CustomPromptSandboxContext,
    EmptyAgentTurnError,
    _extract_agent_error,
    create_task_and_trigger,
    poll_for_turn,
)
from products.tasks.backend.logic.services.custom_prompt_multi_turn_runner import (
    _EMPTY_TURN_RETRY_NUDGE,
    MultiTurnSession,
)
from products.tasks.backend.models import TaskRun
from products.tasks.backend.tests.agent_log_fixtures import (
    FakeTaskRun,
    _agent_error_line,
    _agent_message_chunk_line,
    _agent_message_line,
    _console_line,
    _cost_less_usage_update_line,
    _end_turn_line,
    _progress_line,
    _tool_call_line,
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
                "products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS",
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
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 0),
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
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 0),
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
    """When the SDK drops the closing end_turn after the agent's final message (cost left null,
    log goes quiet), poll_for_turn salvages the message on the timeout path — gated on the
    null-cost fingerprint, a non-terminal status, and STALE_TURN_SALVAGE_SECONDS of silence so a
    turn still emitting near the deadline isn't cut off. Tests patch the budget and floor small."""

    @pytest.mark.asyncio
    async def test_salvages_last_message_when_end_turn_never_arrives(self):
        # Final message + null-cost usage_update, no end_turn — the prod failure shape.
        log = "\n".join([_agent_message_line("close-out summary"), _usage_update_line(165000)])
        fake = FakeTaskRun()
        with (
            patch("posthog.storage.object_storage.read", return_value=log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 10),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.MAX_POLL_SECONDS", 30),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.STALE_TURN_SALVAGE_SECONDS", 15),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake),
        ):
            last_message, _, total_lines, _ = await poll_for_turn(fake, skip_lines=0)

        assert last_message == "close-out summary"
        assert total_lines == 2

    @pytest.mark.asyncio
    async def test_salvages_dropped_finalization_after_active_work(self):
        # Real work across several polls, then end_turn dropped — must still be salvaged. Uses the
        # REAL STALE_TURN_SALVAGE_SECONDS (deliberately not patched) against a 600s budget so a floor
        # set too close to the budget — which would reject a turn that works for minutes and only then
        # drops end_turn (the exact prod failure) — fails this test instead of silently regressing.
        work = [_agent_message_line("partial-1"), _usage_update_line()]
        more = [*work, _agent_message_line("partial-2"), _usage_update_line()]
        done = [*more, _agent_message_line("close-out summary"), _usage_update_line(165000)]
        # Grow for the first three polls (last new lines ~elapsed 30), then quiet to the 600s deadline.
        poll_logs = ["\n".join(work), "\n".join(more), "\n".join(done)]
        poll_iter = iter(poll_logs)

        def next_log(*_args, **_kwargs):
            return next(poll_iter, "\n".join(done))

        fake = FakeTaskRun()
        with (
            patch("posthog.storage.object_storage.read", side_effect=next_log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 10),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.MAX_POLL_SECONDS", 600),
            # STALE_TURN_SALVAGE_SECONDS intentionally NOT patched — exercise the production floor.
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake),
        ):
            last_message, _, total_lines, _ = await poll_for_turn(fake, skip_lines=0)

        assert last_message == "close-out summary"
        assert total_lines == len(done)

    @parameterized.expand(
        [
            ("single_network_audit", [_console_line("agentsh network events")]),
            (
                "audit_then_credential_refresh",
                [_console_line("agentsh network events"), _console_line("Refreshed sandbox credentials: github")],
            ),
            ("sandbox_output", [_console_line("npm install ...", method="_posthog/sandbox_output")]),
            ("setup_progress", [_console_line("cloning repo", method="_posthog/progress")]),
        ]
    )
    async def test_salvages_dropped_finalization_despite_trailing_console_lines(self, _name, trailing):
        # The prod failure shape: the agent emits its close-out + null-cost usage_update, then the relay
        # appends observability side-channels (agentsh network audit, credential refresh, stdout, setup
        # progress) AFTER the fingerprint while the turn hangs. The tail check must skip those and still
        # recognize the dropped finalization — otherwise the run hangs to the poll timeout and fails.
        log = "\n".join([_agent_message_line("close-out summary"), _usage_update_line(165000), *trailing])
        fake = FakeTaskRun()
        with (
            patch("posthog.storage.object_storage.read", return_value=log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 10),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.MAX_POLL_SECONDS", 30),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.STALE_TURN_SALVAGE_SECONDS", 15),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake),
        ):
            last_message, _, total_lines, _ = await poll_for_turn(fake, skip_lines=0)

        assert last_message == "close-out summary"
        assert total_lines == 2 + len(trailing)

    @pytest.mark.asyncio
    async def test_does_not_salvage_when_console_lines_follow_a_live_tail(self):
        # Trailing console noise must NOT manufacture a salvage when the agent's own tail isn't the
        # finalization fingerprint: here the last turn-relevant line is a bare agent_message (no
        # usage_update), so skipping the console lines still finds no fingerprint and the run times out.
        log = "\n".join([_agent_message_line("still working"), _console_line("agentsh network events")])
        fake = FakeTaskRun()
        with (
            patch("posthog.storage.object_storage.read", return_value=log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 10),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.MAX_POLL_SECONDS", 30),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.STALE_TURN_SALVAGE_SECONDS", 15),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake),
        ):
            with pytest.raises(RuntimeError, match="timed out"):
                await poll_for_turn(fake, skip_lines=0)

    @pytest.mark.asyncio
    async def test_max_poll_seconds_overrides_module_budget(self):
        # A caller-supplied max_poll_seconds bounds the loop instead of the module MAX_POLL_SECONDS:
        # the module value is left larger, so the elapsed in the timeout error proves the override won.
        log = _agent_message_line("intermediate")  # no fingerprint — always times out
        fake = FakeTaskRun()
        with (
            patch("posthog.storage.object_storage.read", return_value=log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 10),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.MAX_POLL_SECONDS", 100),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake),
        ):
            with pytest.raises(RuntimeError, match="after 30s"):
                await poll_for_turn(fake, skip_lines=0, max_poll_seconds=30)

    @pytest.mark.asyncio
    async def test_salvage_reassembles_chunked_message(self):
        # Response split across agent_message_chunk slices, then null-cost usage_update — salvage
        # reparses from start-of-turn and returns all chunks, not just the last.
        log = "\n".join(
            [
                _agent_message_chunk_line("Part-one."),
                _agent_message_chunk_line("Part-two."),
                _agent_message_chunk_line("Part-three."),
                _usage_update_line(165000),
            ]
        )
        fake = FakeTaskRun()
        with (
            patch("posthog.storage.object_storage.read", return_value=log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 10),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.MAX_POLL_SECONDS", 30),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.STALE_TURN_SALVAGE_SECONDS", 15),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake),
        ):
            last_message, _, _, _ = await poll_for_turn(fake, skip_lines=0)

        assert last_message == "Part-one.Part-two.Part-three."

    @pytest.mark.asyncio
    async def test_does_not_salvage_turn_active_near_deadline(self):
        # New lines (with the fingerprint tail) arrive on every poll right up to the deadline, so
        # silence never clears the floor — the still-active turn must fail, not be salvaged.
        lines: list[str] = []
        logs = []
        for i in range(1, 6):
            lines += [_agent_message_line(f"chunk-{i}"), _usage_update_line()]
            logs.append("\n".join(lines))
        poll_iter = iter(logs)

        def next_log(*_args, **_kwargs):
            return next(poll_iter, logs[-1])

        fake = FakeTaskRun()
        with (
            patch("posthog.storage.object_storage.read", side_effect=next_log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 10),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.MAX_POLL_SECONDS", 50),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.STALE_TURN_SALVAGE_SECONDS", 15),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake),
        ):
            with pytest.raises(RuntimeError, match="timed out"):
                await poll_for_turn(fake, skip_lines=0)

    @pytest.mark.asyncio
    async def test_declines_salvage_when_reread_shows_nonterminal_activity(self):
        # The silence floor was crossed, but the salvage reread's tail is a bare agent_message (no
        # end_turn, no null-cost usage_update) — the turn was still producing output, not finalized.
        # The tail, not a line count, is the discriminator: a non-terminal tail must decline and time
        # out rather than truncate a possibly-live turn.
        quiet = [_agent_message_line("close-out summary"), _usage_update_line(165000)]  # fingerprint tail
        grown = [*quiet, _agent_message_line("actually still going")]  # non-terminal tail on the reread
        calls = {"n": 0}

        def next_log(*_args, **_kwargs):
            calls["n"] += 1
            # Polls 1-3 are steady (quiet); the 4th read is the salvage reread, which ends mid-stream.
            return "\n".join(grown) if calls["n"] > 3 else "\n".join(quiet)

        fake = FakeTaskRun()
        with (
            patch("posthog.storage.object_storage.read", side_effect=next_log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 10),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.MAX_POLL_SECONDS", 30),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.STALE_TURN_SALVAGE_SECONDS", 15),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake),
        ):
            with pytest.raises(RuntimeError, match="timed out"):
                await poll_for_turn(fake, skip_lines=0)

    @pytest.mark.asyncio
    async def test_completes_when_end_turn_recovered_on_reread(self):
        # The final polls missed the closing line; the salvage reread sees the real end_turn. The turn
        # completed (late), so it's returned as a normal completion, not declined as "grown" activity.
        quiet = "\n".join([_agent_message_line("final answer")])  # no end_turn yet
        completed = "\n".join([_agent_message_line("final answer"), _end_turn_line()])  # end_turn on reread
        calls = {"n": 0}

        def next_log(*_args, **_kwargs):
            calls["n"] += 1
            # polls 1-3 miss the closing line; the salvage reread (4th) sees the real end_turn.
            return completed if calls["n"] > 3 else quiet

        fake = FakeTaskRun()
        with (
            patch("posthog.storage.object_storage.read", side_effect=next_log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 10),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.MAX_POLL_SECONDS", 30),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.STALE_TURN_SALVAGE_SECONDS", 15),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake),
        ):
            last_message, _, _, _ = await poll_for_turn(fake, skip_lines=0)

        assert last_message == "final answer"

    @pytest.mark.asyncio
    async def test_salvages_despite_eventually_consistent_short_final_poll(self):
        # An earlier poll saw the full log; the final polls got a stale, shorter S3 read. The salvage
        # reread recovers the full log and salvages off its fingerprint tail — no line-count comparison
        # is involved, so an eventually-consistent short final read can't cause a false decline.
        full = "\n".join(
            [
                _user_message_line("prompt"),
                _agent_message_line("close-out summary"),
                _usage_update_line(165000),
            ]
        )
        short = "\n".join([_user_message_line("prompt"), _agent_message_line("close-out summary")])
        calls = {"n": 0}

        def next_log(*_args, **_kwargs):
            calls["n"] += 1
            # poll 1 sees the full 3-line log; polls 2-3 get a stale 2-line read; the salvage reread is full.
            return short if calls["n"] in (2, 3) else full

        fake = FakeTaskRun()
        with (
            patch("posthog.storage.object_storage.read", side_effect=next_log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 10),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.MAX_POLL_SECONDS", 30),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.STALE_TURN_SALVAGE_SECONDS", 15),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake),
        ):
            last_message, _, _, _ = await poll_for_turn(fake, skip_lines=0)

        assert last_message == "close-out summary"

    @pytest.mark.asyncio
    async def test_salvages_when_finalization_fingerprint_lands_on_reread(self):
        # The agent's final message was seen during polling, but the closing null-cost usage_update
        # only becomes visible on the timeout reread. The completed fingerprint must be salvaged — not
        # declined as "new activity" just because the reread has one more line than the polls saw.
        seen = "\n".join([_agent_message_line("close-out summary")])  # message only, no fingerprint yet
        finalized = "\n".join([_agent_message_line("close-out summary"), _usage_update_line(165000)])
        calls = {"n": 0}

        def next_log(*_args, **_kwargs):
            calls["n"] += 1
            # polls 1-3 see only the message; the salvage reread (4th) sees the null-cost usage_update.
            return finalized if calls["n"] > 3 else seen

        fake = FakeTaskRun()
        with (
            patch("posthog.storage.object_storage.read", side_effect=next_log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 10),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.MAX_POLL_SECONDS", 30),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.STALE_TURN_SALVAGE_SECONDS", 15),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake),
        ):
            last_message, _, _, _ = await poll_for_turn(fake, skip_lines=0)

        assert last_message == "close-out summary"

    @pytest.mark.asyncio
    async def test_declines_salvage_when_reread_shows_new_chunk_after_final_poll(self):
        # A null-cost usage_update is also emitted between chunks of an active turn. If the agent emits
        # another chunk (message + null-cost usage) after the final poll, the reread's tail is still
        # fingerprint-shaped but it grew 2 lines past the high-water mark — fresh activity with no
        # silence window, so it could still be live. Salvaging would truncate it; this declines.
        polled = "\n".join([_agent_message_line("working"), _usage_update_line()])  # fingerprint tail
        active = "\n".join(
            [
                _agent_message_line("working"),
                _usage_update_line(),
                _agent_message_line("still working"),
                _usage_update_line(),
            ]
        )  # a fresh chunk landed; tail is still fingerprint-shaped (+2 lines)
        calls = {"n": 0}

        def next_log(*_args, **_kwargs):
            calls["n"] += 1
            # polls 1-3 see only "working"; the salvage reread (4th) sees the newly-emitted chunk.
            return active if calls["n"] > 3 else polled

        fake = FakeTaskRun()
        with (
            patch("posthog.storage.object_storage.read", side_effect=next_log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 10),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.MAX_POLL_SECONDS", 30),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.STALE_TURN_SALVAGE_SECONDS", 15),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake),
        ):
            with pytest.raises(RuntimeError, match="timed out"):
                await poll_for_turn(fake, skip_lines=0)

    @pytest.mark.asyncio
    async def test_declines_salvage_when_reread_shows_new_tool_activity(self):
        # A tool call is activity that does NOT change the trailing agent_message. If one lands after
        # the final poll followed by a null-cost usage_update, last_message is unchanged and the tail is
        # fingerprint-shaped — but the reread grew 2 lines past the high-water mark, so it's fresh
        # activity with no silence window and must decline (the line count, not the message, catches it).
        polled = "\n".join([_agent_message_line("working"), _usage_update_line()])  # fingerprint tail
        active = "\n".join(
            [_agent_message_line("working"), _usage_update_line(), _tool_call_line("grep"), _usage_update_line()]
        )  # last_message still "working", tail still fingerprint-shaped (+2 lines)
        calls = {"n": 0}

        def next_log(*_args, **_kwargs):
            calls["n"] += 1
            return active if calls["n"] > 3 else polled

        fake = FakeTaskRun()
        with (
            patch("posthog.storage.object_storage.read", side_effect=next_log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 10),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.MAX_POLL_SECONDS", 30),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.STALE_TURN_SALVAGE_SECONDS", 15),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake),
        ):
            with pytest.raises(RuntimeError, match="timed out"):
                await poll_for_turn(fake, skip_lines=0)

    @pytest.mark.asyncio
    async def test_salvages_chunked_message_streamed_across_polls(self):
        # The final response streams as agent_message_chunks over several polls (each poll's slice holds
        # only the latest chunk), then end_turn is dropped. All chunks landed during polling, so the
        # reread adds nothing past the high-water mark (+0) and the full reassembled message is salvaged.
        c1 = _agent_message_chunk_line("Part-one.")
        full = "\n".join(
            [
                c1,
                _agent_message_chunk_line("Part-two."),
                _agent_message_chunk_line("Part-three."),
                _usage_update_line(165000),
            ]
        )
        calls = {"n": 0}

        def next_log(*_args, **_kwargs):
            calls["n"] += 1
            # poll 1 sees the first chunk; from poll 2 on the whole chunked message + usage is present.
            return c1 if calls["n"] == 1 else full

        fake = FakeTaskRun()
        with (
            patch("posthog.storage.object_storage.read", side_effect=next_log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 10),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.MAX_POLL_SECONDS", 60),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.STALE_TURN_SALVAGE_SECONDS", 15),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake),
        ):
            last_message, _, _, _ = await poll_for_turn(fake, skip_lines=0)

        assert last_message == "Part-one.Part-two.Part-three."

    @pytest.mark.asyncio
    async def test_salvage_propagates_exhausted_storage_error(self):
        # If every salvage reread attempt fails, the storage error propagates (like the poll loop and
        # terminal drain) instead of masquerading as a generic poll timeout.
        quiet = "\n".join([_agent_message_line("close-out summary"), _usage_update_line(165000)])
        calls = {"n": 0}

        def next_log(*_args, **_kwargs):
            calls["n"] += 1
            if calls["n"] >= 4:  # polls 1-3 succeed; every salvage reread blips
                raise ObjectStorageError("s3 down")
            return quiet

        fake = FakeTaskRun()
        with (
            patch("posthog.storage.object_storage.read", side_effect=next_log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 10),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.MAX_POLL_SECONDS", 30),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.STALE_TURN_SALVAGE_SECONDS", 15),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake),
        ):
            with pytest.raises(ObjectStorageError):
                await poll_for_turn(fake, skip_lines=0)

    @pytest.mark.asyncio
    async def test_salvage_retries_transient_storage_error(self):
        # A transient S3 error on the salvage read is retried (like the poll loop and terminal drain),
        # so a single blip doesn't fail a turn that is otherwise recoverable.
        quiet = "\n".join([_agent_message_line("close-out summary"), _usage_update_line(165000)])
        calls = {"n": 0}

        def next_log(*_args, **_kwargs):
            calls["n"] += 1
            if calls["n"] == 4:  # the first salvage read blips; the retry (5th) succeeds
                raise ObjectStorageError("transient")
            return quiet

        fake = FakeTaskRun()
        with (
            patch("posthog.storage.object_storage.read", side_effect=next_log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 10),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.MAX_POLL_SECONDS", 30),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.STALE_TURN_SALVAGE_SECONDS", 15),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake),
        ):
            last_message, _, _, _ = await poll_for_turn(fake, skip_lines=0)

        assert last_message == "close-out summary"

    @pytest.mark.asyncio
    async def test_terminal_status_at_timeout_drains_instead_of_salvaging(self):
        # Fingerprint present but no agent_message, and the run is terminal by the deadline — the
        # timeout path drains (raises the real failure) instead of reporting a bare timeout.
        log = "\n".join([_user_message_line("prompt"), _usage_update_line()])  # fingerprint, no agent_message
        running = FakeTaskRun(status="running")
        failed = FakeTaskRun(status="failed", error_message="sandbox killed")
        statuses = iter([running] * 3 + [failed])

        def next_status(*_args, **_kwargs):
            return next(statuses, failed)

        with (
            patch("posthog.storage.object_storage.read", return_value=log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 10),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.MAX_POLL_SECONDS", 30),
            patch("products.tasks.backend.models.TaskRun.objects.get", side_effect=next_status),
        ):
            with pytest.raises(RuntimeError, match="terminal status"):
                await poll_for_turn(running, skip_lines=0)

    @pytest.mark.asyncio
    async def test_active_turn_completes_via_end_turn_not_salvage(self):
        # A still-active turn completes via its real end_turn before the budget runs out.
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
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 10),
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
        # Silence floor cleared, but the tail isn't a null-cost usage_update — so the fingerprint
        # gate (not the floor) blocks salvage and the run times out.
        log = "\n".join([_agent_message_line("intermediate"), *tail_lines])
        fake = FakeTaskRun()
        with (
            patch("posthog.storage.object_storage.read", return_value=log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 10),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.MAX_POLL_SECONDS", 30),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.STALE_TURN_SALVAGE_SECONDS", 15),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake),
        ):
            with pytest.raises(RuntimeError, match="timed out"):
                await poll_for_turn(fake, skip_lines=0)

    @parameterized.expand(
        [
            ("one_console_line", [_console_line("agentsh network events")]),
            (
                "console_then_credential_refresh",
                [_console_line("agentsh network events"), _console_line("Refreshed sandbox credentials: github")],
            ),
            ("sandbox_output", [_console_line("npm install ...", method="_posthog/sandbox_output")]),
        ]
    )
    async def test_salvages_when_late_fingerprint_and_trailing_relay_lines_both_land_on_reread(self, _name, trailing):
        # The growth check must discount transient relay side-channels, not just the tail classifier.
        # Polls saw only the agent_message; the late null-cost usage_update AND trailing relay line(s)
        # both appear on the salvage reread. Raw growth is +2 or more, but only +1 line is turn-relevant
        # (the finalization fingerprint), so salvage must proceed — counting the relay lines as growth
        # would re-open the exact dropped-finalization-behind-trailing-logs case this path recovers.
        seen = _agent_message_line("close-out summary")  # message only, no fingerprint yet
        finalized = "\n".join([_agent_message_line("close-out summary"), _usage_update_line(165000), *trailing])
        calls = {"n": 0}

        def next_log(*_args, **_kwargs):
            calls["n"] += 1
            # polls 1-3 see only the message; the salvage reread (4th) sees the fingerprint + relay lines.
            return finalized if calls["n"] > 3 else seen

        fake = FakeTaskRun()
        with (
            patch("posthog.storage.object_storage.read", side_effect=next_log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 10),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.MAX_POLL_SECONDS", 30),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.STALE_TURN_SALVAGE_SECONDS", 15),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake),
        ):
            last_message, _, _, _ = await poll_for_turn(fake, skip_lines=0)

        assert last_message == "close-out summary"

    @pytest.mark.asyncio
    async def test_failed_progress_after_fingerprint_declines_salvage(self):
        # The workflow's failure/cancel handlers emit a `_posthog/progress` status="failed" BEFORE the
        # TaskRun reaches a terminal status. A salvage reread landing in that window must treat the
        # failed progress marker as decisive — not skip it as informational setup progress and report a
        # bogus success off the preceding finalization fingerprint. Status is still non-terminal here,
        # so without this the run would salvage instead of letting the terminal drain win.
        log = "\n".join(
            [_agent_message_line("close-out summary"), _usage_update_line(165000), _progress_line(status="failed")]
        )
        fake = FakeTaskRun()
        with (
            patch("posthog.storage.object_storage.read", return_value=log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 10),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.MAX_POLL_SECONDS", 30),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.STALE_TURN_SALVAGE_SECONDS", 15),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake),
        ):
            with pytest.raises(RuntimeError, match="timed out"):
                await poll_for_turn(fake, skip_lines=0)

    @parameterized.expand([("in_progress",), ("completed",)])
    async def test_informational_progress_after_fingerprint_still_salvages(self, status):
        # Only failed/cancelled progress is decisive — an informational progress line (a normal setup
        # step) trailing the fingerprint is still skipped as transient, so the dropped finalization is
        # salvaged as before.
        log = "\n".join(
            [_agent_message_line("close-out summary"), _usage_update_line(165000), _progress_line(status=status)]
        )
        fake = FakeTaskRun()
        with (
            patch("posthog.storage.object_storage.read", return_value=log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 10),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.MAX_POLL_SECONDS", 30),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.STALE_TURN_SALVAGE_SECONDS", 15),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake),
        ):
            last_message, _, _, _ = await poll_for_turn(fake, skip_lines=0)

        assert last_message == "close-out summary"


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
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 0),
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
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 0),
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
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 0),
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
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 0),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake_task_run),
            patch(
                "products.tasks.backend.logic.services.custom_prompt_internals._persist_task_run_error_message",
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
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 0),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake_task_run),
            patch(
                "products.tasks.backend.logic.services.custom_prompt_internals._persist_task_run_error_message",
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
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 0),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake_task_run),
            patch(
                "products.tasks.backend.logic.services.custom_prompt_internals._persist_task_run_error_message",
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
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 0),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake_task_run),
            patch(
                "products.tasks.backend.logic.services.custom_prompt_internals._persist_task_run_error_message",
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
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 0),
            patch("products.tasks.backend.models.TaskRun.objects.get", return_value=fake_task_run),
            patch(
                "products.tasks.backend.logic.services.custom_prompt_internals._persist_task_run_error_message",
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
            "products.tasks.backend.logic.services.custom_prompt_multi_turn_runner.poll_for_turn",
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
            "products.tasks.backend.logic.services.custom_prompt_multi_turn_runner.poll_for_turn",
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
            "products.tasks.backend.logic.services.custom_prompt_multi_turn_runner.poll_for_turn",
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
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 0),
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
            "products.tasks.backend.logic.services.custom_prompt_multi_turn_runner.poll_for_turn",
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
                "products.tasks.backend.logic.services.custom_prompt_multi_turn_runner.async_connect",
                new=AsyncMock(return_value=MagicMock(get_workflow_handle=MagicMock(return_value=AsyncMock()))),
            ),
            patch(
                "products.tasks.backend.logic.services.custom_prompt_multi_turn_runner.poll_for_turn",
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
                "products.tasks.backend.logic.services.custom_prompt_multi_turn_runner.create_task_and_trigger",
                new=AsyncMock(return_value=(fake_task, fake_run)),
            ),
            patch(
                "products.tasks.backend.logic.services.custom_prompt_multi_turn_runner.async_connect",
                new=AsyncMock(return_value=mock_client),
            ),
            patch(
                "products.tasks.backend.logic.services.custom_prompt_multi_turn_runner.poll_for_turn",
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
            "products.tasks.backend.logic.services.custom_prompt_internals.Task.create_and_run",
            return_value=mock_task,
        ) as mock_create:
            await create_task_and_trigger("prompt", context)

        kwargs = mock_create.call_args.kwargs
        assert kwargs["sandbox_environment_id"] == expected_env
        assert kwargs["posthog_mcp_scopes"] == expected_scopes

    @pytest.mark.asyncio
    @pytest.mark.parametrize("ai_stage, expected", [("research", "research"), (None, None)])
    async def test_forwards_ai_stage(self, ai_stage, expected):
        team, user = await sync_to_async(self._setup_team_and_user)()
        context = CustomPromptSandboxContext(team_id=team.id, user_id=user.id, repository="posthog/posthog")

        mock_task = MagicMock()
        mock_task.latest_run = MagicMock()
        with patch(
            "products.tasks.backend.logic.services.custom_prompt_internals.Task.create_and_run",
            return_value=mock_task,
        ) as mock_create:
            await create_task_and_trigger("prompt", context, ai_stage=ai_stage)

        assert mock_create.call_args.kwargs["ai_stage"] == expected


class TestMultiTurnSessionStartFallback:
    """start() salvages an end-turn the agent produced but that didn't validate against the
    model (empty, prose, or malformed JSON) via fallback_from_text, instead of failing the
    whole run. Without a fallback — or on a cancellation — it still fails and ends the run."""

    def _fake_session(self) -> MultiTurnSession:
        session = MultiTurnSession(
            task=object(),  # type: ignore[arg-type]
            task_run=FakeTaskRun(),  # type: ignore[arg-type]
            _workflow_handle=AsyncMock(),
        )
        session.end = AsyncMock()  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]
        return session

    @pytest.mark.asyncio
    async def test_salvages_unparseable_text_with_fallback(self):
        # _Resp requires a JSON object with `value`; prose can't validate, so the fallback
        # builds the model from the raw close-out text instead of failing the run.
        session = self._fake_session()
        prose = "No anomalies this run. Scanned 12 commits, remembered the scan marker."

        with patch.object(MultiTurnSession, "start_raw", new=AsyncMock(return_value=(session, prose))):
            returned_session, parsed = await MultiTurnSession.start(
                prompt="x",
                context=MagicMock(),
                model=_Resp,
                fallback_from_text=lambda text: _Resp(value=text),
            )

        assert returned_session is session
        assert parsed == _Resp(value=prose)
        # A salvaged run is NOT ended as failed — the caller persists the result and ends normally.
        session.end.assert_not_awaited()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_fails_and_ends_run_without_fallback(self):
        session = self._fake_session()

        with patch.object(MultiTurnSession, "start_raw", new=AsyncMock(return_value=(session, "prose only"))):
            with pytest.raises(ValueError):
                await MultiTurnSession.start(prompt="x", context=MagicMock(), model=_Resp)

        session.end.assert_awaited_once()  # type: ignore[attr-defined]
        assert session.end.await_args.kwargs.get("status") == "failed"  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_valid_json_parses_without_invoking_fallback(self):
        session = self._fake_session()
        fallback = MagicMock()

        with patch.object(
            MultiTurnSession, "start_raw", new=AsyncMock(return_value=(session, json.dumps({"value": "ok"})))
        ):
            _, parsed = await MultiTurnSession.start(
                prompt="x", context=MagicMock(), model=_Resp, fallback_from_text=fallback
            )

        assert parsed == _Resp(value="ok")
        fallback.assert_not_called()
        session.end.assert_not_awaited()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_raising_fallback_ends_run_instead_of_escaping(self):
        # A fallback that itself raises (e.g. a stricter model that also rejects the raw text)
        # must not escape start() before teardown — the run is ended as failed, not left wedged.
        session = self._fake_session()

        def boom(_text: str) -> _Resp:
            raise ValueError("stricter model rejects raw text too")

        with patch.object(MultiTurnSession, "start_raw", new=AsyncMock(return_value=(session, "prose only"))):
            with pytest.raises(ValueError):
                await MultiTurnSession.start(prompt="x", context=MagicMock(), model=_Resp, fallback_from_text=boom)

        session.end.assert_awaited_once()  # type: ignore[attr-defined]
        assert session.end.await_args.kwargs.get("status") == "failed"  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_cancellation_never_salvages(self):
        # A Temporal cancellation must propagate and fail the run even when a fallback is set —
        # salvaging a cancelled turn would mask a genuine timeout as a degraded success.
        session = self._fake_session()
        fallback = MagicMock()

        with (
            patch.object(MultiTurnSession, "start_raw", new=AsyncMock(return_value=(session, "some text"))),
            patch.object(MultiTurnSession, "_parse_and_validate", side_effect=asyncio.CancelledError()),
        ):
            with pytest.raises(asyncio.CancelledError):
                await MultiTurnSession.start(prompt="x", context=MagicMock(), model=_Resp, fallback_from_text=fallback)

        fallback.assert_not_called()
        session.end.assert_awaited_once()  # type: ignore[attr-defined]


class TestPollForTurnConnectionDrop:
    """poll_for_turn runs for many minutes while the activity's pooled DB connection sits idle;
    pgbouncer can drop it underneath the in-loop `TaskRun.objects.get` refreshes. Those reads must
    reconnect transparently instead of aborting the whole report run with an OperationalError."""

    @pytest.mark.asyncio
    async def test_in_loop_refresh_reconnects_after_dropped_connection(self):
        # First poll has an agent_message but no end_turn -> falls through to the in-loop TaskRun
        # refresh, whose first ORM read hits a dropped pooled connection. The retry must reconnect
        # and observe the now-terminal status so the run drains cleanly instead of crashing.
        log = "\n".join([_agent_message_line("connection-drop summary"), _usage_update_line()])
        completed = FakeTaskRun(status=TaskRun.Status.COMPLETED)
        get_mock = MagicMock(side_effect=[OperationalError("server closed the connection unexpectedly"), completed])

        # settings.TEST gates the close_old_connections() call (it health-checks live
        # connections, which trips the test DB-access guard), so flip it off to exercise
        # the real reconnect path.
        with (
            patch("posthog.storage.object_storage.read", return_value=log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 0),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.settings.TEST", False),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.close_old_connections") as close_conns,
            patch("products.tasks.backend.models.TaskRun.objects.get", new=get_mock),
        ):
            last_message, _, _, _ = await poll_for_turn(FakeTaskRun(), skip_lines=0)

        assert last_message == "connection-drop summary"
        # Read was retried after the drop, and the staleness guard ran before each attempt.
        assert get_mock.call_count == 2
        assert close_conns.call_count == 2

    @pytest.mark.asyncio
    async def test_persistent_connection_failure_propagates(self):
        # A genuinely dead pool (both attempts fail) must still surface — the guard retries once,
        # it is not an infinite reconnect loop that masks a real outage.
        log = "\n".join([_agent_message_line("partial"), _usage_update_line()])
        get_mock = MagicMock(side_effect=OperationalError("server closed the connection unexpectedly"))

        with (
            patch("posthog.storage.object_storage.read", return_value=log),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.POLL_INTERVAL_SECONDS", 0),
            patch("products.tasks.backend.logic.services.custom_prompt_internals.close_old_connections"),
            patch("products.tasks.backend.models.TaskRun.objects.get", new=get_mock),
        ):
            with pytest.raises(OperationalError):
                await poll_for_turn(FakeTaskRun(), skip_lines=0)

        assert get_mock.call_count == 2
