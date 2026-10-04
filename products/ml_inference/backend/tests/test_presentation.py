from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from products.ml_inference.backend.facade.contracts import (
    ChoiceAnswer,
    DecisionGatewayError,
    DecisionGatewayUnreachableError,
    DecisionResult,
    DecisionsDisabledError,
    NoulAnswer,
)

QUESTIONS = {
    "urgent": {"type": "noul", "instructions": "Is this urgent?"},
    "queue": {"type": "choice", "instructions": "Which team?", "criteria": {"billing": "money", "support": "product"}},
}


class TestDecideEndpoint(APIBaseTest):
    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/ml_inference/decisions/decide/"

    @parameterized.expand([(False, "US"), (False, "EU"), (True, None)])
    def test_requires_current_organization_consent_before_calling_the_model(
        self, debug: bool, deployment: str | None
    ) -> None:
        with (
            override_settings(DEBUG=debug, CLOUD_DEPLOYMENT=deployment),
            patch("products.ml_inference.backend.logic.decisions.posthoganalytics.feature_enabled", return_value=True),
            patch("products.ml_inference.backend.logic.decisions.decide") as decide,
        ):
            decide.return_value = DecisionResult(
                model="test", answers={"urgent": NoulAnswer(probability=0.9)}, input_tokens=1
            )
            for consent in (None, False, True, False):
                self.organization.is_ai_data_processing_approved = consent
                self.organization.save(update_fields=["is_ai_data_processing_approved"])
                decide.reset_mock()

                response = self.client.post(self._url(), {"state": "text", "questions": QUESTIONS}, format="json")

                assert response.status_code == (status.HTTP_200_OK if consent else status.HTTP_404_NOT_FOUND)
                assert decide.call_count == int(bool(consent))

    @patch("products.ml_inference.backend.presentation.views.api.decide")
    def test_returns_typed_answers(self, decide) -> None:
        decide.return_value = DecisionResult(
            model="jevk5-0.2",
            answers={
                "urgent": NoulAnswer(probability=0.94),
                "queue": ChoiceAnswer(
                    choice="billing", confidence=0.94, probabilities={"billing": 0.97, "support": 0.03}
                ),
            },
            input_tokens=50,
            latency_ms=31.5,
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
        assert body["latency_ms"] == 31.5
        sent = decide.call_args.args[0]
        assert sent.team_id == self.team.id
        assert sent.distinct_id == self.user.distinct_id
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
        assert "bad state" not in response.json()["detail"]

    @patch(
        "products.ml_inference.backend.presentation.views.api.decide",
        side_effect=DecisionGatewayUnreachableError("decision gateway unreachable: ConnectError"),
    )
    @patch("products.ml_inference.backend.presentation.views.api.decisions_enabled", return_value=True)
    def test_reports_an_unreachable_gateway_as_unavailable(self, _enabled, _decide) -> None:
        response = self.client.post(self._url(), {"state": "text", "questions": QUESTIONS}, format="json")

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    def test_rejects_a_malformed_body_before_calling_the_model(self) -> None:
        response = self.client.post(self._url(), {"state": "text"}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
