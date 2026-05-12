"""Synthesize a baseline summary for a watched question.

The baseline summary is the comparison anchor passed to Max on every subsequent drift run.
A one-paragraph natural-language description of what the query measures and what its current
value is keeps the schedule cheap (no need to re-render the chart each run) and resilient to
schema drift on the underlying AssistantQuery types.
"""

import json
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


_BASELINE_SUMMARY_SYSTEM_PROMPT = """\
You write one-paragraph baselines for PostHog AI watched questions.

Given a user's natural-language question and the visualization PostHog AI produced as its
answer, write a single short paragraph (3-5 sentences) that:
- Re-states what the metric is and how it's defined (event, breakdown, filter, date range).
- States the current observed value(s) in concrete numbers and units.
- Names the time window the answer applies to.

The paragraph is reused as the anchor against which future scheduled runs of the same query
are compared. Be concrete and avoid hedging — this is a reference, not a narrative.
"""


def _serialize_visualization_for_prompt(visualization_message: dict[str, Any]) -> str:
    """Compact the VisualizationMessage payload into a prompt-safe blob."""
    try:
        return json.dumps(visualization_message, default=str)[:8000]
    except Exception:
        return repr(visualization_message)[:8000]


def generate_baseline_summary_for_message(*, question_text: str, visualization_message: dict[str, Any]) -> str:
    """Produce the baseline anchor paragraph. Falls back to a deterministic short string on
    LLM failure so watch creation is never blocked by a flaky upstream model.
    """
    safe_question = (question_text or "").strip()[:1000]
    if not safe_question:
        return ""

    try:
        from ee.hogai.llm import MaxChatLLM  # type: ignore[import-not-found]
    except Exception:  # pragma: no cover - import fallback
        MaxChatLLM = None  # type: ignore[assignment]

    if MaxChatLLM is None:
        logger.warning("MaxChatLLM unavailable; returning short deterministic baseline summary.")
        return f'Baseline question: "{safe_question}". The latest answer is the visualization saved with this watch.'

    user_prompt = (
        f"User question: {safe_question}\n\n"
        f"Visualization payload (JSON, may be truncated):\n{_serialize_visualization_for_prompt(visualization_message)}"
    )

    try:
        llm = MaxChatLLM(model="claude-haiku-4-5-20251001", temperature=0.0)
        response = llm.complete_text(
            system_prompt=_BASELINE_SUMMARY_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
    except Exception:
        logger.exception("Baseline summary LLM call failed; falling back to question text only.")
        return f'Baseline question: "{safe_question}".'

    response = (response or "").strip()
    if not response:
        return f'Baseline question: "{safe_question}".'
    return response[:4000]
