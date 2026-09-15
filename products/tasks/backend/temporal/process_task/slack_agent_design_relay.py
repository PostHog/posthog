"""Per-turn child of ProcessTaskWorkflow.

Three stream surfaces, chosen by ``stream_mode`` on the input:

- ``timeline`` — narrative streams as markdown_text; consecutive tool calls share
  one live task card interleaved in arrival order (Slack's
  ``task_display_mode="timeline"``). The card's details grow one line per call
  (tool name, capped args, the outcome glued on when it arrives), the title
  counts the calls, and narrative closes the card — complete, or error when any
  call in it failed.
- ``final_only`` — nothing streams while the turn runs; when the turn completes
  the final answer posts in one batch through the same start/stop lifecycle.
- unset — the legacy plan-block surface, kept for relays whose start was
  recorded before ``stream_mode`` existed. Two phases in a single
  chat.startStream lifecycle: before the first tool call, text_deltas stream as
  markdown_text; after it, they buffer between tool calls and surface as 💭
  steps in the plan block. On turn_completed the last narrative burst streams
  as the final markdown_text.

Whatever the surface, the stream closes with the trailing @-mention and the
provenance footer.
"""

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Optional, Union

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from products.tasks.backend.temporal.slack_relay.object_tags import split_incomplete_tag_suffix

    from .activities.slack_agent_design import (
        STREAM_MODE_FINAL_ONLY,
        STREAM_MODE_TIMELINE,
        AppendSlackAgentDesignStepsInput,
        StartSlackAgentDesignStreamInput,
        StopSlackAgentDesignStreamInput,
        StreamChunk,
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
# Per-line caps inside a burst card. Each delta chunk must stay under Slack's
# 256-char task_update limit, and appends cannot be retracted, so the line cap
# is preemptive — the title keeps counting past it.
_CARD_ARGS_LIMIT = 140
_CARD_RESULT_LIMIT = 80
_CARD_MAX_LINES = 15

_ACTIVITY_OPTIONS: dict[str, Any] = {
    "start_to_close_timeout": timedelta(seconds=10),
    "retry_policy": RetryPolicy(maximum_attempts=3),
}


@dataclass
class PendingStep:
    title: str
    details: Optional[str]
    tool_call_id: Optional[str] = None


@dataclass
class QueuedText:
    """A run of narrative between two tool calls, grown in place as deltas arrive."""

    text: str


@dataclass
class QueuedToolResult:
    """A finished tool call's outcome, to annotate the open burst card."""

    tool_call_id: str
    output: Optional[str]
    failed: bool


@dataclass
class BurstCard:
    """The live card a run of consecutive tool calls shares.

    Slack appends a same-id task_update's details to the card rather than
    replacing them, so every chunk carries only its delta: one new line per
    call, the outcome glued onto that line when it arrives."""

    card_id: str
    title_base: str
    count: int = 0
    uniform: bool = True
    lines: int = 0
    any_failed: bool = False
    # Calls that own a line in the card; a result for a call without one (the
    # line cap suppressed it, or the burst closed) appends nothing.
    line_tool_ids: set[str] = field(default_factory=set)

    @property
    def display_title(self) -> str:
        if not self.uniform:
            return f"{self.count} tool calls"
        return self.title_base if self.count == 1 else f"{self.title_base} ({self.count})"


@dataclass
class SlackAgentDesignRelayInput:
    slack_thread_context: dict[str, Any]
    # Trailing and defaulted so a relay already in flight decodes it as absent and
    # simply closes without a footer, rather than failing replay.
    run_id: Optional[str] = None
    # None selects the legacy plan-block surface, which is what relays recorded
    # before this field existed replay.
    stream_mode: Optional[str] = None


@workflow.defn(name="slack-agent-design-relay")
class SlackAgentDesignRelayWorkflow(PostHogWorkflow):
    def __init__(self) -> None:
        self._pending_steps: list[PendingStep] = []
        # Narrative buffer. In plan phase 1 this is streamed and reset on each flush.
        # In plan phase 2 it accumulates until the next tool call promotes it to a
        # 💭 step, or until turn_completed streams it as the final answer. The
        # final_only surface reads it the same way: cleared on each tool call, so at
        # turn end it holds only the answer.
        self._current_narrative: str = ""
        self._has_seen_tool_call: bool = False
        self._stream_ts: Optional[str] = None
        self._current_task_id: Optional[str] = None
        self._current_task_title: Optional[str] = None
        self._current_task_details: Optional[str] = None
        self._last_dispatched_at: float = 0.0
        # Length of a narrative held back whole (an unfinished tag); a flush waits for it to grow.
        self._held_length: int = 0
        self._turn_complete: bool = False
        # Gateway trace id of the turn this relay is streaming, as ``complete_turn``
        # reports it. The closing reply carries the thumbs, so this is what a rating on
        # them names.
        self._trace_id: Optional[str] = None
        # Timeline surface: prose and steps in arrival order, consumed up to
        # (_consumed, _consumed_text_offset). The offset only ever points into a
        # QueuedText at index _consumed, and only moves forward — deltas append.
        self._events: list[Union[PendingStep, QueuedText, QueuedToolResult]] = []
        self._consumed: int = 0
        self._consumed_text_offset: int = 0
        # Bumped by every content signal, so the final_only wait can tell live
        # silence from a turn that is still producing.
        self._signal_seq: int = 0
        # The open burst card: consecutive tool calls update one live card (count in
        # the title, the current call in details, the latest outcome in output).
        # Narrative closes it — complete, or error when any call in it failed.
        self._burst: Optional[BurstCard] = None

    @workflow.signal
    async def agent_status_update(self, payload: dict[str, Any] | str) -> None:
        """New tool call → queue a step (and on the plan surface, transition to phase 2).
        A tool_result payload only annotates the timeline card's line for that call."""
        tool_call_id: Optional[str] = None
        if isinstance(payload, str):
            title = payload
            details = None
            if not title:
                return
        else:
            if payload.get("kind") == "tool_result":
                result_id = payload.get("tool_call_id")
                if isinstance(result_id, str) and result_id:
                    output_raw = payload.get("output")
                    self._events.append(
                        QueuedToolResult(
                            tool_call_id=result_id,
                            output=output_raw if isinstance(output_raw, str) and output_raw else None,
                            failed=bool(payload.get("failed")),
                        )
                    )
                    self._signal_seq += 1
                return
            raw_title = payload.get("title") or payload.get("text")
            if not isinstance(raw_title, str) or not raw_title:
                return
            title = raw_title
            details_raw = payload.get("details")
            details = details_raw if isinstance(details_raw, str) and details_raw else None
            id_raw = payload.get("tool_call_id")
            tool_call_id = id_raw if isinstance(id_raw, str) and id_raw else None

        # Any pending narrative becomes a 💭 step preceding the tool call step.
        # In phase 1 → phase 2 transition, this converts the last (unstreamed)
        # narrative burst into a step rather than losing it.
        narrative = self._current_narrative.strip()
        if narrative:
            self._pending_steps.append(PendingStep(title=_NARRATIVE_STEP_TITLE, details=narrative[:_STEP_FIELD_LIMIT]))
            self._current_narrative = ""

        self._has_seen_tool_call = True
        self._pending_steps.append(PendingStep(title=title, details=details))
        self._events.append(PendingStep(title=title, details=details, tool_call_id=tool_call_id))
        self._signal_seq += 1

    @workflow.signal
    async def agent_text_delta(self, text: str) -> None:
        if isinstance(text, str) and text:
            self._current_narrative += text
            tail = self._events[-1] if self._events else None
            if isinstance(tail, QueuedText):
                tail.text += text
            else:
                self._events.append(QueuedText(text=text))
            self._signal_seq += 1

    @workflow.signal
    async def complete_turn(self, trace_id: str | None = None) -> None:
        self._turn_complete = True
        self._trace_id = trace_id

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
        if input.stream_mode == STREAM_MODE_TIMELINE:
            await self._run_timeline(input)
        elif input.stream_mode == STREAM_MODE_FINAL_ONLY:
            await self._run_final_only(input)
        else:
            await self._run_plan(input)

    # ─── Timeline surface ───

    def _has_unsent_events(self) -> bool:
        if self._consumed >= len(self._events):
            return False
        if self._consumed == len(self._events) - 1:
            tail = self._events[self._consumed]
            if isinstance(tail, QueuedText):
                return len(tail.text) > self._consumed_text_offset
        return True

    def _timeline_marker(self) -> tuple[int, int]:
        """Changes whenever content arrives, so a hold on an unfinished tag can wait
        for growth rather than re-flushing the same unsendable suffix."""
        tail = self._events[-1] if self._events else None
        return (len(self._events), len(tail.text) if isinstance(tail, QueuedText) else -1)

    def _burst_chunk(self, status: str, details_delta: Optional[str]) -> StreamChunk:
        assert self._burst is not None
        return StreamChunk(
            task_update=TaskUpdateChunk(
                id=self._burst.card_id,
                title=self._burst.display_title,
                status=status,
                details=details_delta,
            )
        )

    def _card_chunks_for_step(self, step: PendingStep) -> list[StreamChunk]:
        """Fold the tool call into the open burst card, or open a new one.

        The card is the burst's single timeline point. Its details grow one line
        per call (tool name plus capped args); the title counts every call, even
        the ones past the line cap."""
        if self._burst is None:
            self._burst = BurstCard(card_id=str(workflow.uuid4()), title_base=step.title)
        elif step.title != self._burst.title_base:
            self._burst.uniform = False
        self._burst.count += 1
        details_delta: Optional[str] = None
        if self._burst.lines < _CARD_MAX_LINES:
            line = f"{step.title}: {step.details[:_CARD_ARGS_LIMIT]}" if step.details else step.title
            details_delta = f"\n{line}" if self._burst.lines else line
            self._burst.lines += 1
            if step.tool_call_id:
                self._burst.line_tool_ids.add(step.tool_call_id)
        return [self._burst_chunk("in_progress", details_delta)]

    def _card_chunk_for_result(self, result: QueuedToolResult) -> Optional[StreamChunk]:
        """Glue the outcome onto its call's line in the open burst card.

        Results arrive before the next call in a sequential agent, so the append
        lands on the line the call wrote. One for a closed burst, or for a call
        past the line cap, changes nothing visible."""
        if self._burst is None:
            return None
        if result.failed:
            self._burst.any_failed = True
        if result.tool_call_id not in self._burst.line_tool_ids:
            return None
        self._burst.line_tool_ids.discard(result.tool_call_id)
        preview = (result.output or "")[:_CARD_RESULT_LIMIT]
        if result.failed:
            delta = f" ✗ {preview}" if preview else " ✗ failed"
        elif preview:
            delta = f" → {preview}"
        else:
            return None
        return self._burst_chunk("in_progress", delta)

    def _close_burst_chunk(self) -> Optional[StreamChunk]:
        """Close the open burst card — error when any call in it failed. Calls the
        line cap suppressed surface as one trailing count line."""
        if self._burst is None:
            return None
        overflow = self._burst.count - self._burst.lines
        details_delta = f"\n…+{overflow} more" if overflow > 0 else None
        chunk = self._burst_chunk("error" if self._burst.any_failed else "complete", details_delta)
        self._burst = None
        return chunk

    def _collect_timeline_chunks(self, final: bool) -> list[StreamChunk]:
        """Consume unsent events into ordered chunks, advancing the consumed pointer.

        Mid-turn the trailing prose is held back at an unfinished object tag or code
        fence so it never posts as raw XML; at turn end (``final``) the text is whole
        and goes out as written.
        """
        chunks: list[StreamChunk] = []

        def _push_card(chunk: Optional[StreamChunk]) -> None:
            # Every card chunk is an append-delta, so nothing coalesces — dropping
            # one would lose its line from the card.
            if chunk is not None:
                chunks.append(chunk)

        i = self._consumed
        offset = self._consumed_text_offset
        while i < len(self._events):
            item = self._events[i]
            if isinstance(item, QueuedToolResult):
                _push_card(self._card_chunk_for_result(item))
                i += 1
                offset = 0
                continue
            if isinstance(item, PendingStep):
                for chunk in self._card_chunks_for_step(item):
                    _push_card(chunk)
                i += 1
                offset = 0
                continue
            text = item.text[offset:]
            if i == len(self._events) - 1 and not final:
                split = split_incomplete_tag_suffix(text)
                if split.sendable:
                    _push_card(self._close_burst_chunk())
                    chunks.append(StreamChunk(markdown_text=split.sendable))
                    offset += len(split.sendable)
                break
            if text:
                _push_card(self._close_burst_chunk())
                chunks.append(StreamChunk(markdown_text=text))
            i += 1
            offset = 0
        if final:
            _push_card(self._close_burst_chunk())
        self._consumed = i
        self._consumed_text_offset = offset
        return chunks

    async def _dispatch_timeline_chunks(self, input: SlackAgentDesignRelayInput, chunks: list[StreamChunk]) -> bool:
        """Open the stream with the first flush, append after. False when the open failed."""
        if self._stream_ts is None:
            self._stream_ts = await workflow.execute_activity(
                start_slack_agent_design_stream,
                StartSlackAgentDesignStreamInput(
                    slack_thread_context=input.slack_thread_context,
                    ordered_chunks=chunks,
                    # Bursts render as steps of one plan rail; "timeline" names the
                    # relay's interleaving surface, not Slack's display mode.
                    task_display_mode="plan",
                    run_id=input.run_id,
                ),
                **_ACTIVITY_OPTIONS,
            )
            return self._stream_ts is not None
        await workflow.execute_activity(
            append_slack_agent_design_steps,
            AppendSlackAgentDesignStepsInput(
                slack_thread_context=input.slack_thread_context,
                ts=self._stream_ts,
                ordered_chunks=chunks,
            ),
            **_ACTIVITY_OPTIONS,
        )
        return True

    async def _run_timeline(self, input: SlackAgentDesignRelayInput) -> None:
        try:
            while not self._turn_complete:
                try:
                    await workflow.wait_condition(
                        lambda: self._has_unsent_events() or self._turn_complete,
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

                chunks = self._collect_timeline_chunks(final=False)
                if not chunks:
                    # The only unsent content is an unfinished tag suffix — wait for
                    # it to grow into something sendable, or for the turn to end.
                    marker = self._timeline_marker()

                    def _grew(held: tuple[int, int] = marker) -> bool:
                        return self._timeline_marker() != held or self._turn_complete

                    try:
                        await workflow.wait_condition(
                            _grew,
                            timeout=timedelta(minutes=TURN_IDLE_TIMEOUT_MINUTES),
                        )
                    except TimeoutError:
                        workflow.logger.warning(
                            "slack_app_agent_design_relay_idle_timeout",
                            extra={"workflow_id": workflow.info().workflow_id},
                        )
                        return
                    continue

                self._last_dispatched_at = workflow.now().timestamp()
                if not await self._dispatch_timeline_chunks(input, chunks):
                    return
        finally:
            final_chunks = self._collect_timeline_chunks(final=True)
            if final_chunks:
                await self._dispatch_timeline_chunks(input, final_chunks)
            if self._stream_ts is not None:
                await self._stop_stream(input)

    # ─── Final-only surface ───

    async def _run_final_only(self, input: SlackAgentDesignRelayInput) -> None:
        try:
            while not self._turn_complete:
                seen = self._signal_seq

                def _woke(last: int = seen) -> bool:
                    return self._turn_complete or self._signal_seq != last

                try:
                    # Deltas and steps reset the idle clock, so a long turn that is
                    # still producing never times out; only true silence does.
                    await workflow.wait_condition(
                        _woke,
                        timeout=timedelta(minutes=TURN_IDLE_TIMEOUT_MINUTES),
                    )
                except TimeoutError:
                    workflow.logger.warning(
                        "slack_app_agent_design_relay_idle_timeout",
                        extra={"workflow_id": workflow.info().workflow_id},
                    )
                    return
        finally:
            final_answer = self._current_narrative.strip()
            if final_answer:
                self._stream_ts = await workflow.execute_activity(
                    start_slack_agent_design_stream,
                    StartSlackAgentDesignStreamInput(
                        slack_thread_context=input.slack_thread_context,
                        first_markdown_text=final_answer,
                        run_id=input.run_id,
                    ),
                    **_ACTIVITY_OPTIONS,
                )
            if self._stream_ts is not None:
                await self._stop_stream(input)

    async def _stop_stream(self, input: SlackAgentDesignRelayInput, final_markdown: Optional[str] = None) -> None:
        assert self._stream_ts is not None
        await workflow.execute_activity(
            stop_slack_agent_design_stream,
            StopSlackAgentDesignStreamInput(
                slack_thread_context=input.slack_thread_context,
                ts=self._stream_ts,
                complete_task_id=self._current_task_id,
                complete_task_title=self._current_task_title,
                complete_task_details=self._current_task_details,
                final_markdown=final_markdown,
                run_id=input.run_id,
                trace_id=self._trace_id,
            ),
            **_ACTIVITY_OPTIONS,
        )

    # ─── Legacy plan surface ───

    async def _run_plan(self, input: SlackAgentDesignRelayInput) -> None:
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
                    if not self._current_narrative:
                        continue
                    if workflow.patched("slack-agent-design-hold-split-tags-2026-08"):
                        # An object tag or code fence cut by the flush boundary would post as
                        # raw XML; keep its start for the next flush. Patched because a history
                        # recorded before this branch cleared the narrative here and then waited.
                        split = split_incomplete_tag_suffix(self._current_narrative)
                        if not split.sendable:
                            self._held_length = len(self._current_narrative)
                            try:
                                await workflow.wait_condition(
                                    lambda: len(self._current_narrative) != self._held_length or self._turn_complete,
                                    timeout=timedelta(minutes=TURN_IDLE_TIMEOUT_MINUTES),
                                )
                            except TimeoutError:
                                workflow.logger.warning(
                                    "slack_app_agent_design_relay_idle_timeout",
                                    extra={"workflow_id": workflow.info().workflow_id},
                                )
                                return
                            continue
                        to_stream = split.sendable
                        self._current_narrative = split.held
                    else:
                        to_stream = self._current_narrative
                        self._current_narrative = ""
                    self._last_dispatched_at = workflow.now().timestamp()

                    if self._stream_ts is None:
                        self._stream_ts = await workflow.execute_activity(
                            start_slack_agent_design_stream,
                            StartSlackAgentDesignStreamInput(
                                slack_thread_context=input.slack_thread_context,
                                first_markdown_text=to_stream,
                            ),
                            **_ACTIVITY_OPTIONS,
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
                            **_ACTIVITY_OPTIONS,
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
                        **_ACTIVITY_OPTIONS,
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
                            **_ACTIVITY_OPTIONS,
                        )
                    continue

                await workflow.execute_activity(
                    append_slack_agent_design_steps,
                    AppendSlackAgentDesignStepsInput(
                        slack_thread_context=input.slack_thread_context,
                        ts=self._stream_ts,
                        task_updates=self._build_transition_chunks(steps),
                    ),
                    **_ACTIVITY_OPTIONS,
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
                    **_ACTIVITY_OPTIONS,
                )
                # Already streamed as the opening chunk — don't re-emit in stop.
                final_for_stop = None
            if self._stream_ts is not None:
                await self._stop_stream(input, final_markdown=final_for_stop)
