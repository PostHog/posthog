"""Per-turn child of ProcessTaskWorkflow.

Two phases in a single chat.startStream lifecycle:

Phase 1 (before the first tool call): text_deltas stream as markdown_text
chunks — native Slack streaming animation. The stream is opened lazily on
the first signal we can act on.

Phase 2 (after the first tool call): text_deltas buffer between tool calls
and surface as 💭 steps in the plan block, sandwiched between the tool
call steps. This is the plan-block-driven mode.

On turn_completed the last narrative burst (post-last-tool-call, or the
only content in phase 1) streams as the final markdown_text and the
stream closes with the trailing @-mention.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from .activities.slack_agent_design import (
        AppendSlackAgentDesignStepsInput,
        StartSlackAgentDesignStreamInput,
        StopSlackAgentDesignStreamInput,
        TaskUpdateChunk,
        append_slack_agent_design_steps,
        start_slack_agent_design_stream,
        stop_slack_agent_design_stream,
    )


STATUS_DEBOUNCE_SECONDS = 1.0
STATUS_MIN_INTERVAL_SECONDS = 2.0
TURN_IDLE_TIMEOUT_MINUTES = 5
_STEP_FIELD_LIMIT = 256
_NARRATIVE_STEP_TITLE = "💭"


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
        self._pending_steps: list[PendingStep] = []
        # Narrative buffer. In phase 1 this is streamed and reset on each flush.
        # In phase 2 it accumulates until the next tool call promotes it to a
        # 💭 step, or until turn_completed streams it as the final answer.
        self._current_narrative: str = ""
        self._has_seen_tool_call: bool = False
        self._stream_ts: Optional[str] = None
        self._current_task_id: Optional[str] = None
        self._current_task_title: Optional[str] = None
        self._current_task_details: Optional[str] = None
        self._last_dispatched_at: float = 0.0
        self._turn_complete: bool = False

    @workflow.signal
    async def agent_status_update(self, payload: dict[str, Any] | str) -> None:
        """New tool call → transition to phase 2 and queue steps."""
        if isinstance(payload, str):
            title = payload
            details = None
            if not title:
                return
        else:
            raw_title = payload.get("title") or payload.get("text")
            if not isinstance(raw_title, str) or not raw_title:
                return
            title = raw_title
            details_raw = payload.get("details")
            details = details_raw if isinstance(details_raw, str) and details_raw else None

        # Any pending narrative becomes a 💭 step preceding the tool call step.
        # In phase 1 → phase 2 transition, this converts the last (unstreamed)
        # narrative burst into a step rather than losing it.
        narrative = self._current_narrative.strip()
        if narrative:
            self._pending_steps.append(PendingStep(title=_NARRATIVE_STEP_TITLE, details=narrative[:_STEP_FIELD_LIMIT]))
            self._current_narrative = ""

        self._has_seen_tool_call = True
        self._pending_steps.append(PendingStep(title=title, details=details))

    @workflow.signal
    async def agent_text_delta(self, text: str) -> None:
        if isinstance(text, str) and text:
            self._current_narrative += text

    @workflow.signal
    async def complete_turn(self) -> None:
        self._turn_complete = True

    def _build_transition_chunks(self, steps: list[PendingStep]) -> list[TaskUpdateChunk]:
        """Previous step → complete, intermediates → complete, last → in_progress.
        Mutates ``self._current_*`` to point at the new in-progress step."""
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

    def _has_pending(self) -> bool:
        if not self._has_seen_tool_call:
            return bool(self._current_narrative)
        return bool(self._pending_steps)

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

                if self._turn_complete:
                    break  # type: ignore[unreachable]

                await workflow.sleep(STATUS_DEBOUNCE_SECONDS)

                elapsed = workflow.now().timestamp() - self._last_dispatched_at
                if elapsed < STATUS_MIN_INTERVAL_SECONDS:
                    await workflow.sleep(STATUS_MIN_INTERVAL_SECONDS - elapsed)

                if not self._has_seen_tool_call:
                    # Phase 1: stream narrative as markdown_text.
                    to_stream = self._current_narrative
                    if not to_stream:
                        continue
                    self._current_narrative = ""
                    self._last_dispatched_at = workflow.now().timestamp()

                    if self._stream_ts is None:
                        self._stream_ts = await workflow.execute_activity(
                            start_slack_agent_design_stream,
                            StartSlackAgentDesignStreamInput(
                                slack_thread_context=input.slack_thread_context,
                                first_markdown_text=to_stream,
                            ),
                            start_to_close_timeout=timedelta(seconds=10),
                            retry_policy=RetryPolicy(maximum_attempts=3),
                        )
                        if self._stream_ts is None:
                            return
                    else:
                        await workflow.execute_activity(
                            append_slack_agent_design_steps,
                            AppendSlackAgentDesignStepsInput(
                                slack_thread_context=input.slack_thread_context,
                                ts=self._stream_ts,
                                markdown_text=to_stream,
                            ),
                            start_to_close_timeout=timedelta(seconds=10),
                            retry_policy=RetryPolicy(maximum_attempts=3),
                        )
                    continue

                # Phase 2: flush queued steps into the plan block.
                steps = self._pending_steps
                self._pending_steps = []
                if not steps:
                    continue

                self._last_dispatched_at = workflow.now().timestamp()

                if self._stream_ts is None:
                    first = steps[0]
                    first_id = str(workflow.uuid4())
                    self._stream_ts = await workflow.execute_activity(
                        start_slack_agent_design_stream,
                        StartSlackAgentDesignStreamInput(
                            slack_thread_context=input.slack_thread_context,
                            first_task_id=first_id,
                            first_task_title=first.title,
                            first_task_details=first.details,
                        ),
                        start_to_close_timeout=timedelta(seconds=10),
                        retry_policy=RetryPolicy(maximum_attempts=3),
                    )
                    if self._stream_ts is None:
                        return
                    self._current_task_id = first_id
                    self._current_task_title = first.title
                    self._current_task_details = first.details
                    remaining = steps[1:]
                    if remaining:
                        await workflow.execute_activity(
                            append_slack_agent_design_steps,
                            AppendSlackAgentDesignStepsInput(
                                slack_thread_context=input.slack_thread_context,
                                ts=self._stream_ts,
                                task_updates=self._build_transition_chunks(remaining),
                            ),
                            start_to_close_timeout=timedelta(seconds=10),
                            retry_policy=RetryPolicy(maximum_attempts=3),
                        )
                    continue

                await workflow.execute_activity(
                    append_slack_agent_design_steps,
                    AppendSlackAgentDesignStepsInput(
                        slack_thread_context=input.slack_thread_context,
                        ts=self._stream_ts,
                        task_updates=self._build_transition_chunks(steps),
                    ),
                    start_to_close_timeout=timedelta(seconds=10),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
        finally:
            final_answer = self._current_narrative.strip()
            # If turn_completed beat the first flush, open the stream now with
            # the final answer as the seed. Keeps the streaming lifecycle
            # consistent — no chat.postMessage fallback that would flicker
            # against Slack's stream animation.
            final_for_stop: Optional[str] = final_answer or None
            if self._stream_ts is None and final_answer:
                self._stream_ts = await workflow.execute_activity(
                    start_slack_agent_design_stream,
                    StartSlackAgentDesignStreamInput(
                        slack_thread_context=input.slack_thread_context,
                        first_markdown_text=final_answer,
                    ),
                    start_to_close_timeout=timedelta(seconds=10),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                # Already streamed as the opening chunk — don't re-emit in stop.
                final_for_stop = None
            if self._stream_ts is not None:
                await workflow.execute_activity(
                    stop_slack_agent_design_stream,
                    StopSlackAgentDesignStreamInput(
                        slack_thread_context=input.slack_thread_context,
                        ts=self._stream_ts,
                        complete_task_id=self._current_task_id,
                        complete_task_title=self._current_task_title,
                        complete_task_details=self._current_task_details,
                        final_markdown=final_for_stop,
                    ),
                    start_to_close_timeout=timedelta(seconds=10),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
