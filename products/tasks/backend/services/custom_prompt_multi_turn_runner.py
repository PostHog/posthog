import asyncio
import logging
from dataclasses import dataclass, field
from typing import TypeVar

from asgiref.sync import sync_to_async
from pydantic import BaseModel

from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.services.custom_prompt_executor import extract_json_from_text
from products.tasks.backend.services.custom_prompt_runner import (
    MAX_CONSECUTIVE_STORAGE_ERRORS,
    MAX_POLL_SECONDS,
    POLL_INTERVAL_SECONDS,
    CustomPromptSandboxContext,
    OutputFn,
    _check_logs,
    _create_task_and_trigger,
    _stream_new_lines,
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

    last_message = await _poll_for_turn(session)
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

    last_message = await _poll_for_turn(session)
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


async def _poll_for_turn(session: MultiTurnSession) -> str:
    """Poll S3 logs until the agent finishes its current turn, starting from the session offset."""
    from posthog.storage.object_storage import ObjectStorageError

    elapsed = 0
    consecutive_storage_errors = 0

    while elapsed < MAX_POLL_SECONDS:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        elapsed += POLL_INTERVAL_SECONDS

        try:
            new_end_turn, last_message, full_log, total_lines = await sync_to_async(_check_logs)(
                session.task_run, session.log_lines_seen
            )
        except ObjectStorageError:
            consecutive_storage_errors += 1
            logger.warning(
                "multi_turn: transient storage error (%d/%d)",
                consecutive_storage_errors,
                MAX_CONSECUTIVE_STORAGE_ERRORS,
                exc_info=True,
            )
            if consecutive_storage_errors >= MAX_CONSECUTIVE_STORAGE_ERRORS:
                raise
            continue
        consecutive_storage_errors = 0

        # Stream log lines to output
        if full_log:
            session.printed_lines = _stream_new_lines(
                full_log, session.printed_lines, verbose=session.verbose, output_fn=session.output_fn
            )

        if new_end_turn and last_message:
            session.log_lines_seen = total_lines
            return last_message

        # Check for terminal TaskRun status (agent/workflow crash)
        refreshed = await sync_to_async(TaskRun.objects.get)(id=session.task_run.id)
        if refreshed.status in {TaskRun.Status.COMPLETED, TaskRun.Status.FAILED, TaskRun.Status.CANCELLED}:
            # One final log read
            for attempt in range(MAX_CONSECUTIVE_STORAGE_ERRORS):
                try:
                    _, final_message, final_log, final_lines = await sync_to_async(_check_logs)(
                        session.task_run, session.log_lines_seen
                    )
                    break
                except ObjectStorageError:
                    if attempt + 1 >= MAX_CONSECUTIVE_STORAGE_ERRORS:
                        raise
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)
            else:
                final_message = None
                final_log = None
                final_lines = session.log_lines_seen

            if final_log:
                session.printed_lines = _stream_new_lines(
                    final_log, session.printed_lines, verbose=session.verbose, output_fn=session.output_fn
                )
            session.log_lines_seen = final_lines

            if final_message:
                return final_message
            raise RuntimeError(f"multi_turn: TaskRun reached terminal status={refreshed.status} with no agent message")

    raise RuntimeError(f"multi_turn: polling timed out after {elapsed}s")
