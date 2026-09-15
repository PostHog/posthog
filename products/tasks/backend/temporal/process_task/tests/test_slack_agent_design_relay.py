import os
import uuid
import asyncio
from datetime import timedelta

from temporalio import activity
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.tasks.backend.temporal.process_task.activities.slack_agent_design import (
    STREAM_MODE_FINAL_ONLY,
    STREAM_MODE_TIMELINE,
    AppendSlackAgentDesignStepsInput,
    RenderSlackAgentDesignMessageInput,
    RenderSlackAgentDesignMessageOutput,
    StartSlackAgentDesignStreamInput,
    StopSlackAgentDesignStreamInput,
)
from products.tasks.backend.temporal.process_task.slack_agent_design_relay import (
    SlackAgentDesignRelayInput,
    SlackAgentDesignRelayWorkflow,
)

SLACK_CTX = {"integration_id": 1, "channel": "C1", "thread_ts": "171.100", "mentioning_slack_user_id": "U1"}
TASK_QUEUE = "test-slack-agent-design-relay"


class StreamRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.artifact_blocks_once: list[dict] = []

    def record(self, kind: str, input: object) -> None:
        self.calls.append((kind, input))

    def renders(self) -> list[RenderSlackAgentDesignMessageInput]:
        return [input for _, input in self.calls if isinstance(input, RenderSlackAgentDesignMessageInput)]


def _activities(rec: StreamRecorder) -> list:
    @activity.defn(name="render_slack_agent_design_message")
    async def render(input: RenderSlackAgentDesignMessageInput) -> RenderSlackAgentDesignMessageOutput:
        rec.record("render", input)
        blocks, rec.artifact_blocks_once = rec.artifact_blocks_once, []
        return RenderSlackAgentDesignMessageOutput(ts="999.100", artifact_blocks=blocks)

    @activity.defn(name="start_slack_agent_design_stream")
    async def start(input: StartSlackAgentDesignStreamInput) -> str | None:
        rec.record("start", input)
        return "999.100"

    @activity.defn(name="append_slack_agent_design_steps")
    async def append(input: AppendSlackAgentDesignStepsInput) -> None:
        rec.record("append", input)

    @activity.defn(name="stop_slack_agent_design_stream")
    async def stop(input: StopSlackAgentDesignStreamInput) -> None:
        rec.record("stop", input)

    return [render, start, append, stop]


class _RelayEnv:
    """One time-skipping env + worker around the relay, with recorded activities."""

    def __init__(self) -> None:
        self.rec = StreamRecorder()

    async def __aenter__(self) -> "_RelayEnv":
        self._env_cm = await WorkflowEnvironment.start_time_skipping(
            test_server_existing_path=os.environ.get("TEMPORAL_TEST_SERVER_PATH")
        )
        self.env = await self._env_cm.__aenter__()
        self._worker_cm = Worker(
            self.env.client,
            task_queue=TASK_QUEUE,
            workflows=[SlackAgentDesignRelayWorkflow],
            activities=_activities(self.rec),
            workflow_runner=UnsandboxedWorkflowRunner(),
        )
        await self._worker_cm.__aenter__()
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self._worker_cm.__aexit__(*exc_info)
        await self._env_cm.__aexit__(*exc_info)

    async def start_relay(self, stream_mode: str | None):
        return await self.env.client.start_workflow(
            SlackAgentDesignRelayWorkflow.run,
            SlackAgentDesignRelayInput(slack_thread_context=SLACK_CTX, run_id="run-1", stream_mode=stream_mode),
            id=str(uuid.uuid4()),
            task_queue=TASK_QUEUE,
            retry_policy=RetryPolicy(maximum_attempts=1),
            execution_timeout=timedelta(minutes=10),
        )


def _final_segments(rec: StreamRecorder) -> list:
    closing = [r for r in rec.renders() if r.closing]
    assert closing, "no closing render happened"
    return closing[-1].segments


async def test_timeline_interleaves_prose_and_card_segments_in_arrival_order():
    async with _RelayEnv() as relay:
        handle = await relay.start_relay(STREAM_MODE_TIMELINE)
        await handle.signal(SlackAgentDesignRelayWorkflow.agent_text_delta, "Let me check the data.")
        await handle.signal(SlackAgentDesignRelayWorkflow.agent_status_update, {"title": "Read", "details": "insights"})
        await handle.signal(SlackAgentDesignRelayWorkflow.agent_text_delta, "Found it.")
        await handle.signal(SlackAgentDesignRelayWorkflow.complete_turn, "trace-1")
        await handle.result()

    segments = _final_segments(relay.rec)
    assert [s.kind for s in segments] == ["text", "cards", "text"]
    assert segments[0].text == "Let me check the data."
    assert [c.title for c in segments[1].calls] == ["Read"]
    assert segments[1].complete
    assert segments[2].text == "Found it."

    closing = relay.rec.renders()[-1]
    assert closing.closing
    assert closing.trace_id == "trace-1"
    assert closing.run_id == "run-1"
    # Renders after the first update the posted message rather than posting again.
    assert all(r.ts == "999.100" for r in relay.rec.renders()[1:])
    assert relay.rec.renders()[0].ts is None


