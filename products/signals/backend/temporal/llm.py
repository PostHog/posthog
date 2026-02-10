import os
import json
from typing import Annotated, Literal

import structlog
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from products.signals.backend.temporal.types import ExistingReportMatch, MatchResult, NewReportMatch, SignalCandidate

from ee.hogai.session_summaries.llm.call import get_async_openai_client

logger = structlog.get_logger(__name__)

MATCHING_MODEL = os.getenv("SIGNAL_MATCHING_LLM_MODEL", "gpt-4o-mini")
MAX_RETRIES = 3


class LLMMatchFound(BaseModel):
    match_index: int


class LLMNewGroup(BaseModel):
    match_index: Literal[None] = None
    title: str
    summary: str


LLMMatchResponse = Annotated[LLMMatchFound | LLMNewGroup, Field(discriminator="match_index")]


SYSTEM_PROMPT = """You are a signal grouping assistant. Your job is to determine if a new signal is related to an existing group of signals, or if it should start a new group.

Signals come from diverse sources: exceptions, experiments, insight alerts, session behaviour analysis, and more. Your task is to identify signals that are RELATED - they may be different signal types but connected by the same underlying cause, feature, or user journey.

IMPORTANT: Signals should be grouped if they are meaningfully related, not just superficially similar:
- An experiment reaching significance AND an error spike on the same feature SHOULD match (related by feature)
- A session behaviour anomaly AND an insight alert about the same user flow SHOULD match (related by user journey)
- Two "experiment reached significance" signals from DIFFERENT, unrelated experiments should NOT match
- Two signals about the SAME experiment (e.g., significance + follow-up analysis) SHOULD match

You will receive:
1. A new signal with its description and source information
2. A list of candidate signals (may be empty) with their descriptions, sources, and cosine distances

If a candidate signal is related to the new signal, respond with:
{"match_index": <0-based index of the matching candidate>}

If no candidate is related (or the list is empty), respond with:
{"match_index": null, "title": "<short title for a new report>", "summary": "<1-2 sentence summary of what this signal group is about>"}

Respond ONLY with valid JSON, no other text."""


def _build_user_prompt(
    description: str,
    source_product: str,
    source_type: str,
    candidates: list[SignalCandidate],
) -> str:
    prompt = f"""NEW SIGNAL:
- Source: {source_product} / {source_type}
- Description: {description}

"""
    if not candidates:
        prompt += "CANDIDATES: (none - this is the first signal of its kind)\n"
    else:
        prompt += "CANDIDATES:\n"
        for i, c in enumerate(candidates):
            prompt += f"""
{i}. [distance: {c.distance:.4f}]
   Source: {c.source_product} / {c.source_type}
   Description: {c.content}
   Report ID: {c.report_id}
"""

    return prompt


async def match_signal_with_llm(
    description: str,
    source_product: str,
    source_type: str,
    candidates: list[SignalCandidate],
) -> MatchResult:
    user_prompt = _build_user_prompt(description, source_product, source_type, candidates)
    client = get_async_openai_client()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            response = await client.chat.completions.create(  # type: ignore[call-overload]
                model=MATCHING_MODEL,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0,
            )

            content = response.choices[0].message.content
            if not content:
                raise ValueError("Empty response from LLM")

            parsed: LLMMatchFound | LLMNewGroup = TypeAdapter(LLMMatchResponse).validate_json(content)

            if isinstance(parsed, LLMMatchFound):
                if parsed.match_index < 0 or parsed.match_index >= len(candidates):
                    raise ValueError(f"match_index {parsed.match_index} out of range")
                matched = candidates[parsed.match_index]
                return ExistingReportMatch(report_id=matched.report_id)

            return NewReportMatch(title=parsed.title, summary=parsed.summary)

        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            last_error = e
            logger.warning(
                f"Invalid LLM response (attempt {attempt + 1}/{MAX_RETRIES}): {e}",
                attempt=attempt + 1,
                max_retries=MAX_RETRIES,
            )
            continue

    raise ValueError(f"Failed to get valid LLM response after {MAX_RETRIES} attempts: {last_error}")
