"""OpenAI-based evaluation summary generation."""

from typing import Any, cast

import structlog
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from rest_framework import exceptions

from ..constants import SUMMARIZATION_TIMEOUT
from ..models import OpenAIModel
from ..utils import load_summarization_template
from .evaluation_schema import EvaluationSummaryResponse

logger = structlog.get_logger(__name__)


async def summarize_evaluation_runs(
    evaluation_runs: list[dict],
    team_id: int,
    model: OpenAIModel,
) -> EvaluationSummaryResponse:
    """
    Generate summary of evaluation runs using OpenAI API with structured outputs.

    Args:
        evaluation_runs: List of dicts with 'result' (bool) and 'reasoning' (str)
        team_id: Team ID for logging and tracking
        model: OpenAI model to use

    Returns:
        Structured evaluation summary response
    """
    if not evaluation_runs:
        raise exceptions.ValidationError("No evaluation runs provided")

    # Format the evaluation runs for the prompt
    runs_text = "\n\n".join(
        [f"- Result: {'PASS' if run['result'] else 'FAIL'}\n  Reasoning: {run['reasoning']}" for run in evaluation_runs]
    )

    # Count statistics for the prompt
    pass_count = sum(1 for run in evaluation_runs if run["result"])
    fail_count = len(evaluation_runs) - pass_count

    system_prompt = load_summarization_template("prompts/evaluation_summary.djt", {})
    user_prompt = f"""Analyze these {len(evaluation_runs)} evaluation results ({pass_count} passed, {fail_count} failed):

{runs_text}"""

    client = AsyncOpenAI(timeout=SUMMARIZATION_TIMEOUT)

    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        response = await client.chat.completions.create(
            model=str(model),
            messages=messages,
            user="llma-evaluation-summarization",
            response_format=cast(
                Any,
                {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "evaluation_summary_response",
                        "strict": True,
                        "schema": EvaluationSummaryResponse.model_json_schema(),
                    },
                },
            ),
        )

        content = response.choices[0].message.content
        if not content:
            raise exceptions.ValidationError("OpenAI returned empty response")
        return EvaluationSummaryResponse.model_validate_json(content)
    except exceptions.ValidationError:
        raise
    except Exception as e:
        logger.exception(
            "OpenAI API call failed for evaluation summary",
            error=str(e),
            team_id=team_id,
            model=str(model),
            runs_count=len(evaluation_runs),
        )
        raise exceptions.APIException("Failed to generate evaluation summary")
