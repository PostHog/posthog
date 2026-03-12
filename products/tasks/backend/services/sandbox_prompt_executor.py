"""High-level executor: run a prompt in a sandbox and get validated structured output.

Wraps sandbox_prompt_runner with JSON extraction and Pydantic validation.
"""

import re
import json
import asyncio
import logging
from typing import Any

from pydantic import BaseModel

from products.tasks.backend.services.sandbox_prompt_runner import OutputFn, SandboxContext, run_prompt

MAX_CONCURRENT_SANDBOXES = 5

logger = logging.getLogger(__name__)

_sandbox_semaphore = asyncio.Semaphore(MAX_CONCURRENT_SANDBOXES)


async def run_sandbox_agent_get_structured_output(
    prompt: str,
    context: SandboxContext,
    model_to_validate: type[BaseModel],
    *,
    branch: str = "master",
    step_name: str = "",
    verbose: bool = False,
    output_fn: OutputFn = None,
) -> BaseModel:
    """Run an agent with a custom prompt in a sandbox and return validated Pydantic output."""
    async with _sandbox_semaphore:
        logger.info("Acquired sandbox semaphore (limit=%d)", MAX_CONCURRENT_SANDBOXES)
        try:
            last_message, _ = await run_prompt(
                prompt=prompt,
                context=context,
                branch=branch,
                step_name=step_name,
                verbose=verbose,
                output_fn=output_fn,
            )
        except Exception:
            logger.exception("Sandbox execution failed")
            raise
        if not last_message:
            raise RuntimeError("Sandbox returned no agent message")
        try:
            json_data = extract_json_from_text(text=last_message, label="Sandbox output")
            return model_to_validate.model_validate(json_data)
        except Exception:
            logger.exception("Error processing sandbox output")
            raise


def extract_json_from_text(text: str | None, label: str) -> Any:
    """Extract JSON from text that might contain markdown formatting."""
    if text is None:
        raise ValueError(f"Text to extract JSON from ({label}) is None")
    # Expect ```json...``` pattern first
    pattern = r"```json(?:\n|\s)*(.*)(?:\n|\s)*```"
    match = re.search(pattern, text, re.DOTALL | re.MULTILINE)
    if match:
        json_text = match.group(1).strip()
        return json.loads(json_text)
    # Try to get dict-ish object from text
    pattern = r"\n(\{(?:\n|\s)*\"(?:.|\n|\s)*\})"
    match = re.search(pattern, text, re.DOTALL | re.MULTILINE)
    if match:
        return json.loads(match.group(0))
    # Try to parse the text directly as JSON
    return json.loads(text)
