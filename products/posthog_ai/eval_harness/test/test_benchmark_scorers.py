import pytest

from products.business_knowledge.evals.eval_retrieval import RetrievalMatch
from products.posthog_ai.backend.turn_suggestions.benchmark import Outcome
from products.posthog_ai.evals.turn_suggestions.eval_turn_suggestions import OfferCorrectness


@pytest.mark.parametrize(
    "outcome,score",
    [
        (Outcome.CORRECT, 1.0),
        (Outcome.EITHER, 1.0),
        (Outcome.FALSE_OFFER, 0.0),
        (Outcome.MISSED, 0.0),
        (Outcome.WRONG_KIND, 0.0),
        (Outcome.FAILED, None),
    ],
)
def test_offer_correctness_preserves_benchmark_outcomes(outcome: Outcome, score: float | None) -> None:
    result = OfferCorrectness().eval({"outcome": outcome, "error": "judge unavailable"})
    assert result.score == score
    if outcome == Outcome.FAILED:
        assert result.result is not None
        assert result.result.status == "error"
        assert result.result.error_code == "judge_error"
        assert result.result.error_message == "judge unavailable"
    else:
        assert result.result is None


@pytest.mark.parametrize("found,expected,score", [(True, True, 1.0), (False, False, 1.0), (False, True, 0.0)])
def test_retrieval_scores_absence_as_a_valid_outcome(found: bool, expected: bool, score: float) -> None:
    result = RetrievalMatch().eval(
        {"found": found, "source_names": ["Refund Policy"] if found else []},
        {"retrieval_match": {"found": expected}},
    )
    assert result.score == score
