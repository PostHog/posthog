import re
import json
import logging
from typing import Any, TypeVar

from pydantic import BaseModel

from products.tasks.backend.services.custom_prompt_runner import CustomPromptSandboxContext, OutputFn, run_prompt

logger = logging.getLogger(__name__)

_ModelT = TypeVar("_ModelT", bound=BaseModel)


async def run_sandbox_agent_get_structured_output(
    prompt: str,
    context: CustomPromptSandboxContext,
    model_to_validate: type[_ModelT],
    *,
    branch: str | None = None,
    step_name: str = "",
    verbose: bool = False,
    output_fn: OutputFn = None,
) -> _ModelT:
    """Run an agent with a custom prompt in a sandbox and return validated Pydantic output."""
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
