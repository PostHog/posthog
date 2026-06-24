from __future__ import annotations

import time
import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypeVar

from pydantic import BaseModel

from products.tasks.backend.models import Task, TaskRun

if TYPE_CHECKING:
    from temporalio.client import WorkflowHandle
from posthog.temporal.common.client import async_connect

from products.tasks.backend.logic.services.custom_prompt_internals import (
    CustomPromptSandboxContext,
    EmptyAgentTurnError,
    OutputFn,
    create_task_and_trigger,
    extract_json_from_text,
    poll_for_turn,
)
from products.tasks.backend.temporal.process_task.workflow import ProcessTaskWorkflow

logger = logging.getLogger(__name__)

# Nudge appended to a resent prompt when the agent emits an empty end_turn.
# Kept short to avoid meaningfully changing the cached prefix.
_EMPTY_TURN_RETRY_NUDGE = "\n\nPlease respond now with the JSON object matching the schema above."

_ModelT = TypeVar("_ModelT", bound=BaseModel)


@dataclass
class MultiTurnSession:
    task: Task
    task_run: TaskRun
    log_lines_seen: int = 0
    printed_lines: int = 0
    verbose: bool = False
    output_fn: OutputFn = field(default=None)
    # Per-turn poll budget. None falls back to `poll_for_turn`'s default (`MAX_POLL_SECONDS`).
    # Set this below the caller's Temporal activity `start_to_close_timeout` so the
    # dropped-finalization salvage can fire before the activity is cancelled.
    max_poll_seconds: int | None = None
    _workflow_handle: WorkflowHandle | None = field(default=None, repr=False)

    @classmethod
    async def start(
        cls,
        prompt: str,
        context: CustomPromptSandboxContext,
        model: type[_ModelT],
        *,
        branch: str | None = None,
        step_name: str = "",
        verbose: bool = False,
        output_fn: OutputFn = None,
        origin_product: Task.OriginProduct | None = None,
        signal_report_id: str | None = None,
        ai_stage: str | None = None,
        internal: bool = False,
        on_task_run_created: Callable[[TaskRun], Awaitable[None]] | None = None,
        max_poll_seconds: int | None = None,
        fallback_from_text: Callable[[str], _ModelT] | None = None,
    ) -> tuple[MultiTurnSession, _ModelT]:
        """Start a multi-turn sandbox session and wait for the first structured response.

        `on_task_run_created`, if given, is awaited once the `TaskRun` exists but
        BEFORE the agent's first turn runs. Callers that need a row linked to the
        TaskRun to be queryable during that first turn use this — e.g. the Signals
        scout creates its `SignalScoutRun` bridge here so first-turn finding emits
        can resolve the run by id instead of 404ing on a not-yet-created row.

        `max_poll_seconds` caps each turn's poll budget — see the field docstring.

        `fallback_from_text`, if given, salvages a turn whose text the agent *did*
        produce but which failed to parse/validate against `model` (empty, prose, or
        malformed JSON). Instead of failing the whole run, the callback builds a
        `model` instance from the raw end-turn text so the caller still gets a result
        to persist. Single-turn callers (e.g. the Signals scout, whose summary is a
        free-text markdown close-out) use this so an unparseable end-turn no longer
        discards the entire run and its scan-position close-out.
        """
        session, last_message = await cls.start_raw(
            prompt=prompt,
            context=context,
            branch=branch,
            step_name=step_name,
            verbose=verbose,
            output_fn=output_fn,
            origin_product=origin_product,
            signal_report_id=signal_report_id,
            ai_stage=ai_stage,
            internal=internal,
            on_task_run_created=on_task_run_created,
            max_poll_seconds=max_poll_seconds,
        )
        try:
            parsed = cls._parse_and_validate(last_message, model, label="initial turn")
        except (Exception, asyncio.CancelledError) as e:
            # Salvage path: the agent produced text but it didn't parse/validate. Rather
            # than discarding the whole run, build the model from the raw text so the caller
            # can still persist a (degraded) result. Only for real parse failures — never for
            # a Temporal cancellation (CancelledError), which must propagate and fail the run.
            if (
                fallback_from_text is not None
                and last_message is not None
                and not isinstance(e, asyncio.CancelledError)
            ):
                logger.warning(
                    "multi_turn: end-turn did not validate against %s for run=%s — salvaging raw text (%s)",
                    model.__name__,
                    session.task_run.id,
                    e,
                )
                try:
                    salvaged = fallback_from_text(last_message)
                except Exception:
                    # A raising fallback (e.g. a stricter model that also rejects the raw text)
                    # must not escape before teardown — the caller never received the session,
                    # so its own finally is unreachable and the run would wedge in IN_PROGRESS.
                    # Fall through to end the run as failed on the original parse error.
                    logger.exception("multi_turn: fallback_from_text raised for run=%s", session.task_run.id)
                else:
                    return session, salvaged
            # `start()` is about to raise so the caller never receives the session to run its
            # own teardown. End it here so a first-turn parse failure (or a Temporal timeout,
            # which raises CancelledError — a BaseException) doesn't leave the run wedged in
            # IN_PROGRESS. Shield so the failure signal still lands if the cancel re-fires.
            await asyncio.shield(session.end(status="failed", error=str(e)))
            raise
        return session, parsed

    @classmethod
    async def start_raw(
        cls,
        prompt: str,
        context: CustomPromptSandboxContext,
        *,
        branch: str | None = None,
        step_name: str = "",
        verbose: bool = False,
        output_fn: OutputFn = None,
        origin_product: Task.OriginProduct | None = None,
        signal_report_id: str | None = None,
        ai_stage: str | None = None,
        internal: bool = False,
        on_task_run_created: Callable[[TaskRun], Awaitable[None]] | None = None,
        max_poll_seconds: int | None = None,
    ) -> tuple[MultiTurnSession, str]:
        """Start a multi-turn sandbox session and return the first raw agent response.

        `on_task_run_created`, if given, is awaited once the `TaskRun` exists but
        BEFORE the agent's first turn runs — see `start` for the rationale.

        `max_poll_seconds` caps each turn's poll budget — see the field docstring.
        """
        task, task_run = await create_task_and_trigger(
            prompt,
            context,
            branch=branch,
            step_name=step_name,
            origin_product=origin_product,
            signal_report_id=signal_report_id,
            ai_stage=ai_stage,
            internal=internal,
        )
        logger.info("multi_turn: started task=%s run=%s step=%s", task.id, task_run.id, step_name or "unknown")
        # Get session's parent workflow to send heartbeats to keep the agent alive while waiting for turns
        workflow_id = TaskRun.get_workflow_id(task.id, task_run.id)
        client = await async_connect()
        workflow_handle = client.get_workflow_handle(workflow_id)
        session = cls(
            task=task,
            task_run=task_run,
            verbose=verbose,
            output_fn=output_fn,
            max_poll_seconds=max_poll_seconds,
            _workflow_handle=workflow_handle,
        )
        if on_task_run_created is not None:
            try:
                await on_task_run_created(task_run)
            except (Exception, asyncio.CancelledError) as e:
                # The TaskRun + sandbox workflow are already spawned. If the hook fails
                # (e.g. the caller's bridge-row insert hits a transient DB error), tear the
                # session down so we don't leak a running workflow/sandbox, then propagate.
                # CancelledError (BaseException, e.g. Temporal activity timeout) is caught too,
                # else the run stays IN_PROGRESS forever. Shield so the failure signal still
                # lands if the cancel re-fires mid-cleanup.
                await asyncio.shield(session.end(status="failed", error=str(e)))
                raise
        started_at = time.monotonic()
        try:
            last_message, _, session.log_lines_seen, session.printed_lines = await poll_for_turn(
                task_run,
                verbose=verbose,
                output_fn=output_fn,
                workflow_handle=workflow_handle,
                max_poll_seconds=max_poll_seconds,
            )
            logger.info(
                "multi_turn: initial turn completed run=%s duration=%.2fs",
                task_run.id,
                time.monotonic() - started_at,
            )
        except (Exception, asyncio.CancelledError) as e:
            # The session + sandbox workflow are already spawned, but `start_raw()` is about to
            # raise so the caller never receives the session to run its own teardown. End it
            # here so a first-turn poll failure (or a Temporal timeout, which raises
            # CancelledError — a BaseException) doesn't leave the run wedged in IN_PROGRESS.
            # Shield so the failure signal still lands if the cancel re-fires mid-cleanup.
            await asyncio.shield(session.end(status="failed", error=str(e)))
            raise
        return session, last_message

    async def send_followup(
        self,
        message: str,
        model: type[_ModelT],
        *,
        label: str = "",
    ) -> _ModelT:
        """Send a follow-up message and wait for the agent's next structured response."""
        last_message = await self.send_followup_raw(message, label=label)
        parsed = self._parse_and_validate(last_message, model, label=label or "followup")
        return parsed

    async def send_followup_raw(
        self,
        message: str,
        *,
        label: str = "",
    ) -> str:
        """Send a follow-up message and return the agent's raw response text."""
        if not self._workflow_handle:
            raise RuntimeError("Workflow handle is not available in this session.")
        started_at = time.monotonic()
        last_message = await self._send_and_poll(message, label=label, attempt=1)
        if last_message is None:
            # First attempt was an empty end_turn. Resend with a small nudge to keep the agent going
            retry_message = message + _EMPTY_TURN_RETRY_NUDGE
            last_message = await self._send_and_poll(retry_message, label=label, attempt=2)
            if last_message is None:
                # If the follow-up didn't help - raise
                raise EmptyAgentTurnError(
                    f"Agent produced empty end_turn twice for run={self.task_run.id} label={label}",
                    total_lines=self.log_lines_seen,
                    printed_lines=self.printed_lines,
                )
        logger.info(
            "multi_turn: followup completed run=%s label=%s duration=%.2fs",
            self.task_run.id,
            label,
            time.monotonic() - started_at,
        )
        return last_message

    async def _send_and_poll(self, message: str, *, label: str, attempt: int) -> str | None:
        """Signal the followup and poll for the next turn. Returns None on empty end_turn."""
        assert self._workflow_handle is not None
        await self._workflow_handle.signal(ProcessTaskWorkflow.send_followup_message, message)
        logger.info(
            "multi_turn: sent followup run=%s label=%s attempt=%d",
            self.task_run.id,
            label,
            attempt,
        )
        try:
            last_message, _, self.log_lines_seen, self.printed_lines = await poll_for_turn(
                self.task_run,
                skip_lines=self.log_lines_seen,
                printed_lines=self.printed_lines,
                verbose=self.verbose,
                output_fn=self.output_fn,
                workflow_handle=self._workflow_handle,
                max_poll_seconds=self.max_poll_seconds,
            )
            return last_message
        # Catch empty turns, raise everything else
        except EmptyAgentTurnError as e:
            # Advance log offsets to read from the current tail instead of re-reading the empty-turn lines
            self.log_lines_seen = e.total_lines
            self.printed_lines = e.printed_lines
            logger.exception(
                "multi_turn: empty end_turn run=%s label=%s attempt=%d — will %s",
                self.task_run.id,
                label,
                attempt,
                "retry once" if attempt == 1 else "give up",
            )
            if self.output_fn:
                action = "retrying..." if attempt == 1 else "giving up"
                self.output_fn(f"Agent returned empty response for {label or 'followup'}, {action}")
            return None

    @staticmethod
    def _parse_and_validate(text: str, model: type[_ModelT], label: str) -> _ModelT:
        """Extract JSON from agent text and validate against a Pydantic model."""
        json_data = extract_json_from_text(text=text, label=label)
        return model.model_validate(json_data)

    async def end(self, *, status: str = "completed", error: str | None = None) -> None:
        """Signal the workflow to shut down, recording `status` as the terminal TaskRun state.

        Pass `status="failed"` (with an `error` message) when ending because of an error, so
        the underlying `TaskRun` isn't recorded as `completed` — otherwise failed runs corrupt
        run-status metrics and mislead operational triage.
        """
        if not self._workflow_handle:
            raise RuntimeError("Workflow handle is not available in this session.")
        try:
            await self._workflow_handle.signal(ProcessTaskWorkflow.complete_task, args=[status, error])
            logger.info("multi_turn: ended session run=%s status=%s", self.task_run.id, status)
        except Exception:
            logger.warning("multi_turn: failed to signal completion run=%s", self.task_run.id, exc_info=True)
