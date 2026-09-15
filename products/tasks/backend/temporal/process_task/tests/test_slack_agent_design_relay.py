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
    StartSlackAgentDesignStreamInput,
    StopSlackAgentDesignStreamInput,
    StreamChunk,
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
        self.first_call = asyncio.Event()

    def record(self, kind: str, input: object) -> None:
        self.calls.append((kind, input))
        self.first_call.set()

    def ordered_chunks(self) -> list[StreamChunk]:
        chunks: list[StreamChunk] = []
        for kind, input in self.calls:
            if kind == "start":
                assert isinstance(input, StartSlackAgentDesignStreamInput)
                chunks.extend(input.ordered_chunks)
            elif kind == "append":
                assert isinstance(input, AppendSlackAgentDesignStepsInput)
                chunks.extend(input.ordered_chunks)
        return chunks


def _activities(rec: StreamRecorder) -> list:
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

    return [start, append, stop]


class _RelayEnv:
    """One time-skipping env + worker around the relay, with recorded stream activities."""

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


async def test_timeline_interleaves_prose_and_task_cards_in_arrival_order():
    async with _RelayEnv() as relay:
        handle = await relay.start_relay(STREAM_MODE_TIMELINE)
        await handle.signal(SlackAgentDesignRelayWorkflow.agent_text_delta, "Let me check the data.")
        await handle.signal(SlackAgentDesignRelayWorkflow.agent_status_update, {"title": "Read", "details": "insights"})
        await handle.signal(SlackAgentDesignRelayWorkflow.agent_text_delta, "Found it.")
        await handle.signal(SlackAgentDesignRelayWorkflow.complete_turn, "trace-1")
        await handle.result()

    chunks = relay.rec.ordered_chunks()
    kinds = ["task" if c.task_update else "md" for c in chunks]
    assert kinds == ["md", "task", "md"]
    assert chunks[0].markdown_text == "Let me check the data."
    assert chunks[1].task_update is not None
    assert chunks[1].task_update.title == "Read"
    assert chunks[1].task_update.status == "in_progress"
    assert chunks[2].markdown_text == "Found it."

    start_input = relay.rec.calls[0][1]
    assert isinstance(start_input, StartSlackAgentDesignStreamInput)
    assert start_input.task_display_mode == STREAM_MODE_TIMELINE
    assert start_input.run_id == "run-1"

    stop_kind, stop_input = relay.rec.calls[-1]
    assert stop_kind == "stop"
    assert isinstance(stop_input, StopSlackAgentDesignStreamInput)
    assert stop_input.complete_task_id == chunks[1].task_update.id
    assert stop_input.trace_id == "trace-1"


async def test_each_tool_call_gets_its_own_card_and_its_outcome_lands_on_it():
    # One card per call, and a finished call's result must flip that call's card
    # (filling its output), not the card of whichever call ran last.
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
        await handle.signal(SlackAgentDesignRelayWorkflow.complete_turn, None)
        await handle.result()

    tasks = [c.task_update for c in relay.rec.ordered_chunks() if c.task_update]
    ids = {t.id for t in tasks}
    assert len(ids) == 2
    card_one_id = next(t.id for t in tasks if t.details == "insight list")
    card_one_final = [t for t in tasks if t.id == card_one_id][-1]
    assert card_one_final.status == "complete"
    assert card_one_final.output == "12 rows"

    card_two_id = next(t.id for t in tasks if t.details == "query run")
    stop_input = relay.rec.calls[-1][1]
    assert isinstance(stop_input, StopSlackAgentDesignStreamInput)
    assert stop_input.complete_task_id == card_two_id


async def test_failed_tool_call_marks_its_card_as_error_and_stop_leaves_it_alone():
    # An error status must survive the close: the stop path completing the card
    # again would repaint the failure as success.
    async with _RelayEnv() as relay:
        handle = await relay.start_relay(STREAM_MODE_TIMELINE)
        await handle.signal(
            SlackAgentDesignRelayWorkflow.agent_status_update,
            {"title": "Bash", "details": "make test", "tool_call_id": "tc-1"},
        )
        await handle.signal(
            SlackAgentDesignRelayWorkflow.agent_status_update,
            {"kind": "tool_result", "tool_call_id": "tc-1", "output": "exit 1", "failed": True},
        )
        await handle.signal(SlackAgentDesignRelayWorkflow.complete_turn, None)
        await handle.result()

    tasks = [c.task_update for c in relay.rec.ordered_chunks() if c.task_update]
    assert tasks[-1].status == "error"
    assert tasks[-1].output == "exit 1"
    stop_input = relay.rec.calls[-1][1]
    assert isinstance(stop_input, StopSlackAgentDesignStreamInput)
    assert stop_input.complete_task_id is None


async def test_timeline_narrative_breaks_the_card_burst():
    # Prose between tool calls completes the open card, so the next call opens a
    # new one and the thread keeps its text → card → text → card rhythm.
    async with _RelayEnv() as relay:
        handle = await relay.start_relay(STREAM_MODE_TIMELINE)
        await handle.signal(SlackAgentDesignRelayWorkflow.agent_status_update, {"title": "Read"})
        await handle.signal(SlackAgentDesignRelayWorkflow.agent_text_delta, "Now searching.")
        await handle.signal(SlackAgentDesignRelayWorkflow.agent_status_update, {"title": "Grep"})
        await handle.signal(SlackAgentDesignRelayWorkflow.complete_turn, None)
        await handle.result()

    tasks = [c.task_update for c in relay.rec.ordered_chunks() if c.task_update]
    assert [(t.title, t.status) for t in tasks] == [
        ("Read", "in_progress"),
        ("Read", "complete"),
        ("Grep", "in_progress"),
    ]
    assert tasks[0].id == tasks[1].id
    assert tasks[2].id != tasks[0].id


async def test_final_only_posts_one_batch_with_only_the_post_tool_answer():
    async with _RelayEnv() as relay:
        handle = await relay.start_relay(STREAM_MODE_FINAL_ONLY)
        await handle.signal(SlackAgentDesignRelayWorkflow.agent_text_delta, "Let me look into this…")
        await handle.signal(SlackAgentDesignRelayWorkflow.agent_status_update, {"title": "Read"})
        await handle.signal(SlackAgentDesignRelayWorkflow.agent_text_delta, "The answer is 42.")
        await handle.signal(SlackAgentDesignRelayWorkflow.complete_turn, "trace-2")
        await handle.result()

    assert [kind for kind, _ in relay.rec.calls] == ["start", "stop"]
    start_input = relay.rec.calls[0][1]
    assert isinstance(start_input, StartSlackAgentDesignStreamInput)
    assert start_input.first_markdown_text == "The answer is 42."
    assert not start_input.ordered_chunks
    stop_input = relay.rec.calls[1][1]
    assert isinstance(stop_input, StopSlackAgentDesignStreamInput)
    assert stop_input.trace_id == "trace-2"
    assert stop_input.complete_task_id is None


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
