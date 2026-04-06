from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypeVar

from pydantic import BaseModel

from products.tasks.backend.models import Task, TaskRun

if TYPE_CHECKING:
    from temporalio.client import WorkflowHandle
from posthog.temporal.common.client import async_connect

from products.tasks.backend.services.custom_prompt_executor import extract_json_from_text
from products.tasks.backend.services.custom_prompt_runner import (
    CustomPromptSandboxContext,
    OutputFn,
    _create_task_and_trigger,
    _poll_for_turn,
)
from products.tasks.backend.temporal.process_task.workflow import ProcessTaskWorkflow

logger = logging.getLogger(__name__)

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
        branch: str = "master",
        step_name: str = "",
        verbose: bool = False,
        output_fn: OutputFn = None,
        origin_product: str | None = None,
        signal_report_id: str | None = None,
    ) -> tuple[MultiTurnSession, _ModelT]:
        """Start a multi-turn sandbox session and wait for the first response."""
        task, task_run = await _create_task_and_trigger(
            prompt,
            context,
            branch,
            step_name,
            origin_product=origin_product,
            signal_report_id=signal_report_id,
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
        last_message, _, session.log_lines_seen, session.printed_lines = await _poll_for_turn(
            task_run, verbose=verbose, output_fn=output_fn, workflow_handle=workflow_handle
        )
        parsed = cls._parse_and_validate(last_message, model, label="initial turn")
        return session, parsed

    async def send_followup(
        self,
        message: str,
        model: type[_ModelT],
        *,
        label: str = "",
    ) -> _ModelT:
        """Send a follow-up message and wait for the agent's next response."""
        if not self._workflow_handle:
            raise RuntimeError("Workflow handle is not available in this session.")
        await self._workflow_handle.signal(ProcessTaskWorkflow.send_followup_message, message)
        logger.info("multi_turn: sent followup run=%s label=%s", self.task_run.id, label)
        last_message, _, self.log_lines_seen, self.printed_lines = await _poll_for_turn(
            self.task_run,
            skip_lines=self.log_lines_seen,
            printed_lines=self.printed_lines,
            verbose=self.verbose,
            output_fn=self.output_fn,
            workflow_handle=self._workflow_handle,
        )
        parsed = self._parse_and_validate(last_message, model, label=label or "followup")
        return parsed

    @staticmethod
    def _parse_and_validate(text: str, model: type[_ModelT], label: str) -> _ModelT:
        """Extract JSON from agent text and validate against a Pydantic model."""
        json_data = extract_json_from_text(text=text, label=label)
        return model.model_validate(json_data)

    async def end(self) -> None:
        """Signal the workflow to shut down cleanly."""
        if not self._workflow_handle:
            raise RuntimeError("Workflow handle is not available in this session.")
        try:
            await self._workflow_handle.signal(ProcessTaskWorkflow.complete_task, args=["completed", None])
            logger.info("multi_turn: ended session run=%s", self.task_run.id)
        except Exception:
            logger.warning("multi_turn: failed to signal completion run=%s", self.task_run.id, exc_info=True)
