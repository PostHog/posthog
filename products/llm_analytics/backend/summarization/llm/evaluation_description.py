"""LLM gateway-based evaluation description generation."""

from typing import Any, cast

import structlog
from openai.types.chat import ChatCompletionMessageParam
from rest_framework import exceptions

from posthog.llm.gateway_client import get_async_llm_client

from ..constants import SUMMARIZATION_TIMEOUT
from ..models import OpenAIModel
from ..utils import load_summarization_template
from .description_schema import EvaluationDescriptionResponse

logger = structlog.get_logger(__name__)


EVALUATION_TYPE_LABELS = {
    "llm_judge": "LLM judge (uses an LLM to grade each generation against a natural-language prompt)",
    "hog": "Hog code (runs deterministic code against each generation)",
}


async def generate_evaluation_description(
    team_id: int,
    model: OpenAIModel,
    evaluation_type: str,
    evaluation_name: str = "",
    evaluation_prompt: str = "",
    evaluation_source: str = "",
    allows_na: bool = False,
    existing_description: str = "",
    user_distinct_id: str = "",
) -> EvaluationDescriptionResponse:
    """
    Generate a concise description for an evaluation using LLM gateway with structured outputs.

    Args:
        team_id: Team ID for logging and tracking
        model: OpenAI model to use
        evaluation_type: "llm_judge" or "hog"
        evaluation_name: Current name of the evaluation
        evaluation_prompt: Judge prompt (for llm_judge type)
        evaluation_source: Hog source code (for hog type)
        allows_na: Whether the evaluation allows "Not applicable" results
        existing_description: The current description (used as a hint; may be rewritten)
        user_distinct_id: Distinct ID of the user for analytics tracking

    Returns:
        Structured description response
    """
    if evaluation_type not in EVALUATION_TYPE_LABELS:
        raise exceptions.ValidationError(f"Unknown evaluation type: {evaluation_type}")

    has_config = bool(evaluation_prompt.strip()) if evaluation_type == "llm_judge" else bool(evaluation_source.strip())
    if not has_config and not evaluation_name.strip():
        raise exceptions.ValidationError(
            "Cannot generate a description: evaluation has no name, prompt, or source code yet."
        )

    system_prompt = load_summarization_template(
        "prompts/evaluation_description.djt",
        {
            "evaluation_type": evaluation_type,
            "evaluation_type_label": EVALUATION_TYPE_LABELS[evaluation_type],
            "evaluation_name": evaluation_name,
            "evaluation_prompt": evaluation_prompt,
            "evaluation_source": evaluation_source,
            "allows_na": allows_na,
            "existing_description": existing_description,
        },
    )

    user_prompt = "Generate a concise description for this evaluation."

    # Reuse the registered "llma_eval_summary" product slug — this endpoint is semantically
    # part of the same feature. Adding a new slug requires a coordinated change in
    # services/llm-gateway/src/llm_gateway/products/config.py.
    client = get_async_llm_client("llma_eval_summary").with_options(timeout=SUMMARIZATION_TIMEOUT)

    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        response = await client.chat.completions.create(
            model=str(model),
            messages=messages,
            user=user_distinct_id or "llma-evaluation-description",
            response_format=cast(
                Any,
                {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "evaluation_description",
                        "strict": True,
                        "schema": EvaluationDescriptionResponse.model_json_schema(),
                    },
                },
            ),
        )

        content = response.choices[0].message.content
        if not content:
            logger.error(
                "evaluation_description_empty_response",
                team_id=team_id,
                model=str(model),
            )
            raise exceptions.APIException("Failed to generate evaluation description: empty response")

        return EvaluationDescriptionResponse.model_validate_json(content)

    except exceptions.APIException:
        raise
    except Exception as e:
        logger.exception(
            "evaluation_description_failed",
            team_id=team_id,
            model=str(model),
            error=str(e),
        )
        raise exceptions.APIException("Failed to generate evaluation description") from e