async def test_burst_stays_one_card_segment_and_outcomes_land_on_their_calls():
    # Consecutive calls share a card; a call's result must land on that call, and
    # a failure must be legible on it.
    async with _RelayEnv() as relay:
        handle = await relay.start_relay(STREAM_MODE_TIMELINE)
        await handle.signal(
            SlackAgentDesignRelayWorkflow.agent_status_update,
            {"title": "posthog/exec", "details": "insight list", "tool_call_id": "tc-1"},
        )
        await handle.signal(
            SlackAgentDesignRelayWorkflow.agent_status_update,
            {"title": "posthog/exec", "details": "query run", "tool_call_id": "tc-2"},
        )
        await handle.signal(
            SlackAgentDesignRelayWorkflow.agent_status_update,
            {"kind": "tool_result", "tool_call_id": "tc-1", "output": "12 rows", "failed": False},
        )
        await handle.signal(
            SlackAgentDesignRelayWorkflow.agent_status_update,
            {"kind": "tool_result", "tool_call_id": "tc-2", "output": "exit 1", "failed": True},
        )
        await handle.signal(SlackAgentDesignRelayWorkflow.complete_turn, None)
        await handle.result()

    segments = _final_segments(relay.rec)
    assert [s.kind for s in segments] == ["cards"]
    first, second = segments[0].calls
    assert first.output == "12 rows" and not first.failed
    assert second.output == "exit 1" and second.failed


async def test_timeline_narrative_splits_bursts_into_separate_cards():
    async with _RelayEnv() as relay:
        handle = await relay.start_relay(STREAM_MODE_TIMELINE)
        await handle.signal(SlackAgentDesignRelayWorkflow.agent_status_update, {"title": "Read"})
        await handle.signal(SlackAgentDesignRelayWorkflow.agent_text_delta, "Now searching.")
        await handle.signal(SlackAgentDesignRelayWorkflow.agent_status_update, {"title": "Grep"})
        await handle.signal(SlackAgentDesignRelayWorkflow.complete_turn, None)
        await handle.result()

    segments = _final_segments(relay.rec)
    assert [s.kind for s in segments] == ["cards", "text", "cards"]
    assert [c.title for c in segments[0].calls] == ["Read"]
    assert segments[0].complete
    assert [c.title for c in segments[2].calls] == ["Grep"]


async def test_artifact_blocks_returned_by_a_render_stay_in_the_message():
    # Blocks popped from the artifact queue must persist across later rewrites,
    # anchored where they first rendered.
    async with _RelayEnv() as relay:
        relay.rec.artifact_blocks_once = [{"type": "image", "image_url": "https://example.com/c.png"}]
        handle = await relay.start_relay(STREAM_MODE_TIMELINE)
        await handle.signal(SlackAgentDesignRelayWorkflow.agent_text_delta, "Chart coming.")
        await asyncio.sleep(1)
        await handle.signal(SlackAgentDesignRelayWorkflow.agent_text_delta, " And the wrap-up.")
        await handle.signal(SlackAgentDesignRelayWorkflow.complete_turn, None)
        await handle.result()

    segments = _final_segments(relay.rec)
    kinds = [s.kind for s in segments]
    assert "blocks" in kinds
    blocks_segment = next(s for s in segments if s.kind == "blocks")
    assert blocks_segment.blocks == [{"type": "image", "image_url": "https://example.com/c.png"}]


async def test_final_only_renders_one_batch_with_only_the_post_tool_answer():
    async with _RelayEnv() as relay:
        handle = await relay.start_relay(STREAM_MODE_FINAL_ONLY)
        await handle.signal(SlackAgentDesignRelayWorkflow.agent_text_delta, "Let me look into this…")
        await handle.signal(SlackAgentDesignRelayWorkflow.agent_status_update, {"title": "Read"})
        await handle.signal(SlackAgentDesignRelayWorkflow.agent_text_delta, "The answer is 42.")
        await handle.signal(SlackAgentDesignRelayWorkflow.complete_turn, "trace-2")
        await handle.result()

    renders = relay.rec.renders()
    assert [kind for kind, _ in relay.rec.calls] == ["render"]
    assert renders[0].closing
    assert renders[0].trace_id == "trace-2"
    assert [s.kind for s in renders[0].segments] == ["text"]
    assert renders[0].segments[0].text == "The answer is 42."


async def test_final_only_with_no_answer_posts_nothing():
    async with _RelayEnv() as relay:
        handle = await relay.start_relay(STREAM_MODE_FINAL_ONLY)
        await handle.signal(SlackAgentDesignRelayWorkflow.agent_status_update, {"title": "Read"})
        await handle.signal(SlackAgentDesignRelayWorkflow.complete_turn, None)
        await handle.result()

    assert relay.rec.calls == []


async def test_missing_stream_mode_keeps_the_legacy_plan_surface():
    async with _RelayEnv() as relay:
        handle = await relay.start_relay(None)
        await handle.signal(SlackAgentDesignRelayWorkflow.agent_text_delta, "Hello there.")
        await handle.signal(SlackAgentDesignRelayWorkflow.complete_turn, None)
        await handle.result()

    kinds = [kind for kind, _ in relay.rec.calls]
    assert kinds[0] == "start"
    assert kinds[-1] == "stop"
    start_input = relay.rec.calls[0][1]
    assert isinstance(start_input, StartSlackAgentDesignStreamInput)
    # The legacy surface never sends ordered chunks or a display mode.
    assert not start_input.ordered_chunks
    assert start_input.task_display_mode is None
    assert start_input.run_id is None
