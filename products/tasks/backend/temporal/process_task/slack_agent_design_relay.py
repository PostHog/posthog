"""Per-turn child of ProcessTaskWorkflow.

Drives one chat.startStream message per turn:

- A plan block with one line per kind of work (see ``slack_progress_phases``). A line
  appears the first time its phase is used and completes the line before it. Later calls
  of an earlier phase only move that line's counter. Tool names and arguments never show.
  The open line shows the description of the running shell command when the agent gave one.
  Phases past ``MAX_PLAN_LINES`` fold into one "Other work" line.
- The agent's prose is not streamed while it works. Each tool call ends a burst of prose,
  and the last non-empty burst streams as the final answer when the turn completes.
- The plan title reads "Working on it" while the turn runs and "Done in …" when it ends.

The first turn's relay starts before the sandbox exists, with a ``setup_title``. It opens
the plan at once with one setup line, so the thread shows progress while the sandbox
provisions. Slack draws no plan without a line, and cannot remove one, so the first work
line takes over the setup line instead of adding a second one.

Slack ends a stream that gets no update for a few minutes and marks its open step as
failed, so a quiet relay re-sends its open line as a keep-alive.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from .activities.slack_agent_design import (
        AppendSlackAgentDesignStepsInput,
        SlackAgentDesignStream,
        StartSlackAgentDesignStreamInput,
        StopSlackAgentDesignStreamInput,
        TaskUpdateChunk,
        append_slack_agent_design_steps,
        start_slack_agent_design_stream,
        stop_slack_agent_design_stream,
    )
    from .slack_progress_phases import (
        ANSWER_LINE_TITLE,
        OTHER_WORK,
        PHASES,
        PLAN_TITLE_STOPPED,
        PLAN_TITLE_WORKING,
        done_plan_title,
        phase_line_title,
    )


STATUS_DEBOUNCE_SECONDS = 1.0
STATUS_MIN_INTERVAL_SECONDS = 2.0
KEEPALIVE_SECONDS = 60
MAX_PLAN_LINES = 7
# One tool call, such as a long test run, can keep the agent quiet for a long time.
TURN_IDLE_TIMEOUT_MINUTES = 30
_ACTIVITY_TIMEOUT = timedelta(seconds=30)
_ACTIVITY_RETRY = RetryPolicy(maximum_attempts=3)


@dataclass
class SlackAgentDesignRelayInput:
    slack_thread_context: dict[str, Any]
    run_id: Optional[str] = None
    # Set for the relay that starts before the sandbox exists: the title of the setup line.
    setup_title: Optional[str] = None


@workflow.defn(name="slack-agent-design-relay")
class SlackAgentDesignRelayWorkflow(PostHogWorkflow):
    def __init__(self) -> None:
        # Phase keys in the order their lines appeared, and the Slack task id of each line.
        self._line_order: list[str] = []
        self._line_ids: dict[str, str] = {}
        self._counts: dict[str, int] = {}
        self._current_key: Optional[str] = None
        # The description of the latest call per line, shown while that line is open.
        self._activity: dict[str, Optional[str]] = {}
        # The setup line, until the first work line takes over its Slack task id.
        self._setup_line: Optional[TaskUpdateChunk] = None
        # Lines added, and lines whose counter moved, since the last flush.
        self._new_keys: list[str] = []
        self._changed_keys: set[str] = set()
        # Prose since the last tool call, and the last non-empty burst before it.
        self._narrative: str = ""
        self._last_burst: str = ""
        self._stream: Optional[SlackAgentDesignStream] = None
        self._last_dispatched_at: float = 0.0
        self._last_signal_at: Optional[datetime] = None
        self._started_at: Optional[datetime] = None
        self._turn_complete: bool = False
        # Gateway trace id of the turn this relay is streaming, as ``complete_turn``
        # reports it. The closing reply carries the thumbs, so this is what a rating on
        # them names.
        self._trace_id: Optional[str] = None

    @workflow.signal
    async def agent_status_update(self, payload: dict[str, Any] | str) -> None:
        """A tool call. It ends the prose burst before it, and counts toward its phase when it has one."""
        self._last_signal_at = workflow.now()
        if self._narrative.strip():
            self._last_burst = self._narrative
        self._narrative = ""

        key = payload.get("phase") if isinstance(payload, dict) else None
        if not isinstance(key, str) or key not in PHASES:
            return
        if key not in self._line_ids and len(self._line_order) >= MAX_PLAN_LINES - 1:
            key = OTHER_WORK.key
        activity = payload.get("activity") if isinstance(payload, dict) else None
        self._activity[key] = activity if isinstance(activity, str) and activity else None
        self._counts[key] = self._counts.get(key, 0) + 1
        if key not in self._line_ids:
            if self._setup_line is not None:
                self._line_ids[key] = self._setup_line.id
                self._setup_line = None
            else:
                self._line_ids[key] = str(workflow.uuid4())
            self._line_order.append(key)
            self._new_keys.append(key)
        else:
            self._changed_keys.add(key)

    @workflow.signal
    async def agent_text_delta(self, text: str) -> None:
        self._last_signal_at = workflow.now()
        if isinstance(text, str) and text:
            self._narrative += text

    @workflow.signal
    async def complete_turn(self, trace_id: str | None = None) -> None:
        self._turn_complete = True
        self._trace_id = trace_id

    def _line_chunk(self, key: str, status: str) -> TaskUpdateChunk:
        activity = self._activity.get(key) if status == "in_progress" and key == self._current_key else None
        title = phase_line_title(PHASES[key], self._counts.get(key, 0), activity)
        return TaskUpdateChunk(id=self._line_ids[key], title=title, status=status)

    def _open_line(self) -> Optional[TaskUpdateChunk]:
        """The line shown in progress right now."""
        if self._current_key is not None:
            return self._line_chunk(self._current_key, "in_progress")
        return self._setup_line

    def _take_pending_chunks(self) -> list[TaskUpdateChunk]:
        """Chunks for the lines added or changed since the last flush, in plan order."""
        chunks: list[TaskUpdateChunk] = []
        for key in sorted(self._changed_keys, key=self._line_order.index):
            if key not in self._new_keys:
                chunks.append(self._line_chunk(key, "in_progress" if key == self._current_key else "complete"))
        for key in self._new_keys:
            if self._current_key is not None:
                chunks.append(self._line_chunk(self._current_key, "complete"))
            self._current_key = key
            chunks.append(self._line_chunk(key, "in_progress"))
        self._new_keys = []
        self._changed_keys = set()
        return chunks

    def _has_pending(self) -> bool:
        return bool(self._new_keys or self._changed_keys)

    def _closing_plan_title(self) -> Optional[str]:
        if self._stream is None or not (self._stream.has_plan or self._line_order):
            return None
        if not self._turn_complete:
            return PLAN_TITLE_STOPPED
        return done_plan_title(workflow.now() - (self._started_at or workflow.now()))

    def _final_answer(self) -> str:
        return (self._narrative if self._narrative.strip() else self._last_burst).strip()

    def _idle_for(self, started_at: datetime) -> timedelta:
        return workflow.now() - (self._last_signal_at or started_at)

    async def _start_stream(self, input: SlackAgentDesignRelayInput, **fields: Any) -> Optional[SlackAgentDesignStream]:
        return await workflow.execute_activity(
            start_slack_agent_design_stream,
            StartSlackAgentDesignStreamInput(slack_thread_context=input.slack_thread_context, **fields),
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY,
        )

    async def _append(self, input: SlackAgentDesignRelayInput, chunks: list[TaskUpdateChunk]) -> None:
        assert self._stream is not None
        await workflow.execute_activity(
            append_slack_agent_design_steps,
            AppendSlackAgentDesignStepsInput(
                slack_thread_context=input.slack_thread_context,
                ts=self._stream.ts,
                task_updates=chunks,
            ),
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY,
        )

    @workflow.run
    async def run(self, input: SlackAgentDesignRelayInput) -> None:
        started_at = workflow.now()
        self._started_at = started_at
        try:
            if input.setup_title:
                self._setup_line = TaskUpdateChunk(
                    id=str(workflow.uuid4()), title=input.setup_title, status="in_progress"
                )
                self._stream = await self._start_stream(
                    input, task_updates=[self._setup_line], plan_title=PLAN_TITLE_WORKING
                )
                if self._stream is None:
                    return

            while not self._turn_complete:
                try:
                    await workflow.wait_condition(
                        lambda: self._has_pending() or self._turn_complete,
                        timeout=timedelta(seconds=KEEPALIVE_SECONDS),
                    )
                except TimeoutError:
                    if self._idle_for(started_at) >= timedelta(minutes=TURN_IDLE_TIMEOUT_MINUTES):
                        workflow.logger.warning(
                            "slack_app_agent_design_relay_idle_timeout",
                            extra={"workflow_id": workflow.info().workflow_id},
                        )
                        return
                    open_line = self._open_line()
                    if self._stream is not None and open_line is not None:
                        await self._append(input, [open_line])
                    continue

                if self._turn_complete:
                    break  # type: ignore[unreachable]

                await workflow.sleep(STATUS_DEBOUNCE_SECONDS)
                elapsed = workflow.now().timestamp() - self._last_dispatched_at
                if elapsed < STATUS_MIN_INTERVAL_SECONDS:
                    await workflow.sleep(STATUS_MIN_INTERVAL_SECONDS - elapsed)

                chunks = self._take_pending_chunks()
                if not chunks:
                    continue
                self._last_dispatched_at = workflow.now().timestamp()

                if self._stream is None:
                    self._stream = await self._start_stream(input, task_updates=chunks, plan_title=PLAN_TITLE_WORKING)
                    if self._stream is None:
                        return
                    continue
                await self._append(input, chunks)
        finally:
            await self._close_stream(input)

    async def _close_stream(self, input: SlackAgentDesignRelayInput) -> None:
        final_answer = self._final_answer()
        final_for_stop: Optional[str] = final_answer or None
        # Lines that never reached Slack because the turn ended inside the debounce window.
        pending = self._take_pending_chunks()
        if self._stream is None and (final_answer or pending):
            # A turn with no flushed step still streams its answer in a stream of its own.
            self._stream = await self._start_stream(
                input,
                task_updates=pending,
                first_markdown_text=final_answer or None,
                plan_title=PLAN_TITLE_WORKING if pending else None,
            )
            final_for_stop = None
            pending = []
        if self._stream is None:
            return
        if self._current_key is not None:
            closing: Optional[TaskUpdateChunk] = self._line_chunk(self._current_key, "complete")
        elif self._setup_line is not None:
            # The turn used no tool, so the setup line is the only line the plan has.
            closing = TaskUpdateChunk(id=self._setup_line.id, title=self._setup_line.title, status="complete")
            if self._turn_complete:
                closing = TaskUpdateChunk(id=closing.id, title=ANSWER_LINE_TITLE, status="complete")
        else:
            closing = None
        if closing is not None and not self._turn_complete:
            # The run stopped inside this step, so it must not read as done.
            pending.append(TaskUpdateChunk(id=closing.id, title=closing.title, status="error"))
            closing = None
        if pending:
            await self._append(input, pending)
        await workflow.execute_activity(
            stop_slack_agent_design_stream,
            StopSlackAgentDesignStreamInput(
                slack_thread_context=input.slack_thread_context,
                ts=self._stream.ts,
                complete_task_id=closing.id if closing else None,
                complete_task_title=closing.title if closing else None,
                final_markdown=final_for_stop,
                run_id=input.run_id,
                trace_id=self._trace_id,
                plan_title=self._closing_plan_title(),
            ),
            # Attachments upload inside this activity. One attempt, because a retry would
            # append the answer a second time.
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
