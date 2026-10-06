"""Per-turn child of ProcessTaskWorkflow that streams one Slack reply.

The reply is a plan block and the final answer. The plan shows one line per kind of work (see
``products.slack_app.backend.logic.progress_phases``), or the agent's todo list when it keeps one. Each line lists the
descriptions of its calls. The agent's prose does not stream: the answer is the final text the
agent server reports for the turn, or the last burst before the turn ends when that text does not
arrive in time. While the turn runs, one line always spins and the plan title says what happens now.

The first turn's relay starts before the sandbox exists, so the plan shows the setup steps the
parent sends through ``setup_step``. Slack ends a stream that gets no update for a few minutes,
so a quiet relay re-sends its open line.
"""

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.dataclasses import frozen
from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from products.slack_app.backend.facade.api import (
        ANSWER_LINE_TITLE,
        OTHER_WORK,
        PLAN_TITLE_STOPPED,
        PLAN_TITLE_WORKING,
        PREPARING_LINE_TITLE,
        SLACK_STEP_STATUSES,
        THINKING_LINE_TITLE,
        ProgressPhase,
        done_plan_title,
        intent_from_narrative,
        phase_for_key,
        phase_line_title,
    )

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


STATUS_DEBOUNCE_SECONDS = 1.0
STATUS_MIN_INTERVAL_SECONDS = 2.0
KEEPALIVE_SECONDS = 60
MAX_PLAN_LINES = 7
# One tool call, such as a long test run, can keep the agent quiet for a long time.
TURN_IDLE_TIMEOUT_MINUTES = 30
_ACTIVITY_TIMEOUT = timedelta(seconds=30)
_ACTIVITY_RETRY = RetryPolicy(maximum_attempts=3)
# The parent's progress step that the first setup line shows.
_SANDBOX_SETUP_STEP = "sandbox"
_PATCH_ID_STREAM_ENDED = "tasks-slack-relay-stream-ended"


def _trace_key(trace_id: Optional[str]) -> Optional[str]:
    """The trace id in one form. The relay endpoint sends it as a hyphenated UUID, and the turn-complete
    event sends the W3C form, which is the same 32 hex digits without hyphens."""
    return trace_id.replace("-", "").lower() if trace_id else None


@frozen
class SlackAgentDesignRelayInput:
    slack_thread_context: dict[str, Any]
    run_id: Optional[str] = None
    # Set for the relay that starts before the sandbox exists: the title of the first setup line.
    setup_title: Optional[str] = None
    # The message this turn answers, so the reply tags its sender.
    message_id: Optional[str] = None


