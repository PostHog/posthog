"""Per-turn child of ProcessTaskWorkflow. status_update/text_delta signals →
debounced 1s + throttled ≥2s into one chat.appendStream per flush."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from .activities.slack_agent_design import (
        AppendSlackAgentDesignStepInput,
        StartSlackAgentDesignStreamInput,
        StopSlackAgentDesignStreamInput,
        TaskUpdateChunk,
        append_slack_agent_design_step,
        start_slack_agent_design_stream,
        stop_slack_agent_design_stream,
    )


STATUS_DEBOUNCE_SECONDS = 1.0
STATUS_MIN_INTERVAL_SECONDS = 2.0
TURN_IDLE_TIMEOUT_MINUTES = 5


@dataclass
class PendingStep:
    title: str
    details: Optional[str]


@dataclass
class SlackAgentDesignRelayInput:
    slack_thread_context: dict[str, Any]


@workflow.defn(name="slack-agent-design-relay")
class SlackAgentDesignRelayWorkflow(PostHogWorkflow):
    def __init__(self) -> None:
        # Each tool call enqueues its own entry — never deduplicate.
        self._pending_steps: list[PendingStep] = []
        self._pending_markdown_buffer: str = ""
        self._stream_ts: Optional[str] = None
        self._current_task_id: Optional[str] = None
        self._current_task_title: Optional[str] = None
        self._current_task_details: Optional[str] = None
        self._last_dispatched_at: float = 0.0
        self._turn_complete: bool = False

    @workflow.signal
    async def agent_status_update(self, payload: dict[str, Any] | str) -> None:
        """Enqueue a step. Str payload accepted for in-flight pre-enrichment relays."""
        if isinstance(payload, str):
            self._pending_steps.append(PendingStep(title=payload, details=None))
            return
        title = payload.get("title") or payload.get("text")
        if not isinstance(title, str) or not title:
            return
        details = payload.get("details")
        self._pending_steps.append(
            PendingStep(
                title=title,
                details=details if isinstance(details, str) and details else None,
            )
        )

    @workflow.signal
    async def agent_text_delta(self, text: str) -> None:
        if not isinstance(text, str) or not text:
            return
        self._pending_markdown_buffer += text

    @workflow.signal
    async def complete_turn(self) -> None:
        self._turn_complete = True

    def _has_pending(self) -> bool:
        return bool(self._pending_steps) or bool(self._pending_markdown_buffer)

    def _build_transition_chunks(self, steps: list[PendingStep]) -> list[TaskUpdateChunk]:
        """Previous step → complete, intermediates → complete, last → in_progress."""
        chunks: list[TaskUpdateChunk] = []
        if not steps:
            return chunks
        if self._current_task_id and self._current_task_title:
            chunks.append(
                TaskUpdateChunk(
                    id=self._current_task_id,
                    title=self._current_task_title,
                    status="complete",
                    details=self._current_task_details,
                )
            )
        for s in steps[:-1]:
            chunks.append(
                TaskUpdateChunk(
                    id=str(workflow.uuid4()),
                    title=s.title,
                    status="complete",
                    details=s.details,
                )
            )
        last = steps[-1]
        last_id = str(workflow.uuid4())
        chunks.append(
            TaskUpdateChunk(
                id=last_id,
                title=last.title,
                status="in_progress",
                details=last.details,
            )
        )
        self._current_task_id = last_id
        self._current_task_title = last.title
        self._current_task_details = last.details
        return chunks

    @workflow.run
    async def run(self, input: SlackAgentDesignRelayInput) -> None:
        try:
            while not self._turn_complete:
                try:
                    await workflow.wait_condition(
                        lambda: self._has_pending() or self._turn_complete,
                        timeout=timedelta(minutes=TURN_IDLE_TIMEOUT_MINUTES),
                    )
                except TimeoutError:
                    workflow.logger.warning(
                        "slack_app_agent_design_relay_idle_timeout",
                        extra={"workflow_id": workflow.info().workflow_id},
                    )
                    return

                # complete_turn signal can flip this while we were waiting above.
                if self._turn_complete:
                    break  # type: ignore[unreachable]

                await workflow.sleep(STATUS_DEBOUNCE_SECONDS)

                elapsed = workflow.now().timestamp() - self._last_dispatched_at
                if elapsed < STATUS_MIN_INTERVAL_SECONDS:
                    await workflow.sleep(STATUS_MIN_INTERVAL_SECONDS - elapsed)

                steps = self._pending_steps
                self._pending_steps = []
                markdown = self._pending_markdown_buffer
                self._pending_markdown_buffer = ""

                if not steps and not markdown:
                    continue

                self._last_dispatched_at = workflow.now().timestamp()

                if self._stream_ts is None:
                    # The plan block needs at least one step to open.
                    if not steps:
                        steps = [PendingStep(title="Thinking", details=None)]
                    first_step = steps[0]
                    first_id = str(workflow.uuid4())
                    self._stream_ts = await workflow.execute_activity(
                        start_slack_agent_design_stream,
                        StartSlackAgentDesignStreamInput(
                            slack_thread_context=input.slack_thread_context,
                            first_task_id=first_id,
                            first_task_title=first_step.title,
                            first_task_details=first_step.details,
                        ),
                        start_to_close_timeout=timedelta(seconds=10),
                        retry_policy=RetryPolicy(maximum_attempts=3),
                    )
                    if self._stream_ts is None:
                        return
                    self._current_task_id = first_id
                    self._current_task_title = first_step.title
                    self._current_task_details = first_step.details
                    remaining = steps[1:]
                    if remaining or markdown:
                        await workflow.execute_activity(
                            append_slack_agent_design_step,
                            AppendSlackAgentDesignStepInput(
                                slack_thread_context=input.slack_thread_context,
                                ts=self._stream_ts,
                                task_updates=self._build_transition_chunks(remaining),
                                markdown_text=markdown or None,
                            ),
                            start_to_close_timeout=timedelta(seconds=10),
                            retry_policy=RetryPolicy(maximum_attempts=3),
                        )
                    continue

                await workflow.execute_activity(
                    append_slack_agent_design_step,
                    AppendSlackAgentDesignStepInput(
                        slack_thread_context=input.slack_thread_context,
                        ts=self._stream_ts,
                        task_updates=self._build_transition_chunks(steps),
                        markdown_text=markdown or None,
                    ),
                    start_to_close_timeout=timedelta(seconds=10),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
        finally:
            if self._stream_ts is not None:
                await workflow.execute_activity(
                    stop_slack_agent_design_stream,
                    StopSlackAgentDesignStreamInput(
                        slack_thread_context=input.slack_thread_context,
                        ts=self._stream_ts,
                        complete_task_id=self._current_task_id,
                        complete_task_title=self._current_task_title,
                        complete_task_details=self._current_task_details,
                    ),
                    start_to_close_timeout=timedelta(seconds=10),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
