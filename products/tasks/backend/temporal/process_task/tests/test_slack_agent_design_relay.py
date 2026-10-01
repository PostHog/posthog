import uuid
import asyncio
from typing import Any

import pytest

from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.tasks.backend.temporal.process_task.activities.slack_agent_design import (
    AppendSlackAgentDesignStepsInput,
    SlackAgentDesignStream,
    StartSlackAgentDesignStreamInput,
    StopSlackAgentDesignStreamInput,
    TaskUpdateChunk,
)
from products.tasks.backend.temporal.process_task.slack_agent_design_relay import (
    SlackAgentDesignRelayInput,
    SlackAgentDesignRelayWorkflow,
)

pytestmark = [pytest.mark.asyncio]

SLACK_CTX = {"integration_id": 1, "channel": "C1", "thread_ts": "1.0", "mentioning_slack_user_id": "U1"}


class _SlackCalls:
    def __init__(self) -> None:
        self.starts: list[StartSlackAgentDesignStreamInput] = []
        self.appends: list[AppendSlackAgentDesignStepsInput] = []
        self.stops: list[StopSlackAgentDesignStreamInput] = []

    def activities(self) -> list[Any]:
        @activity.defn(name="start_slack_agent_design_stream")
        async def start(input: StartSlackAgentDesignStreamInput) -> SlackAgentDesignStream:
            self.starts.append(input)
            return SlackAgentDesignStream(ts="2.0", has_plan=bool(input.task_updates))

        @activity.defn(name="append_slack_agent_design_steps")
        async def append(input: AppendSlackAgentDesignStepsInput) -> None:
            self.appends.append(input)

        @activity.defn(name="stop_slack_agent_design_stream")
        async def stop(input: StopSlackAgentDesignStreamInput) -> None:
            self.stops.append(input)

        return [start, append, stop]

    def final_lines(self) -> dict[str, tuple[str, str | None, str]]:
        lines: dict[str, tuple[str, str | None, str]] = {}
        for chunks in [s.task_updates for s in self.starts] + [a.task_updates for a in self.appends]:
            for chunk in chunks:
                lines[chunk.id] = (chunk.title, chunk.details, chunk.status)
        for stop in self.stops:
            if stop.complete_task_id and stop.complete_task_title:
                lines[stop.complete_task_id] = (stop.complete_task_title, stop.complete_task_details, "complete")
        return lines

    def sent_chunks(self) -> list[TaskUpdateChunk]:
        return [chunk for start in self.starts for chunk in start.task_updates] + [
            chunk for append in self.appends for chunk in append.task_updates
        ]

    def answer(self) -> str | None:
        return next((s.final_markdown for s in self.stops if s.final_markdown), None) or next(
            (s.first_markdown_text for s in self.starts if s.first_markdown_text), None
        )


async def _run_relay(
    signals: list[tuple[str, Any]], *, setup_title: str | None = None, cancel: bool = False
) -> _SlackCalls:
    calls = _SlackCalls()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        task_queue = f"test-{uuid.uuid4()}"
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[SlackAgentDesignRelayWorkflow],
            activities=calls.activities(),
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await env.client.start_workflow(
                SlackAgentDesignRelayWorkflow.run,
                SlackAgentDesignRelayInput(slack_thread_context=SLACK_CTX, run_id="run-1", setup_title=setup_title),
                id=f"relay-{uuid.uuid4()}",
                task_queue=task_queue,
            )
            for name, arg in signals:
                await handle.signal(name, arg)
            if cancel:
                await asyncio.sleep(0.5)
                await handle.cancel()
                with pytest.raises(WorkflowFailureError):
                    await handle.result()
            else:
                await handle.signal("complete_turn", "trace-1")
                await handle.result()
    return calls


