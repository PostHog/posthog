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
            new_end_turn, last_message, full_log, total_lines = await sync_to_async(_check_logs_from_offset)(
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
                    _, final_message, final_log, final_lines = await sync_to_async(_check_logs_from_offset)(
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


def _check_logs_from_offset(task_run: TaskRun, skip_lines: int) -> tuple[bool, str | None, str | None, int]:
    """Read S3 logs and parse only lines after skip_lines for new end_turn/agent messages.

    Returns (found_new_end_turn, last_agent_message, full_log_content, total_line_count).
    """
    import json

    from posthog.storage import object_storage

    from products.tasks.backend.services.custom_prompt_runner import _extract_text

    log_content = object_storage.read(task_run.log_url, missing_ok=True) or ""
    if not log_content.strip():
        return False, None, None, 0

    lines = log_content.strip().split("\n")
    total_lines = len(lines)

    # Eventual consistency: if S3 returns fewer lines than expected, no new data
    if total_lines <= skip_lines:
        return False, None, log_content, total_lines

    new_lines = lines[skip_lines:]
    agent_finished = False
    _AGENT_MSG_TYPES = {"agent_message", "agent_message_chunk"}
    parsed_updates: list[dict] = []

    for line in new_lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        notification = entry.get("notification")
        if not isinstance(notification, dict):
            continue
        result = notification.get("result")
        if isinstance(result, dict) and result.get("stopReason") == "end_turn":
            agent_finished = True
        if notification.get("method") != "session/update":
            continue
        params = notification.get("params")
        update = params.get("update") if isinstance(params, dict) else None
        if not isinstance(update, dict):
            continue
        parsed_updates.append(update)

    # Walk backwards to find the last agent message in the new lines
    trailing_parts: list[str] = []
    found_agent_msg = False
    for update in reversed(parsed_updates):
        is_agent_msg = update.get("sessionUpdate") in _AGENT_MSG_TYPES
        if not found_agent_msg:
            if is_agent_msg:
                found_agent_msg = True
            else:
                continue
        if found_agent_msg and not is_agent_msg:
            break
        text = _extract_text(update)
        if text:
            trailing_parts.append(text)
    trailing_parts.reverse()
    latest_text = "".join(trailing_parts) if trailing_parts else None

    return agent_finished, latest_text, log_content, total_lines
