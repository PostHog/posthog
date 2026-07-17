"""Anthropic provider for survey summarization, routed through the internal ai-gateway.

Uses the OpenAI Chat Completions shape (``build_openai_client``): the gateway translates it to
the Anthropic model named by ``model`` and captures the ``$ai_generation`` event itself, so we do
NOT wrap the client with ``posthoganalytics.ai`` (that would double-capture). Per-call analytics
dimensions ride the ``X-PostHog-Properties`` blob and the trace id rides ``X-PostHog-Trace-Id``,
both of which the gateway reads.
"""

import json
import uuid
from dataclasses import dataclass

import structlog
from rest_framework import exceptions

from posthog.llm.gateway_client import build_openai_client

from ..constants import DEFAULT_MODEL, SUMMARIZATION_TIMEOUT
from ..models import AnthropicModel
from .schema import SurveySummaryResponse

logger = structlog.get_logger(__name__)


@dataclass
class SummarizationResult:
    """Result of survey summarization including trace_id for feedback mapping."""

    summary: SurveySummaryResponse
    trace_id: str


SYSTEM_PROMPT = """You are a product manager's assistant specializing in analyzing survey responses.

Your goal is to identify actionable user pain points and needs from survey data.

Guidelines:
- Be concise and focus on what matters most for product decisions
- Identify patterns and themes across responses (maximum 5 themes)
- Use actual quotes to support your analysis
- Prioritize themes by how frequently they appear
- For each theme, estimate the percentage of responses that mention it (>50%, 25-50%, 10-25%, or <10%)
- Focus on actionable insights that can drive product improvements
- Keep the overview to 1-2 sentences
- Keep the key insight to 1 sentence

Respond with a single JSON object (no markdown fences) matching this JSON schema:
{schema}"""


def _build_user_prompt(question_text: str, responses: list[str]) -> str:
    """Build the user prompt with question and responses."""
    responses_text = "\n".join(f"- {r}" for r in responses)
    return f"""Analyze these survey responses and identify key themes.

Survey Question: {question_text}

Responses:
{responses_text}

Identify the key themes, patterns, and actionable insights. Include relevant quotes to support each theme."""


def summarize_with_anthropic(
    question_text: str,
    responses: list[str],
    model: AnthropicModel = DEFAULT_MODEL,
    *,
    distinct_id: str | None = None,
    survey_id: str | None = None,
    question_id: str | None = None,
    team_id: int | None = None,
) -> SummarizationResult:
    """
    Generate a survey summary using a cheap Anthropic model routed through the ai-gateway.

    Args:
        question_text: The survey question being summarized
        responses: List of response strings to analyze
        model: Anthropic model to use
        distinct_id: User's distinct ID for analytics
        survey_id: Survey ID for analytics
        question_id: Question ID for analytics
        team_id: Team ID the generation is attributed to

    Returns:
        SummarizationResult with summary and trace_id for feedback mapping
    """
    if not responses:
        raise exceptions.ValidationError("responses cannot be empty")

    # ai_product=None: we build the full X-PostHog-Properties blob below so the per-call survey
    # dimensions ride alongside the product tag rather than overriding it.
    client = build_openai_client("survey_summary")

    trace_id = str(uuid.uuid4())
    system_prompt = SYSTEM_PROMPT.format(schema=json.dumps(SurveySummaryResponse.model_json_schema()))

    # The gateway reads event dimensions from this JSON blob (not the x-posthog-property-<key>
    # per-header form), and stamps $ai_trace_id from X-PostHog-Trace-Id so feedback maps back.
    properties = {"ai_product": "survey_summary", "ai_feature": "survey_summary", "response_count": len(responses)}
    if survey_id:
        properties["survey_id"] = survey_id
    if question_id:
        properties["question_id"] = question_id

    create_kwargs: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": _build_user_prompt(question_text, responses)},
        ],
        "response_format": {"type": "json_object"},
        "timeout": SUMMARIZATION_TIMEOUT,
        "extra_headers": {
            "X-PostHog-Properties": json.dumps(properties),
            "X-PostHog-Trace-Id": trace_id,
        },
    }
    if distinct_id:
        create_kwargs["user"] = distinct_id

    try:
        response = client.chat.completions.create(**create_kwargs)
        content = response.choices[0].message.content
        if not content:
            raise exceptions.ValidationError("Model returned empty response")
        return SummarizationResult(summary=SurveySummaryResponse.model_validate_json(content), trace_id=trace_id)
    except exceptions.ValidationError:
        raise
    except Exception:
        logger.exception("survey_summary_generation_failed", model=str(model), properties=properties)
        raise exceptions.APIException("Failed to generate response")
