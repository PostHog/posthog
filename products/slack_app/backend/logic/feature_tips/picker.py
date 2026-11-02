"""Which feature a tip promotes, when more than one is a candidate.

Jev, a System One decision model, reads the person's message and picks the feature that fits it,
or ``none``. Below the confidence threshold, on ``none``, or on any failure, the candidate with
the lowest rank wins. A tip does not have to match the message, so the model only orders the
candidates and never decides whether a tip goes out.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

import structlog

from posthog.dataclasses import frozen
from posthog.llm.managed_decision_model import DEFAULT_DECISION_MODEL
from posthog.llm.system_one import ChoiceAnswer, ChoiceQuestion
from posthog.llm.system_one_client import GATEWAY_MAX_CHOICE_OPTIONS, build_system_one_client

from products.slack_app.backend.logic.feature_tips.catalog import TipFeature
from products.slack_app.backend.logic.feature_tips.features import SlackFeature
from products.slack_app.backend.temporal.activities.classifiers import CLASSIFIER_PROPERTY

logger = structlog.get_logger(__name__)

FEATURE_TIP_DECISION_MODEL = DEFAULT_DECISION_MODEL
# Not the `slack_app` product the other classifiers bill under: a tip promotes PostHog, so it
# must not spend the team's AI credits.
FEATURE_TIP_AI_PRODUCT = "slack_app_feature_tip"
# The answer is already in the thread. A slow call only delays the tip, so it is not worth waiting for.
FEATURE_TIP_TIMEOUT_SECONDS = 5.0
# Tuned in products/slack_app/evals/eval_feature_tip_picker.py.
FEATURE_TIP_MIN_CONFIDENCE = 0.6
FEATURE_TIP_QUESTION_ID = "feature_tip"
NO_FEATURE = "none"
# The model needs the request, not the whole message. This also keeps pasted logs out of the call.
FEATURE_TIP_MESSAGE_MAX_CHARS = 500
# `none` takes one of the options the gateway accepts.
FEATURE_TIP_MAX_CANDIDATES = GATEWAY_MAX_CHOICE_OPTIONS - 1

FEATURE_TIP_INSTRUCTIONS = (
    "`message` is what a person asked the PostHog assistant in Slack. "
    "Pick the assistant feature that would help this person most with this kind of request. "
    "Pick `none` when no feature in the list relates to the message. "
    "Do not pick a feature only because it is generally useful."
)
NO_FEATURE_CRITERIA = "No feature in the list relates to what the message asks for."


@frozen
class FeatureTipVerdict:
    choice: str
    confidence: float


@frozen
class TipChoice:
    feature: SlackFeature
    source: Literal["contextual", "ranked"]
    confidence: float | None = None


def classify_feature_tip(
    message: str,
    candidates: Sequence[TipFeature],
    *,
    team_id: int,
    distinct_id: str | None,
    trace_id: str | None = None,
) -> FeatureTipVerdict | None:
    """Ask the decision model which candidate fits the message. ``None`` means no verdict.

    Raises when no System One server is configured or the call fails, so the caller can tell
    an outage from a refusal.
    """
    text = message.strip()[:FEATURE_TIP_MESSAGE_MAX_CHARS]
    if not text or not candidates:
        return None
    candidates = sorted(candidates, key=lambda tip: tip.rank)[:FEATURE_TIP_MAX_CANDIDATES]
    # No TypeSafe fallback: the message is customer text, and TypeSafe is a third party.
    client = build_system_one_client(
        model=FEATURE_TIP_DECISION_MODEL,
        ai_product=FEATURE_TIP_AI_PRODUCT,
        team_id=team_id,
        distinct_id=distinct_id,
        trace_id=trace_id,
        properties={CLASSIFIER_PROPERTY: "feature_tip"},
        timeout=FEATURE_TIP_TIMEOUT_SECONDS,
    )
    result = client.decide(
        state={"message": text},
        questions={
            FEATURE_TIP_QUESTION_ID: ChoiceQuestion(
                instructions=FEATURE_TIP_INSTRUCTIONS,
                criteria={
                    **{tip.feature.value: tip.choice_criteria for tip in candidates},
                    NO_FEATURE: NO_FEATURE_CRITERIA,
                },
            )
        },
    )
    answer = result.answers.get(FEATURE_TIP_QUESTION_ID)
    if not isinstance(answer, ChoiceAnswer):
        logger.info("slack_app_feature_tip_refused")
        return None
    return FeatureTipVerdict(choice=answer.choice, confidence=answer.confidence)


def choose_tip(
    candidates: Sequence[TipFeature],
    message: str | None,
    *,
    team_id: int,
    distinct_id: str | None,
    trace_id: str | None = None,
) -> TipChoice | None:
    if not candidates:
        return None
    ranked = min(candidates, key=lambda tip: tip.rank)
    if len(candidates) == 1 or not message:
        return TipChoice(feature=ranked.feature, source="ranked")
    try:
        verdict = classify_feature_tip(message, candidates, team_id=team_id, distinct_id=distinct_id, trace_id=trace_id)
    except Exception:
        logger.warning("slack_app_feature_tip_classifier_failed", exc_info=True)
        verdict = None
    by_value = {tip.feature.value: tip for tip in candidates}
    if verdict is not None and verdict.choice in by_value and verdict.confidence >= FEATURE_TIP_MIN_CONFIDENCE:
        return TipChoice(feature=by_value[verdict.choice].feature, source="contextual", confidence=verdict.confidence)
    return TipChoice(
        feature=ranked.feature,
        source="ranked",
        confidence=verdict.confidence if verdict is not None else None,
    )
