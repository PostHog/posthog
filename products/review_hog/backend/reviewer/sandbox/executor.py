import json
import asyncio
import logging
from pathlib import Path

from django.conf import settings

from asgiref.sync import sync_to_async
from pydantic import BaseModel

from products.review_hog.backend.reviewer.constants import MAX_CONCURRENT_SANDBOXES
from products.tasks.backend.services.custom_prompt_executor import extract_json_from_text
from products.tasks.backend.services.custom_prompt_runner import (
    CustomPromptSandboxContext,
    resolve_sandbox_context_for_local_dev,
    run_prompt,
)

logger = logging.getLogger(__name__)

_sandbox_semaphore = asyncio.Semaphore(MAX_CONCURRENT_SANDBOXES)

# Cloud defaults (used when DEBUG=False)
_CLOUD_TEAM_ID = 2
_CLOUD_USER_ID = 196695
_CLOUD_REPOSITORY = "posthog/posthog"
_LOCAL_REPOSITORY = "sortafreel/posthog"


async def _resolve_context() -> CustomPromptSandboxContext:
    """Return sandbox context based on environment (cloud vs local dev)."""
    if settings.DEBUG:
        return await sync_to_async(resolve_sandbox_context_for_local_dev)(_LOCAL_REPOSITORY)
    return CustomPromptSandboxContext(
        team_id=_CLOUD_TEAM_ID,
        user_id=_CLOUD_USER_ID,
        repository=_CLOUD_REPOSITORY,
    )


async def run_sandbox_review(
    prompt: str,
    system_prompt: str,
    branch: str,
    output_path: str,
    model_to_validate: type[BaseModel],
    step_name: str = "",
) -> bool:
    """Run a review in a sandbox and save validated output locally.

    Combines system prompt and user prompt, sends to a sandbox agent,
    extracts JSON from the response, validates with Pydantic, and saves locally.

    Returns True if successful, False otherwise.
    """
    async with _sandbox_semaphore:
        logger.info(f"Acquired sandbox semaphore (limit={MAX_CONCURRENT_SANDBOXES})")

        full_prompt = f"{system_prompt}\n\n{prompt}"
        context = await _resolve_context()

        try:
            last_message, full_log = await run_prompt(
                prompt=full_prompt, context=context, branch=branch, step_name=step_name
            )
        except Exception as e:
            logger.exception(f"Sandbox execution failed: {e}")
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
            logger.exception(f"Error processing sandbox output: {e}")
            return False
