import logging
from dataclasses import dataclass, field
from typing import TypeVar

from pydantic import BaseModel

from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.services.custom_prompt_executor import extract_json_from_text
from products.tasks.backend.services.custom_prompt_runner import (
    CustomPromptSandboxContext,
    OutputFn,
    _create_task_and_trigger,
    _poll_for_turn,
)

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


async def start_session(
    prompt: str,
    context: CustomPromptSandboxContext,
    model: type[_ModelT],
    *,
    branch: str = "master",
    step_name: str = "",
    verbose: bool = False,
    output_fn: OutputFn = None,
) -> tuple[MultiTurnSession, _ModelT]:
    """Start a multi-turn sandbox session and wait for the first response."""
    task, task_run = await _create_task_and_trigger(prompt, context, branch, step_name)
    logger.info("multi_turn: started task=%s run=%s step=%s", task.id, task_run.id, step_name or "unknown")

    session = MultiTurnSession(
        task=task,
        task_run=task_run,
        verbose=verbose,
        output_fn=output_fn,
    )

    last_message, _, session.log_lines_seen, session.printed_lines = await _poll_for_turn(
        task_run, verbose=verbose, output_fn=output_fn
    )
    parsed = _parse_and_validate(last_message, model, label="initial turn")
    return session, parsed


async def send_followup(
    session: MultiTurnSession,
    message: str,
    model: type[_ModelT],
    *,
    label: str = "",
) -> _ModelT:
    """Send a follow-up message and wait for the agent's next response."""
    from posthog.temporal.common.client import async_connect

    from products.tasks.backend.temporal.process_task.workflow import ProcessTaskWorkflow

    workflow_id = TaskRun.get_workflow_id(session.task.id, session.task_run.id)
    client = await async_connect()
    handle = client.get_workflow_handle(workflow_id)
    await handle.signal(ProcessTaskWorkflow.send_followup_message, message)
    logger.info("multi_turn: sent followup run=%s label=%s", session.task_run.id, label)

    last_message, _, session.log_lines_seen, session.printed_lines = await _poll_for_turn(
        session.task_run,
        skip_lines=session.log_lines_seen,
        printed_lines=session.printed_lines,
        verbose=session.verbose,
        output_fn=session.output_fn,
    )
    parsed = _parse_and_validate(last_message, model, label=label or "followup")
    return parsed


async def end_session(session: MultiTurnSession) -> None:
    """Signal the workflow to shut down cleanly."""
    from posthog.temporal.common.client import async_connect

    from products.tasks.backend.temporal.process_task.workflow import ProcessTaskWorkflow

    workflow_id = TaskRun.get_workflow_id(session.task.id, session.task_run.id)
    try:
        client = await async_connect()
        handle = client.get_workflow_handle(workflow_id)
        await handle.signal(ProcessTaskWorkflow.complete_task, args=["completed", None])
        logger.info("multi_turn: ended session run=%s", session.task_run.id)
    except Exception:
        logger.warning("multi_turn: failed to signal completion run=%s", session.task_run.id, exc_info=True)


def _parse_and_validate(text: str, model: type[_ModelT], label: str) -> _ModelT:
    """Extract JSON from agent text and validate against a Pydantic model."""
    json_data = extract_json_from_text(text=text, label=label)
    return model.model_validate(json_data)
