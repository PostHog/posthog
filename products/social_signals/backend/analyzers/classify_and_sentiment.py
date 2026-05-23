"""Classify + sentiment analyzer.

Calls the PostHog LLM gateway with a structured output schema and returns:

    {
        "sentiment": "positive" | "neutral" | "negative",
        "sentiment_score": -1.0 to 1.0,
        "category": "bug" | "feature_request" | "praise" | "question" |
                    "complaint" | "comparison" | "other",
        "summary": str,
        "is_actionable": bool,
    }

The output schema is enforced server-side via OpenAI-compatible response_format
JSON schema. Unknown / missing fields fall back to safe defaults rather than
crashing the analyzer.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar

from posthog.llm.gateway_client import get_llm_client

from ..facade.enums import AnalyzerKind, MentionCategory, Sentiment

if TYPE_CHECKING:
    from ..models import Mention


# We deliberately use a small, cheap model — classification + short summary
# doesn't justify Opus, and we want this to scale to thousands per day.
_MODEL = "gpt-4.1-mini"

_SYSTEM_PROMPT = (
    "You are a social media analyst. You will be given a short post or comment "
    "that mentions a software product. Classify it and produce a one-sentence "
    "summary. Be conservative: when in doubt, prefer 'other' for category and "
    "'neutral' for sentiment. Output only valid JSON matching the requested schema."
)

_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["sentiment", "sentiment_score", "category", "summary", "is_actionable"],
    "properties": {
        "sentiment": {
            "type": "string",
            "enum": [s.value for s in Sentiment],
        },
        "sentiment_score": {
            "type": "number",
            "minimum": -1.0,
            "maximum": 1.0,
        },
        "category": {
            "type": "string",
            "enum": [c.value for c in MentionCategory],
        },
        "summary": {
            "type": "string",
            "maxLength": 240,
        },
        "is_actionable": {
            "type": "boolean",
        },
    },
}


def _build_user_message(mention: "Mention") -> str:
    parts: list[str] = [f"Platform: {mention.platform}"]
    if mention.author_handle:
        parts.append(f"Author: @{mention.author_handle}")
    if mention.url:
        parts.append(f"URL: {mention.url}")
    parts.append("Content:")
    parts.append(mention.content or "(empty)")
    return "\n".join(parts)


def _safe_result(raw: dict | None) -> dict[str, Any]:
    """Coerce LLM output into a known shape; fall back to neutral / other."""
    raw = raw or {}
    sentiment = raw.get("sentiment")
    if sentiment not in {s.value for s in Sentiment}:
        sentiment = Sentiment.NEUTRAL.value

    category = raw.get("category")
    if category not in {c.value for c in MentionCategory}:
        category = MentionCategory.OTHER.value

    score = raw.get("sentiment_score")
    if not isinstance(score, (int, float)) or score < -1 or score > 1:
        score = 0.0

    return {
        "sentiment": sentiment,
        "sentiment_score": float(score),
        "category": category,
        "summary": str(raw.get("summary") or "")[:240],
        "is_actionable": bool(raw.get("is_actionable", False)),
    }


class ClassifyAndSentimentAnalyzer:
    """Single-shot LLM classification + sentiment analysis for a mention."""

    kind: ClassVar[str] = AnalyzerKind.CLASSIFY_AND_SENTIMENT.value
    enabled_by_default: ClassVar[bool] = True
    model_used: ClassVar[str] = _MODEL

    def run(self, mention: "Mention") -> dict[str, Any]:
        client = get_llm_client("social_signals")
        completion = client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_message(mention)},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "social_mention_classification",
                    "strict": True,
                    "schema": _RESPONSE_SCHEMA,
                },
            },
            user=f"team-{mention.team_id}",
        )
        message = completion.choices[0].message
        content = message.content or "{}"
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = {}
        return _safe_result(parsed if isinstance(parsed, dict) else {})
