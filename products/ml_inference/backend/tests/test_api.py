import pytest
from unittest.mock import patch

from products.ml_inference.backend.facade import api
from products.ml_inference.backend.facade.contracts import (
    DecisionQuestion,
    DecisionRequest,
    DecisionResult,
    DecisionsDisabledError,
)
from products.ml_inference.backend.facade.enums import DecisionQuestionType


def _request() -> DecisionRequest:
    return DecisionRequest(
        team_id=7,
        state="text",
        questions={"q": DecisionQuestion(type=DecisionQuestionType.NOUL, instructions="Really?")},
    )


class TestDecideFacade:
    @patch("products.ml_inference.backend.logic.decisions.decide")
    @patch("products.ml_inference.backend.logic.decisions.decisions_enabled", return_value=False)
    def test_refuses_an_unenrolled_team_before_calling_the_gateway(self, _enabled, decide) -> None:
        with pytest.raises(DecisionsDisabledError):
            api.decide(_request())

        decide.assert_not_called()

    @patch("products.ml_inference.backend.logic.decisions.decide")
    @patch("products.ml_inference.backend.logic.decisions.decisions_enabled", return_value=False)
    def test_unchecked_path_skips_enrollment(self, _enabled, decide) -> None:
        decide.return_value = DecisionResult(model="kev-4b", answers={}, input_tokens=1)

        assert api.decide_unchecked(_request()).model == "kev-4b"
