import json
import asyncio
import logging
from pathlib import Path

from pydantic import BaseModel

from products.review_hog.backend.reviewer.constants import MAX_CONCURRENT_SANDBOXES
from products.review_hog.backend.reviewer.sandbox.runner import run_review
from products.review_hog.backend.reviewer.utils.json_utils import extract_json_from_text

logger = logging.getLogger(__name__)

_sandbox_semaphore = asyncio.Semaphore(MAX_CONCURRENT_SANDBOXES)


async def run_sandbox_review(
    prompt: str,
    system_prompt: str,
    branch: str,
    output_path: str,
    model_to_validate: type[BaseModel],
) -> bool:
    """Run a review in a sandbox and save validated output locally.

    Combines system prompt and user prompt, sends to a sandbox agent,
    extracts JSON from the response, validates with Pydantic, and saves locally.

    Returns True if successful, False otherwise.
    """
    async with _sandbox_semaphore:
        logger.info(f"Acquired sandbox semaphore (limit={MAX_CONCURRENT_SANDBOXES})")

        full_prompt = f"{system_prompt}\n\n{prompt}"

        try:
            last_message, full_log = await run_review(prompt=full_prompt, branch=branch)
        except Exception as e:
            logger.error(f"Sandbox execution failed: {e}")
            return False

        # Save full logs for debugging
        log_path = str(output_path).replace(".json", "_logs.txt")
        try:
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            with Path(log_path).open("w") as f:
                f.write(full_log)
        except Exception as e:
            logger.warning(f"Failed to save logs to {log_path}: {e}")

        if not last_message:
            logger.error("Sandbox returned no agent message")
            return False

        # Extract JSON, validate, and save
        try:
            json_data = extract_json_from_text(text=last_message, label="Sandbox output")
            validated_data = model_to_validate.model_validate(json_data)
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with Path(output_path).open("w") as f:
                f.write(json.dumps(validated_data.model_dump(mode="json"), indent=2))
            logger.info(f"Successfully saved validated data to: {output_path}")
            return True
        except Exception as e:
            error_path = str(output_path).replace(".json", "_error.txt")
            with Path(error_path).open("w") as f:
                f.write(last_message)
            logger.error(f"Error processing sandbox output: {e}")
            return False
