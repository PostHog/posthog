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

# A pseudo signal for ``_run_relay``: skip this many seconds, so the relay flushes what it has.
WAIT = "__wait__"

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
        lines: dict[str, tuple[str, str]] = {}
        details: dict[str, str] = {}
        for chunk in self.sent_chunks():
            lines[chunk.id] = (chunk.title, chunk.status)
            if chunk.details:
                details[chunk.id] = details.get(chunk.id, "") + chunk.details
        for stop in self.stops:
            if stop.complete_task_id and stop.complete_task_title:
                lines[stop.complete_task_id] = (stop.complete_task_title, "complete")
        return {line_id: (title, details.get(line_id), status) for line_id, (title, status) in lines.items()}

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
                if name == WAIT:
                    await env.sleep(arg)
                    continue
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
                ("agent_status_update", {"phase": "posthog:Execute SQL query"}),
                ("agent_status_update", {"phase": "posthog:Execute SQL query"}),
                ("agent_status_update", {"phase": "reading_code", "activity": "Search for callers"}),
                ("agent_text_delta", "Now I need to look into this."),
                ("agent_status_update", {"phase": "posthog:Execute SQL query"}),
                ("agent_status_update", {"phase": "making_changes"}),
                ("agent_text_delta", "Signups grew."),
            ]
        )

        # Each call's description stays under its line. With no description, the agent's own last
        # sentence says what the call is for. Slack appends details, so a resent one shows twice.
        assert sorted(calls.final_lines().values()) == [
            ("Execute SQL query (3 calls)", "Look at the data\nLook into this", "complete"),
            ("Making changes", None, "complete"),
            ("Reading the code", "Search for callers", "complete"),
        ]
        assert calls.answer() == "Signups grew."
        assert [(s.plan_title or "").startswith("Done in ") for s in calls.stops] == [True]

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
            [("agent_text_delta", "Checking."), ("agent_status_update", {"phase": "posthog:Execute SQL query"}), *tail]
        )

        assert calls.answer() == "Answer."

    @pytest.mark.parametrize(
        "work, work_lines",
        [
            (
                [("agent_status_update", {"phase": "posthog:Execute SQL query"})],
                [("Execute SQL query", None, "complete")],
            ),
            ([("agent_text_delta", "Hi! What should I look at?")], []),
        ],
        ids=["tool_call", "answer_without_tools"],
    )
    @pytest.mark.timeout(60, func_only=True)
    async def test_setup_steps_change_in_place_and_complete(
        self, work: list[tuple[str, Any]], work_lines: list[tuple[str, None, str]]
    ) -> None:
        # A later update of a setup step must not add a second line, and a step still open when
        # the agent works must not keep spinning, or end as a failure.
        calls = await _run_relay(
            [
                ("setup_step", {"step": "sandbox", "status": "completed", "title": "Sandbox ready"}),
                ("setup_step", {"step": "clone", "status": "in_progress", "title": "Cloning repository"}),
                *work,
            ],
            setup_title="Setting up sandbox",
        )

        assert [[(c.title, c.status) for c in s.task_updates] for s in calls.starts] == [
            [("Setting up sandbox", "in_progress")]
        ]
        assert list(calls.final_lines().values()) == [
            ("Sandbox ready", None, "complete"),
            ("Cloning repository", None, "complete"),
            *work_lines,
        ]
        assert [(s.plan_title or "").startswith("Done in ") for s in calls.stops] == [True]

    @pytest.mark.parametrize(
        "work, last_line, plan_title",
        [
            (
                [("agent_status_update", {"phase": "posthog:Execute SQL query", "activity": "Count weekly signups"})],
                ("Execute SQL query", "Count weekly signups", "complete"),
                "Count weekly signups",
            ),
            (
                [("agent_text_delta", "Hi! What should I look at?")],
                ("Writing the answer", None, "complete"),
                "Thinking",
            ),
        ],
        ids=["tool_call", "answer_without_tools"],
    )
    @pytest.mark.timeout(60, func_only=True)
    async def test_a_line_spins_between_setup_and_work(
        self, work: list[tuple[str, Any]], last_line: tuple[str, str | None, str], plan_title: str
    ) -> None:
        # With setup done and no call yet, nothing else shows that the agent is working. The
        # next line must take over the placeholder, or a finished "Thinking" line stays behind.
        calls = await _run_relay(
            [
                ("setup_step", {"step": "sandbox", "status": "completed", "title": "Sandbox ready"}),
                ("setup_step", {"step": "agent", "status": "completed", "title": "Agent ready"}),
                (WAIT, 10),
                *work,
            ],
            setup_title="Setting up sandbox",
        )

        assert ("Thinking", "in_progress") in [(c.title, c.status) for c in calls.sent_chunks()]
        # A collapsed plan shows only its title, so the title must say what happens now.
        assert [s.plan_title for s in calls.starts] == ["Setting up sandbox"]
        assert [a.plan_title for a in calls.appends if a.plan_title][-1] == plan_title
        assert list(calls.final_lines().values()) == [
            ("Sandbox ready", None, "complete"),
            ("Agent ready", None, "complete"),
            last_line,
        ]

    @pytest.mark.timeout(60, func_only=True)
    async def test_quiet_relay_resends_its_open_line(self) -> None:
        # Slack ends a stream that gets no update for a few minutes and fails its open step.
        calls = await _run_relay([(WAIT, 130)], setup_title="Setting up sandbox")

        resent = [c for a in calls.appends for c in a.task_updates if c.title == "Setting up sandbox"]
        assert len(resent) >= 2

    @pytest.mark.timeout(60, func_only=True)
    async def test_answer_without_steps_opens_the_stream_with_its_mention(self) -> None:
        # The stop call must not mention the requester again, or they get a second ping.
        calls = await _run_relay([("agent_text_delta", "Signups grew.")])

        assert [s.first_markdown_text for s in calls.starts] == ["Signups grew."]
        assert [s.mention_sent for s in calls.stops] == [True]

    @pytest.mark.timeout(60, func_only=True)
    async def test_stopped_run_marks_the_open_step_failed(self) -> None:
        # A run that fails during provisioning must not leave the setup step spinning, or read as done.
        calls = await _run_relay([], setup_title="Setting up sandbox", cancel=True)

        assert list(calls.final_lines().values()) == [("Setting up sandbox", None, "error")]
        assert [s.plan_title for s in calls.stops] == ["Stopped"]

    @pytest.mark.timeout(60, func_only=True)
    async def test_phases_past_the_line_limit_fold_into_other_work(self) -> None:
        keys = [f"posthog:Category {index}" for index in range(9)]
        calls = await _run_relay([("agent_status_update", {"phase": key}) for key in keys])

        titles = [title for title, _details, _status in calls.final_lines().values()]
        assert len(titles) == 7
        assert "Other work (3 steps)" in titles

    @pytest.mark.parametrize(
        "cancel, expected_status, expected_title",
        [(False, "complete", "Done in "), (True, "error", "Stopped")],
        ids=["turn_completes", "run_stops"],
    )
    @pytest.mark.timeout(60, func_only=True)
    async def test_agent_todo_list_replaces_the_phase_lines(
        self, cancel: bool, expected_status: str, expected_title: str
    ) -> None:
        # Slack turns a step still pending at the end into a failure, so a finished turn must
        # complete the leftovers, and a stopped run must not read as done.
        plan = [
            {"title": "Find the signup event", "status": "in_progress"},
            {"title": "Count weekly signups", "status": "pending"},
        ]
        calls = await _run_relay(
            [
                ("agent_status_update", {"plan": plan}),
                ("agent_status_update", {"phase": "reading_code"}),
            ],
            cancel=cancel,
        )

        assert sorted(calls.final_lines().values()) == [
            ("Count weekly signups", None, expected_status),
            ("Find the signup event", None, expected_status),
        ]
        assert [(s.plan_title or "").startswith(expected_title) for s in calls.stops] == [True]