@workflow.defn(name="slack-agent-design-relay")
class SlackAgentDesignRelayWorkflow(PostHogWorkflow):
    def __init__(self) -> None:
        # Slack task id per phase line, in the order the lines appeared.
        self._line_ids: dict[str, str] = {}
        self._phases: dict[str, ProgressPhase] = {}
        self._counts: dict[str, int] = {}
        self._current_key: Optional[str] = None
        # Slack appends a step's details, so each call description is sent once.
        self._unsent_details: dict[str, list[str]] = {}
        self._keys_with_details: set[str] = set()
        self._last_description: dict[str, str] = {}
        self._plan_title: Optional[str] = None
        self._latest_description: Optional[str] = None
        # The spinning line shown while no step is open, until the next line takes over its id.
        self._placeholder: Optional[TaskUpdateChunk] = None
        self._setup_lines: dict[str, TaskUpdateChunk] = {}
        self._changed_setup_steps: list[str] = []
        self._agent_plan: list[TaskUpdateChunk] = []
        self._agent_plan_changed: bool = False
        # Lines added, and lines whose counter moved, since the last flush.
        self._new_keys: list[str] = []
        self._changed_keys: set[str] = set()
        # Prose since the last tool call, and the last non-empty burst before it.
        self._narrative: str = ""
        self._last_burst: str = ""
        # The whole answer as the agent server reports it. It can arrive between two text deltas,
        # so it is kept apart from the deltas and replaces them at close.
        self._final_text: str = ""
        self._final_text_trace_id: Optional[str] = None
        # Whether this turn's agent sent a tool call or prose yet.
        self._turn_has_activity: bool = False
        self._stream: Optional[SlackAgentDesignStream] = None
        # Slack closed the stream early. Later appends to it can only fail.
        self._stream_ended: bool = False
        self._last_dispatched_at: float = 0.0
        self._last_signal_at: Optional[datetime] = None
        self._started_at: datetime = datetime.min
        self._turn_complete: bool = False
        # Gateway trace id of the turn this relay is streaming, as ``complete_turn``
        # reports it. The closing reply carries the thumbs, so this is what a rating on
        # them names.
        self._trace_id: Optional[str] = None

    @workflow.signal
    async def agent_status_update(self, payload: dict[str, Any] | str) -> None:
        """A tool call or a new agent todo list. Either ends the prose burst before it."""
        self._last_signal_at = workflow.now()
        self._turn_has_activity = True
        narrative, self._narrative = self._narrative, ""
        if narrative.strip():
            self._last_burst = narrative

        if not isinstance(payload, dict):
            return
        # The agent is working, so the sandbox is ready.
        self._finish_setup("complete")
        if isinstance(payload.get("plan"), list):
            self._set_agent_plan(payload["plan"])
            return
        if self._agent_plan:
            return
        key = payload.get("phase")
        phase = phase_for_key(key) if isinstance(key, str) else None
        if phase is None:
            return
        if phase.key not in self._line_ids and len(self._line_ids) >= MAX_PLAN_LINES - 1:
            phase = OTHER_WORK
        key = phase.key
        self._phases[key] = phase
        description = payload.get("activity")
        if not isinstance(description, str) or not description:
            description = intent_from_narrative(narrative) if narrative.strip() else None
        self._latest_description = description
        if description and description != self._last_description.get(key):
            self._last_description[key] = description
            self._unsent_details.setdefault(key, []).append(description)
        self._counts[key] = self._counts.get(key, 0) + 1
        if key not in self._line_ids:
            self._line_ids[key] = self._claim_line_id()
            self._new_keys.append(key)
        else:
            self._changed_keys.add(key)

    def _set_agent_plan(self, steps: list[Any]) -> None:
        lines: list[TaskUpdateChunk] = []
        for index, step in enumerate(steps):
            if not isinstance(step, dict) or not isinstance(step.get("title"), str):
                continue
            line_id = self._agent_plan[index].id if index < len(self._agent_plan) else self._claim_line_id()
            lines.append(TaskUpdateChunk(id=line_id, title=step["title"], status=str(step.get("status") or "pending")))
        if lines:
            # A step the agent dropped keeps its line, because Slack cannot remove one.
            self._agent_plan = lines + self._agent_plan[len(lines) :]
            self._agent_plan_changed = True

    @workflow.signal
    async def setup_step(self, payload: dict[str, Any]) -> None:
        """A sandbox setup step, such as "Cloning repository", before the agent runs."""
        self._last_signal_at = workflow.now()
        step, title = payload.get("step"), payload.get("title")
        if not isinstance(step, str) or not isinstance(title, str) or not title:
            return
        existing = self._setup_lines.get(step)
        self._setup_lines[step] = TaskUpdateChunk(
            id=existing.id if existing else self._claim_line_id(),
            title=title,
            status=SLACK_STEP_STATUSES.get(str(payload.get("status")), "in_progress"),
        )
        self._mark_setup_changed(step)

    def _claim_line_id(self) -> str:
        """The Slack task id for a new line. The placeholder's id turns the placeholder into it."""
        if self._placeholder is None:
            return str(workflow.uuid4())
        line_id = self._placeholder.id
        self._placeholder = None
        return line_id

    def _needs_placeholder(self) -> bool:
        if self._turn_complete or self._placeholder is not None or self._current_key is not None:
            return False
        if self._agent_plan or not self._setup_lines:
            return False
        return all(line.status != "in_progress" for line in self._setup_lines.values())

    def _mark_setup_changed(self, step: str) -> None:
        if step not in self._changed_setup_steps:
            self._changed_setup_steps.append(step)

    def _finish_setup(self, status: str) -> None:
        for step, line in self._setup_lines.items():
            if line.status == "in_progress":
                self._setup_lines[step] = replace(line, status=status)
                self._mark_setup_changed(step)

    @workflow.signal
    async def agent_text_delta(self, text: str) -> None:
        self._last_signal_at = workflow.now()
        if isinstance(text, str) and text:
            self._narrative += text
            self._turn_has_activity = True

    @workflow.signal
    async def agent_final_text(self, payload: dict[str, Any]) -> None:
        # The agent server sends a turn's final text after the turn ends. A late one can reach the
        # relay of the next turn, which has no activity yet, and must not become its answer.
        if not self._turn_has_activity:
            return
        text = payload.get("text")
        if isinstance(text, str) and text.strip():
            self._final_text = text.strip()
            trace_id = payload.get("trace_id")
            self._final_text_trace_id = trace_id if isinstance(trace_id, str) else None

    @workflow.signal
    async def complete_turn(self, trace_id: str | None = None) -> None:
        self._turn_complete = True
        self._trace_id = trace_id

    def _line_chunk(self, key: str, status: str, *, with_details: bool = False) -> TaskUpdateChunk:
        title = phase_line_title(self._phases[key], self._counts.get(key, 0))
        details = None
        unsent = self._unsent_details.pop(key, None) if with_details else None
        if unsent:
            # Slack appends details to the text it shows, so later descriptions start a new line.
            details = ("\n" if key in self._keys_with_details else "") + "\n".join(unsent)
            self._keys_with_details.add(key)
        return TaskUpdateChunk(id=self._line_ids[key], title=title, status=status, details=details)

    def _open_agent_step(self) -> Optional[TaskUpdateChunk]:
        return next((line for line in self._agent_plan if line.status == "in_progress"), None)

    def _open_line(self) -> Optional[TaskUpdateChunk]:
        """The line shown in progress right now."""
        if self._agent_plan:
            return self._open_agent_step() or self._agent_plan[-1]
        if self._current_key is not None:
            return self._line_chunk(self._current_key, "in_progress")
        setup_line = next((line for line in reversed(self._setup_lines.values()) if line.status == "in_progress"), None)
        return setup_line or self._placeholder

    def _take_pending_chunks(self, *, allow_placeholder: bool = True) -> list[TaskUpdateChunk]:
        """Chunks for the lines added or changed since the last flush, in plan order."""
        chunks = [self._setup_lines[step] for step in self._changed_setup_steps]
        self._changed_setup_steps = []
        for key in self._line_ids:
            if key in self._changed_keys and key not in self._new_keys:
                status = "in_progress" if key == self._current_key else "complete"
                chunks.append(self._line_chunk(key, status, with_details=True))
        for key in self._new_keys:
            if self._current_key is not None:
                chunks.append(self._line_chunk(self._current_key, "complete"))
            self._current_key = key
            chunks.append(self._line_chunk(key, "in_progress", with_details=True))
        self._new_keys = []
        self._changed_keys = set()
        if self._agent_plan_changed:
            if self._current_key is not None:
                # The todo list takes over from here, so the phase line it interrupts is done.
                chunks.append(self._line_chunk(self._current_key, "complete"))
                self._current_key = None
            chunks.extend(self._agent_plan)
            self._agent_plan_changed = False
        if allow_placeholder and self._needs_placeholder():
            agent_ready = self._setup_lines.get("agent")
            title = THINKING_LINE_TITLE if agent_ready and agent_ready.status == "complete" else PREPARING_LINE_TITLE
            self._placeholder = TaskUpdateChunk(id=str(workflow.uuid4()), title=title, status="in_progress")
            chunks.append(self._placeholder)
        return chunks

    def _current_plan_title(self) -> str:
        """What happens now: the open line, or the description of the call it runs."""
        if self._agent_plan:
            open_step = self._open_agent_step()
            return open_step.title if open_step else PLAN_TITLE_WORKING
        if self._current_key is not None:
            return self._latest_description or self._phases[self._current_key].title
        open_line = self._open_line()
        return open_line.title if open_line else PLAN_TITLE_WORKING

    def _plan_title_update(self) -> Optional[str]:
        """The plan title to send with the next lines, when it changed."""
        title = self._current_plan_title()
        if title == self._plan_title:
            return None
        self._plan_title = title
        return title

    def _has_pending(self) -> bool:
        return bool(self._new_keys or self._changed_keys or self._agent_plan_changed or self._changed_setup_steps)

    def _closing_plan_title(self) -> Optional[str]:
        if self._stream is None or not (self._stream.has_plan or self._line_ids or self._agent_plan):
            return None
        if not self._turn_complete:
            return PLAN_TITLE_STOPPED
        return done_plan_title(workflow.now() - self._started_at)

    def _final_answer(self) -> str:
        # A trace id that differs from this turn's means the text is a late answer of an earlier turn.
        # A turn that the agent starts after a background task ends with no trace id, and the agent
        # server sends no final text for it, so a final text with a trace id is an earlier answer too.
        final_trace, turn_trace = _trace_key(self._final_text_trace_id), _trace_key(self._trace_id)
        stale = bool(final_trace and final_trace != turn_trace)
        if self._final_text and not stale:
            return self._final_text
        return (self._narrative if self._narrative.strip() else self._last_burst).strip()

    def _idle_for(self) -> timedelta:
        return workflow.now() - (self._last_signal_at or self._started_at)

    async def _start_stream(self, input: SlackAgentDesignRelayInput, **fields: Any) -> Optional[SlackAgentDesignStream]:
        return await workflow.execute_activity(
            start_slack_agent_design_stream,
            StartSlackAgentDesignStreamInput(
                slack_thread_context=input.slack_thread_context,
                run_id=input.run_id,
                message_id=input.message_id,
                **fields,
            ),
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY,
        )

    async def _append(
        self, input: SlackAgentDesignRelayInput, chunks: list[TaskUpdateChunk], plan_title: Optional[str] = None
    ) -> None:
        assert self._stream is not None
        if self._stream_ended:
            return
        stream_open = await workflow.execute_activity(
            append_slack_agent_design_steps,
            AppendSlackAgentDesignStepsInput(
                slack_thread_context=input.slack_thread_context,
                ts=self._stream.ts,
                task_updates=chunks,
                plan_title=plan_title,
            ),
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY,
        )
        # An older activity returns None, which means the stream is still open. The patch keeps
        # histories that older workflow code wrote on their recorded command sequence.
        if stream_open is False and workflow.patched(_PATCH_ID_STREAM_ENDED):
            self._stream_ended = True

    @workflow.run
    async def run(self, input: SlackAgentDesignRelayInput) -> None:
        self._started_at = workflow.now()
        try:
            if input.setup_title:
                setup_line = TaskUpdateChunk(id=str(workflow.uuid4()), title=input.setup_title, status="in_progress")
                self._setup_lines[_SANDBOX_SETUP_STEP] = setup_line
                self._plan_title = input.setup_title
                self._stream = await self._start_stream(input, task_updates=[setup_line], plan_title=input.setup_title)
                if self._stream is None:
                    return

            while not self._turn_complete:
                try:
                    await workflow.wait_condition(
                        lambda: self._has_pending() or self._turn_complete,
                        timeout=timedelta(seconds=KEEPALIVE_SECONDS),
                    )
                except TimeoutError:
                    if self._idle_for() >= timedelta(minutes=TURN_IDLE_TIMEOUT_MINUTES):
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

                plan_title = self._plan_title_update()
                if self._stream is None:
                    self._stream = await self._start_stream(input, task_updates=chunks, plan_title=self._plan_title)
                    if self._stream is None:
                        return
                    continue
                await self._append(input, chunks, plan_title)
        finally:
            await self._close_stream(input)

    def _closing_line(self) -> Optional[TaskUpdateChunk]:
        """The open line, which the stop call marks complete."""
        if self._agent_plan:
            return None
        if self._current_key is not None:
            return self._line_chunk(self._current_key, "complete")
        if self._placeholder is not None:
            # The turn answered without a tool, so the placeholder is where the answer came from.
            title = ANSWER_LINE_TITLE if self._turn_complete else self._placeholder.title
            return replace(self._placeholder, title=title, status="complete")
        return None

    async def _close_stream(self, input: SlackAgentDesignRelayInput) -> None:
        final_answer = self._final_answer()
        final_for_stop: Optional[str] = final_answer or None
        mention_sent = False
        # Slack marks a step still open at the end as failed. A finished turn completes the setup
        # and agent steps left open, and a stopped one leaves every unfinished step failed.
        final_status = "complete" if self._turn_complete else "error"
        self._finish_setup(final_status)
        # Lines that never reached Slack because the turn ended inside the debounce window.
        pending = self._take_pending_chunks(allow_placeholder=False)
        if self._stream_ended:
            # The plan is gone with the closed stream, so the answer opens a new message of its own.
            self._stream = None
            pending = []
            self._line_ids = {}
            self._agent_plan = []
            self._current_key = None
            self._placeholder = None
        if self._stream is None and (final_answer or pending):
            # A turn with no flushed step still streams its answer in a stream of its own.
            self._stream = await self._start_stream(
                input,
                task_updates=pending,
                first_markdown_text=final_answer or None,
                plan_title=PLAN_TITLE_WORKING if pending else None,
            )
            final_for_stop = None
            mention_sent = bool(final_answer)
            pending = []
        if self._stream is None:
            return
        pending.extend(replace(line, status=final_status) for line in self._agent_plan if line.status != "complete")
        closing = self._closing_line()
        if closing is not None and not self._turn_complete:
            # The run stopped inside this step, so it must not read as done.
            pending.append(replace(closing, status="error"))
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
                mention_sent=mention_sent,
                actor_slack_user_id=self._stream.actor_slack_user_id,
            ),
            # Attachments upload inside this activity. One attempt, because a retry would
            # append the answer a second time.
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
