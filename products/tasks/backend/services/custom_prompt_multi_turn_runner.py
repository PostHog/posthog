from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypeVar

from pydantic import BaseModel, ValidationError

from products.tasks.backend.models import Task, TaskRun

if TYPE_CHECKING:
    from temporalio.client import WorkflowHandle
from posthog.temporal.common.client import async_connect

from products.tasks.backend.services.custom_prompt_internals import (
    AgentResponseFormatError,
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


def _build_format_retry_nudge(error: Exception) -> str:
    """Build a corrective nudge that feeds the validation error back to the agent.

    Used when the agent's response parses as JSON but doesn't satisfy the target
    Pydantic schema — re-sends the prompt with a short suffix explaining what
    failed so the agent can re-emit a well-formed object.
    """
    return (
        "\n\nYour previous response did not match the required JSON schema.\n"
        f"Validation error: {error}\n\n"
        "Please respond again with a single, valid JSON object that matches the schema above."
    )


_ModelT = TypeVar("_ModelT", bound=BaseModel)


@dataclass
class MultiTurnSession:
    task: Task
    task_run: TaskRun
    log_lines_seen: int = 0
    printed_lines: int = 0
    verbose: bool = False
    output_fn: OutputFn = field(default=None)
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
        internal: bool = False,
    ) -> tuple[MultiTurnSession, _ModelT]:
        """Start a multi-turn sandbox session and wait for the first response."""
        task, task_run = await create_task_and_trigger(
            prompt,
            context,
            branch,
            step_name,
            origin_product=origin_product,
            signal_report_id=signal_report_id,
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
            _workflow_handle=workflow_handle,
        )
        started_at = time.monotonic()
        last_message, _, session.log_lines_seen, session.printed_lines = await poll_for_turn(
            task_run, verbose=verbose, output_fn=output_fn, workflow_handle=workflow_handle
        )
        logger.info(
            "multi_turn: initial turn completed run=%s duration=%.2fs",
            task_run.id,
            time.monotonic() - started_at,
        )
        try:
            parsed = cls._parse_and_validate(last_message, model, label="initial turn")
        except AgentResponseFormatError as e:
            # The initial response parsed as JSON but didn't match the target schema.
            # Send a corrective followup so the agent can re-emit a well-formed object,
            # matching the empty-end_turn retry path. send_followup applies its own
            # single-retry budget, so the agent gets one more chance on the followup.
            logger.warning(
                "multi_turn: initial turn validation failed run=%s — retrying with corrective nudge",
                task_run.id,
                exc_info=True,
            )
            if output_fn:
                output_fn("Initial response did not match the schema, retrying with corrective nudge...")
            parsed = await session.send_followup(
                _build_format_retry_nudge(e.validation_error),
                model,
                label="initial_turn_format_retry",
            )
        return session, parsed

    async def send_followup(
        self,
        message: str,
        model: type[_ModelT],
        *,
        label: str = "",
    ) -> _ModelT:
        """Send a follow-up message and wait for the agent's next response.

        Applies a single retry budget covering both failure modes:

        - Empty end_turn (no agent message) — retry with the empty-turn nudge.
        - Schema validation failure — retry with a corrective nudge that includes
          the validation error so the agent can re-emit a well-formed object.

        On the retry attempt, an empty end_turn still raises ``EmptyAgentTurnError``
        and a validation failure still raises ``AgentResponseFormatError`` — the
        retry budget is one attempt, not unbounded.
        """
        if not self._workflow_handle:
            raise RuntimeError("Workflow handle is not available in this session.")
        started_at = time.monotonic()

        # Attempt 1: send the prompt, poll for the response, then try to parse it.
        last_message = await self._send_and_poll(message, label=label, attempt=1)
        if last_message is not None:
            try:
                parsed = self._parse_and_validate(last_message, model, label=label or "followup")
            except AgentResponseFormatError as e:
                # Schema validation failed — fall through to a corrective retry.
                logger.warning(
                    "multi_turn: followup validation failed run=%s label=%s — will retry with corrective nudge",
                    self.task_run.id,
                    label,
                    exc_info=True,
                )
                if self.output_fn:
                    self.output_fn(f"Agent response did not match the schema for {label or 'followup'}, retrying...")
                retry_message = message + _build_format_retry_nudge(e.validation_error)
            else:
                logger.info(
                    "multi_turn: followup completed run=%s label=%s duration=%.2fs",
                    self.task_run.id,
                    label,
                    time.monotonic() - started_at,
                )
                return parsed
        else:
            # Empty end_turn — resend with a small nudge to keep the agent going.
            retry_message = message + _EMPTY_TURN_RETRY_NUDGE

        # Attempt 2: retry once. Empty end_turns still raise EmptyAgentTurnError,
        # format errors still propagate as AgentResponseFormatError.
        last_message = await self._send_and_poll(retry_message, label=label, attempt=2)
        if last_message is None:
            raise EmptyAgentTurnError(
                f"Agent produced empty end_turn twice for run={self.task_run.id} label={label}",
                total_lines=self.log_lines_seen,
                printed_lines=self.printed_lines,
            )
        parsed = self._parse_and_validate(last_message, model, label=label or "followup")
        logger.info(
            "multi_turn: followup completed run=%s label=%s duration=%.2fs",
            self.task_run.id,
            label,
            time.monotonic() - started_at,
        )
        return parsed

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
        """Extract JSON from agent text and validate against a Pydantic model.

        Raises ``AgentResponseFormatError`` (carrying the underlying validation
        exception) when the agent's text parses as JSON but doesn't satisfy the
        target schema, so callers can recover with a single corrective-nudge
        retry instead of failing the whole activity.
        """
        json_data = extract_json_from_text(text=text, label=label)
        try:
            return model.model_validate(json_data)
        except ValidationError as e:
            raise AgentResponseFormatError(
                f"Agent response failed validation for {label}: {e}",
                validation_error=e,
            ) from e

    async def end(self) -> None:
        """Signal the workflow to shut down cleanly."""
        if not self._workflow_handle:
            raise RuntimeError("Workflow handle is not available in this session.")
        try:
            await self._workflow_handle.signal(ProcessTaskWorkflow.complete_task, args=["completed", None])
            logger.info("multi_turn: ended session run=%s", self.task_run.id)
        except Exception:
            logger.warning("multi_turn: failed to signal completion run=%s", self.task_run.id, exc_info=True)
