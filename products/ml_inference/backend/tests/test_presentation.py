from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from rest_framework import status

from products.ml_inference.backend.facade.contracts import (
    ChoiceAnswer,
    DecisionGatewayError,
    DecisionResult,
    DecisionsDisabledError,
    NoulAnswer,
)
from products.ml_inference.backend.presentation.serializers import DecideRequestSerializer

QUESTIONS = {
    "urgent": {"type": "noul", "instructions": "Is this urgent?"},
    "queue": {"type": "choice", "instructions": "Which team?", "criteria": {"billing": "money", "support": "product"}},
}


class TestDecideRequestValidation(SimpleTestCase):
    def test_rejects_an_unknown_question_type(self) -> None:
        serializer = DecideRequestSerializer(
            data={"state": "text", "questions": {"q": {"type": "essay", "instructions": "Write one"}}}
        )

        assert not serializer.is_valid()
        assert "questions" in serializer.errors

    def test_defaults_the_model(self) -> None:
        serializer = DecideRequestSerializer(data={"state": "text", "questions": QUESTIONS})

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["model"] == "posthog/posthog/decision-4b"


class TestDecideEndpoint(APIBaseTest):
    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/ml_inference/decisions/decide/"

    @patch("products.ml_inference.backend.presentation.views.api.decide")
    def test_returns_typed_answers(self, decide) -> None:
        decide.return_value = DecisionResult(
            model="kev-4b",
            answers={
                "urgent": NoulAnswer(probability=0.94),
                "queue": ChoiceAnswer(
                    choice="billing", confidence=0.94, probabilities={"billing": 0.97, "support": 0.03}
                ),
            },
            input_tokens=50,
            latency_ms=31,
        )

        response = self.client.post(self._url(), {"state": "charged twice", "questions": QUESTIONS}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert body["answers"]["urgent"] == {
            "type": "noul",
            "probability": 0.94,
            "choice": None,
            "score": None,
            "confidence": None,
            "probabilities": None,
        }
        assert body["answers"]["queue"]["choice"] == "billing"
        assert body["input_tokens"] == 50
        sent = decide.call_args.args[0]
        assert sent.team_id == self.team.id
        assert sent.questions["queue"].criteria == {"billing": "money", "support": "product"}

    @patch("products.ml_inference.backend.presentation.views.api.decide", side_effect=DecisionsDisabledError(1))
    def test_hides_the_route_when_decisions_are_off(self, _decide) -> None:
        response = self.client.post(self._url(), {"state": "text", "questions": QUESTIONS}, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @patch(
        "products.ml_inference.backend.presentation.views.api.decide",
        side_effect=DecisionGatewayError(422, "bad state"),
    )
    @patch("products.ml_inference.backend.presentation.views.api.decisions_enabled", return_value=True)
    def test_reports_a_model_refusal_as_a_bad_gateway(self, _enabled, _decide) -> None:
        response = self.client.post(self._url(), {"state": "text", "questions": QUESTIONS}, format="json")

        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert "bad state" in response.json()["detail"]

    def test_rejects_a_malformed_body_before_calling_the_model(self) -> None:
        response = self.client.post(self._url(), {"state": "text"}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
