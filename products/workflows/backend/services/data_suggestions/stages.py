"""Ask Jev, the decision model, which customer lifecycle stage each candidate event marks."""

import json
from collections.abc import Sequence
from typing import cast, get_args

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.llm.gateway_client import team_distinct_id
from posthog.llm.managed_decision_model import ManagedDecisionModel
from posthog.llm.system_one import ChoiceAnswer, ChoiceQuestion, SystemOneNotConfigured, SystemOneRequestFailed
from posthog.llm.system_one_client import GATEWAY_MAX_QUESTIONS, build_system_one_client

from products.workflows.backend.services.data_suggestions.ranking import LifecycleStage

logger = structlog.get_logger(__name__)

STAGE_MODEL = ManagedDecisionModel("workflows-data-suggestion-stages")
# Below this the answer is a guess, and a wrong high-weight stage would push noise above real moments.
MIN_CONFIDENCE = 0.5
MAX_CLASSIFIED_EVENTS = GATEWAY_MAX_QUESTIONS * 3
_TIMEOUT_SECONDS = 15.0

STAGE_CRITERIA: dict[str, str] = {
    "signup": "A new account or user is created, or someone registers.",
    "onboarding": "A first step after sign-up: setup, activation, a first key action, or inviting teammates.",
    "trial": "A trial starts, is used, or is about to end.",
    "purchase": "Someone pays, upgrades, subscribes, orders or checks out.",
    "churn_risk": "Someone cancels, downgrades, unsubscribes, deletes their account or goes inactive.",
    "failure": "Something went wrong for the user, such as an error, a failed payment or a failed action.",
    "support": "A support ticket, a survey answer or other feedback.",
    "other": "Routine product usage or a technical event that marks none of the moments above.",
}


def classify_event_stages(*, team_id: int, event_names: Sequence[str]) -> dict[str, LifecycleStage]:
    """The stage Jev picks for each event it answers with enough confidence. Empty when Jev is unavailable,
    so callers fall back to their own guess."""
    names = list(event_names)[:MAX_CLASSIFIED_EVENTS]
    if not names:
        return {}
    try:
        # Without team_id the gateway bills PostHog, so the classification never draws on the customer's credits.
        client = build_system_one_client(
            model=STAGE_MODEL.current(),
            ai_product="workflows",
            distinct_id=team_distinct_id(team_id),
            properties={"ai_feature": "data_suggestion_stages"},
            timeout=_TIMEOUT_SECONDS,
        )
    except SystemOneNotConfigured:
        return {}

    stages: dict[str, LifecycleStage] = {}
    valid_stages = set(get_args(LifecycleStage))
    for start in range(0, len(names), GATEWAY_MAX_QUESTIONS):
        chunk = names[start : start + GATEWAY_MAX_QUESTIONS]
        questions = {
            f"e{index}": ChoiceQuestion(
                instructions=(
                    "Which customer lifecycle stage does the product analytics event named "
                    f"{json.dumps(name)} mark? Judge only from the name."
                ),
                criteria=STAGE_CRITERIA,
            )
            for index, name in enumerate(chunk)
        }
        try:
            result = client.decide(state={"event_names": chunk}, questions=questions)
        except SystemOneRequestFailed as error:
            logger.warning(
                "workflows.data_suggestions.stage_classification_failed",
                team_id=team_id,
                status_code=error.status_code,
            )
            capture_exception(error, {"team_id": team_id, "chunk_size": len(chunk)})
            continue
        for index, name in enumerate(chunk):
            answer = result.answers.get(f"e{index}")
            if isinstance(answer, ChoiceAnswer) and answer.choice in valid_stages:
                stages[name] = cast(LifecycleStage, answer.choice) if answer.confidence >= MIN_CONFIDENCE else "other"
    return stages
