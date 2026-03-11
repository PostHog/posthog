import asyncio
import logging

from pydantic import BaseModel

from products.signals.backend.report_generation.runner import OutputFn, run_prompt
from products.signals.backend.report_generation.utils import extract_json_from_text

MAX_CONCURRENT_SANDBOXES = 5

logger = logging.getLogger(__name__)

_sandbox_semaphore = asyncio.Semaphore(MAX_CONCURRENT_SANDBOXES)


async def run_sandbox_agent_get_structured_output(
    prompt: str,
    branch: str,
    model_to_validate: type[BaseModel],
    step_name: str = "",
    verbose: bool = False,
    output_fn: OutputFn = None,
) -> BaseModel:
    """
    Run an agent with a custom prompt in a sandbox and return validated output.
    """
    async with _sandbox_semaphore:
        logger.info(f"Acquired sandbox semaphore (limit={MAX_CONCURRENT_SANDBOXES})")
        try:
            last_message, _ = await run_prompt(
                prompt=prompt, branch=branch, step_name=step_name, verbose=verbose, output_fn=output_fn
            )
        except Exception as e:
            logger.exception(f"Sandbox execution failed: {e}")
            raise
        if not last_message:
            logger.error("Sandbox returned no agent message")
            raise
        # Extract JSON, validate, and save
        try:
            json_data = extract_json_from_text(text=last_message, label="Sandbox output")
            validated_data = model_to_validate.model_validate(json_data)
            return validated_data
        except Exception as e:
            logger.exception(f"Error processing sandbox output: {e}")
            raise
