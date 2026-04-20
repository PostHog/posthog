import re
import json
import asyncio
import logging
from typing import Any, TypeVar

from asgiref.sync import sync_to_async
from pydantic import BaseModel

from posthog.storage import object_storage

from products.tasks.backend.models import TaskRun
from products.tasks.backend.services.custom_prompt_runner import CustomPromptSandboxContext, OutputFn

logger = logging.getLogger(__name__)

_ModelT = TypeVar("_ModelT", bound=BaseModel)

# Polling settings for structured output tasks (task_run.output instead of S3 logs)
_STRUCTURED_POLL_INTERVAL_SECONDS = 5
_STRUCTURED_MAX_POLL_SECONDS = 30 * 60  # 30 minutes


async def run_sandbox_agent_get_structured_output(
    prompt: str,
    context: CustomPromptSandboxContext,
    model_to_validate: type[_ModelT],
    *,
    branch: str = "master",
    step_name: str = "",
    verbose: bool = False,
    output_fn: OutputFn = None,
) -> _ModelT:
    """Run an agent with a custom prompt in a sandbox and return validated Pydantic output.

    Passes the model's JSON schema as ``output_schema`` to the task, which gives the
    agent a structured output tool. The agent calls ``set_output`` with its result,
    which is stored on ``task_run.output`` and validated here. This avoids relying on
    S3 log parsing for the agent's response, which can be lossy for large JSON.
    """
    schema = model_to_validate.model_json_schema()

    try:
        # run_prompt still polls S3 logs for liveness / heartbeating, but the actual
        # result comes from task_run.output for structured output tasks. run_prompt
        # will return when the task reaches a terminal status (COMPLETED/FAILED).
        # We ignore the last_message from the log and read task_run.output instead.
        _last_message, _full_log, task, task_run = await _run_prompt_with_task(
            prompt=prompt,
            context=context,
            branch=branch,
            step_name=step_name,
            verbose=verbose,
            output_fn=output_fn,
            output_schema=schema,
        )
    except Exception:
        logger.exception("Sandbox execution failed")
        raise

    # For structured output tasks, read from task_run.output (set via set_output API)
    refreshed = await sync_to_async(TaskRun.objects.get)(id=task_run.id)
    if refreshed.output is not None:
        try:
            return model_to_validate.model_validate(refreshed.output)
        except Exception:
            logger.exception("Error validating structured output from task_run.output")
            raise

    # Fallback: if task_run.output wasn't set (agent didn't use the tool), parse from
    # the agent's text message the old way
    if _last_message:
        logger.warning(
            "Structured output task %s did not use set_output tool, falling back to text parsing",
            task_run.id,
        )
        try:
            json_data = extract_json_from_text(text=_last_message, label="Sandbox output")
            return model_to_validate.model_validate(json_data)
        except Exception:
            logger.exception("Error processing sandbox output (fallback text parsing)")
            raise

    raise RuntimeError("Sandbox returned no agent message and no structured output")


async def _run_prompt_with_task(
    prompt: str,
    context: CustomPromptSandboxContext,
    *,
    branch: str = "master",
    step_name: str = "",
    verbose: bool = False,
    output_fn: OutputFn = None,
    output_schema: dict | None = None,
) -> tuple[str | None, str | None, Any, Any]:
    """Like run_prompt but also returns the task and task_run objects.

    When output_schema is set, tolerates the S3 log polling failing (since the
    result comes from task_run.output instead), and polls for task completion.
    """
    from products.tasks.backend.services.custom_prompt_runner import _create_task_and_trigger, _poll_for_turn

    task, task_run = await _create_task_and_trigger(prompt, context, branch, step_name, output_schema=output_schema)
    logger.info(
        "custom_prompt_executor: started task=%s run=%s step=%s structured=%s",
        task.id,
        task_run.id,
        step_name or "unknown",
        output_schema is not None,
    )

    if output_schema is not None:
        # For structured output tasks, poll for task_run to reach terminal status
        # instead of relying on S3 log parsing to find the agent_message
        last_message = await _poll_for_structured_completion(task_run, verbose=verbose, output_fn=output_fn)
        return last_message, None, task, task_run

    # Non-structured: use the standard S3 log polling
    last_message, full_log, _, _ = await _poll_for_turn(task_run, verbose=verbose, output_fn=output_fn)
    return last_message, full_log, task, task_run


async def _poll_for_structured_completion(
    task_run,
    *,
    verbose: bool = False,
    output_fn: OutputFn = None,
) -> str | None:
    """Poll until a structured-output task_run reaches a terminal status.

    Returns the last agent message from logs if available (best-effort), but the
    caller should prefer task_run.output for the actual result.
    """
    from products.tasks.backend.services.custom_prompt_runner import _check_logs, _stream_new_lines

    elapsed = 0
    skip_lines = 0
    printed_lines = 0
    latest_text: str | None = None

    while elapsed < _STRUCTURED_MAX_POLL_SECONDS:
        await asyncio.sleep(_STRUCTURED_POLL_INTERVAL_SECONDS)
        elapsed += _STRUCTURED_POLL_INTERVAL_SECONDS

        # Best-effort: stream log lines for visibility, but don't fail if S3 is flaky
        try:
            log_content = await sync_to_async(
                lambda: object_storage.read(task_run.log_url, missing_ok=True),
                thread_sensitive=False,
            )()
            if log_content:
                printed_lines = _stream_new_lines(log_content, printed_lines, verbose=verbose, output_fn=output_fn)
                # Try to extract latest agent text from logs
                try:
                    _, last_msg, _, total_lines, _ = _check_logs(task_run, skip_lines)
                    if last_msg:
                        latest_text = last_msg
                    skip_lines = max(skip_lines, total_lines)
                except Exception:
                    pass
        except Exception:
            pass

        # Check if task_run reached terminal status
        refreshed = await sync_to_async(TaskRun.objects.get)(id=task_run.id)
        if refreshed.status in {
            TaskRun.Status.COMPLETED,
            TaskRun.Status.FAILED,
            TaskRun.Status.CANCELLED,
        }:
            if refreshed.status == TaskRun.Status.FAILED:
                raise RuntimeError(f"Structured output task failed: {refreshed.error_message or 'unknown error'}")
            if refreshed.status == TaskRun.Status.CANCELLED:
                raise RuntimeError("Structured output task was cancelled")
            # COMPLETED — caller will read task_run.output
            logger.info("custom_prompt_executor: structured task completed run=%s", task_run.id)
            return latest_text

    raise RuntimeError(f"custom_prompt_executor: structured output task timed out after {elapsed}s")


def extract_json_from_text(text: str | None, label: str) -> Any:
    """Extract JSON from text that might contain markdown formatting or surrounding commentary."""
    if text is None:
        raise ValueError(f"Text to extract JSON from ({label}) is None")

    # 1. ```json ... ``` fenced code block (non-greedy to stop at first closing fence)
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        candidate = match.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # 2. ``` ... ``` generic code block that happens to contain JSON
    match = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        candidate = match.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # 3. Bare JSON object in surrounding text — try each { from the left paired with the last }
    last_brace = text.rfind("}")
    if last_brace != -1:
        start = 0
        while True:
            brace_pos = text.find("{", start)
            if brace_pos == -1 or brace_pos >= last_brace:
                break
            try:
                return json.loads(text[brace_pos : last_brace + 1])
            except json.JSONDecodeError:
                start = brace_pos + 1

    # 4. Last resort — try the whole text as-is
    return json.loads(text)