class TestSlackAgentDesignRelay:
    @pytest.mark.timeout(60, func_only=True)
    async def test_tool_calls_collapse_into_one_line_per_phase(self) -> None:
        calls = await _run_relay(
            [
                ("agent_text_delta", "Let me look at the data."),
                ("agent_status_update", {"phase": "posthog_data"}),
                ("agent_status_update", {"phase": "posthog_data"}),
                ("agent_status_update", {"phase": "reading_code", "activity": "Search for callers"}),
                ("agent_text_delta", "Now I need to look into this."),
                ("agent_status_update", {"phase": "posthog_data"}),
                ("agent_status_update", {"phase": "making_changes"}),
                ("agent_text_delta", "Signups grew."),
            ]
        )

        assert sorted(calls.final_lines().values()) == [
            ("Looking at PostHog data (3 queries)", None, "complete"),
            ("Making changes (1 edit)", None, "complete"),
            ("Reading the code (1 lookup)", None, "complete"),
        ]
        assert calls.answer() == "Signups grew."
        assert [(s.plan_title or "").startswith("Done in ") for s in calls.stops] == [True]
        sent = calls.sent_chunks()
        # The open line shows what runs now, and the finished line goes back to its count.
        assert ("Reading the code: Search for callers", "in_progress") in [(c.title, c.status) for c in sent]
        # Slack appends a step's details on every update, so a counter there reads "1 query2 queries".
        assert all(chunk.details is None for chunk in sent)
        assert all(stop.complete_task_details is None for stop in calls.stops)

    @pytest.mark.parametrize(
        "tail",
        [
            [("agent_text_delta", "Answer.")],
            # A trailing hidden tool, such as a summary update, must not cost the answer.
            [("agent_text_delta", "Answer."), ("agent_status_update", {"phase": None})],
        ],
        ids=["answer_after_last_tool", "answer_before_hidden_tool"],
    )
    @pytest.mark.timeout(60, func_only=True)
    async def test_last_prose_burst_is_the_answer(self, tail: list[tuple[str, Any]]) -> None:
        calls = await _run_relay(
            [("agent_text_delta", "Checking."), ("agent_status_update", {"phase": "posthog_data"}), *tail]
        )

        assert calls.answer() == "Answer."

    @pytest.mark.parametrize(
        "signals, expected_line",
        [
            ([("agent_status_update", {"phase": "posthog_data"})], "Looking at PostHog data (1 query)"),
            ([("agent_text_delta", "Hi! What should I look at?")], "Writing the answer"),
        ],
        ids=["first_work_line", "answer_without_tools"],
    )
    @pytest.mark.timeout(60, func_only=True)
    async def test_early_relay_setup_line_does_not_outlive_setup(
        self, signals: list[tuple[str, Any]], expected_line: str
    ) -> None:
        # Slack cannot remove a line, so the setup line must turn into real work, not stay behind.
        calls = await _run_relay(signals, setup_title="Getting ready")

        assert [[(c.title, c.status) for c in s.task_updates] for s in calls.starts] == [
            [("Getting ready", "in_progress")]
        ]
        assert list(calls.final_lines().values()) == [(expected_line, None, "complete")]
        assert [(s.plan_title or "").startswith("Done in ") for s in calls.stops] == [True]

    @pytest.mark.timeout(60, func_only=True)
    async def test_stopped_run_marks_the_open_step_failed(self) -> None:
        # A run that fails during provisioning must not leave the setup step spinning, or read as done.
        calls = await _run_relay([], setup_title="Getting ready", cancel=True)

        assert list(calls.final_lines().values()) == [("Getting ready", None, "error")]
        assert [s.plan_title for s in calls.stops] == ["Stopped"]

    @pytest.mark.timeout(60, func_only=True)
    async def test_phases_past_the_line_limit_fold_into_other_work(self) -> None:
        keys = [
            "posthog_data",
            "posthog_dashboards",
            "posthog_errors",
            "posthog_replays",
            "posthog_flags",
            "posthog_logs",
            "posthog_ai",
            "posthog_surveys",
            "posthog_warehouse",
        ]
        calls = await _run_relay([("agent_status_update", {"phase": key}) for key in keys])

        titles = [title for title, _details, _status in calls.final_lines().values()]
        assert len(titles) == 7
        assert "Other work (3 steps)" in titles
