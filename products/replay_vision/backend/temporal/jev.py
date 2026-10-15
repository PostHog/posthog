"""Yes/no questions to Jev, the self-hosted classifier the scan's post-checks ask."""

from typing import Any

import structlog

from products.ml_inference.backend.facade import api as decision_api
from products.ml_inference.backend.facade.contracts import DecisionQuestion, DecisionRequest
from products.ml_inference.backend.facade.enums import DecisionQuestionType

logger = structlog.get_logger(__name__)

JEV_MODEL = "posthog/hogference/jevk5-fp8-0.2"
_JEV_TIMEOUT_SECONDS = 10.0


def yes_probabilities(
    *, team_id: int, state: dict[str, Any], questions: dict[str, str], trace_id: str
) -> dict[str, float] | None:
    """P(yes) for each question keyed as given, or None when Jev is unavailable or errors."""
    if not decision_api.decisions_available_here():
        return None
    try:
        result = decision_api.decide_when_available(
            DecisionRequest(
                team_id=team_id,
                state=state,
                questions={
                    key: DecisionQuestion(type=DecisionQuestionType.NOUL, instructions=instructions)
                    for key, instructions in questions.items()
                },
                model=JEV_MODEL,
                ai_product="replay_vision",
                trace_id=trace_id,
                # The state is recording-derived, which stays out of the internal AI observability project.
                privacy_mode=True,
            ),
            timeout_seconds=_JEV_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.warning("replay_vision.jev.unavailable", team_id=team_id, exc_info=True)
        return None
    probabilities: dict[str, float] = {}
    for key in questions:
        probability = getattr(result.answers.get(key), "probability", None)
        if isinstance(probability, float | int):
            probabilities[key] = float(probability)
    return probabilities
