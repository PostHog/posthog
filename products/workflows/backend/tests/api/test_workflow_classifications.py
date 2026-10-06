from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

import httpx
from parameterized import parameterized
from rest_framework.response import Response

from posthog.jwt import PosthogJwtAudience, encode_jwt

from products.workflows.backend.models import HogFlow
from products.workflows.backend.presentation.views.workflow_classifications import (
    WorkflowClassificationRequestSerializer,
)

SECRET = "test-workflow-classification-key"
LABELS = {"positive": "Positive sentiment", "negative": "Negative sentiment"}
PAYLOAD = {"text": "I like this feature.", "instructions": "Choose the sentiment.", "labels": LABELS}


class TestClassificationValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("one_label", {**PAYLOAD, "labels": {"only": "Only label"}}),
            ("too_many_labels", {**PAYLOAD, "labels": {str(i): "label" for i in range(17)}}),
            ("blank_label", {**PAYLOAD, "labels": {" ": "Blank", "valid": "Valid"}}),
            ("oversize_utf8", {**PAYLOAD, "text": "é" * 4097}),
        ]
    )
    def test_rejects_invalid_model_inputs(self, _name: str, payload: dict[str, object]) -> None:
        serializer = WorkflowClassificationRequestSerializer(data=payload)
        assert not serializer.is_valid()


@override_settings(
    DEBUG=True,
    WORKFLOW_CLASSIFICATION_JWT_SECRETS=[SECRET],
    AI_GATEWAY_URL="https://gateway.example.com/v1",
    AI_GATEWAY_API_KEY="fake-gateway-key",
)
class TestWorkflowClassificationsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.client.logout()
        self.flow = HogFlow.objects.create(team=self.team, name="Sentiment classification")
        self.flow_id = str(self.flow.id)
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])

    def _post(self, *, team_id: int | None = None, payload: dict[str, object] | None = None) -> Response:
        token = encode_jwt(
            {"team_id": self.team.id, "hog_flow_id": self.flow_id},
            timedelta(minutes=5),
            PosthogJwtAudience.WORKFLOW_CLASSIFICATION,
            signing_key=SECRET,
        )
        return self.client.post(
            f"/api/projects/{team_id or self.team.id}/workflow_classifications/",
            payload if payload is not None else PAYLOAD,
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

    def test_classifies_with_customer_text_separate_from_instructions_and_privacy_enabled(self) -> None:
        with patch("httpx.Client.post") as gateway:
            gateway.return_value = httpx.Response(
                200,
                json={
                    "model": "jevk5-0.2",
                    "usage": {"input_tokens": 12},
                    "answers": {
                        "classification": {
                            "choice": "positive",
                            "confidence": 0.9,
                            "probabilities": {"positive": 0.9, "negative": 0.1},
                        }
                    },
                },
            )
            response = self._post()
        assert response.status_code == 200, response.json()
        assert response.json() == {
            "label": "positive",
            "confidence": 0.9,
            "probabilities": {"positive": 0.9, "negative": 0.1},
        }
        call = gateway.call_args.kwargs
        assert call["json"]["state"] == {"text": PAYLOAD["text"]}
        assert PAYLOAD["text"] not in call["json"]["questions"]["classification"]["instructions"]
        assert call["headers"]["X-PostHog-Privacy-Mode"] == "true"

    @parameterized.expand([("other_team", 401), ("deleted_workflow", 422), ("consent", 403), ("invalid_input", 400)])
    def test_rejects_before_calling_the_model(self, case: str, expected_status: int) -> None:
        if case == "deleted_workflow":
            self.flow.delete()
        if case == "consent":
            self.organization.is_ai_data_processing_approved = False
            self.organization.save(update_fields=["is_ai_data_processing_approved"])
        with patch("httpx.Client.post") as gateway:
            response = self._post(
                team_id=self.team.id + 1 if case == "other_team" else None,
                payload={**PAYLOAD, "labels": {"only": "One"}} if case == "invalid_input" else None,
            )
        assert response.status_code == expected_status, response.json()
        gateway.assert_not_called()

    @parameterized.expand(
        [
            (
                "unknown_label",
                {"choice": "other", "confidence": 0.9, "probabilities": {"positive": 0.9, "negative": 0.1}},
            ),
            (
                "invalid_probability",
                {"choice": "positive", "confidence": 1.1, "probabilities": {"positive": 0.9, "negative": 0.1}},
            ),
            (
                "missing_label_probability",
                {"choice": "positive", "confidence": 0.9, "probabilities": {"positive": 0.9}},
            ),
        ]
    )
    def test_refuses_invalid_gateway_answers(self, _name: str, answer: dict[str, object]) -> None:
        with patch("httpx.Client.post") as gateway:
            gateway.return_value = httpx.Response(
                200, json={"model": "jevk5-0.2", "usage": {"input_tokens": 12}, "answers": {"classification": answer}}
            )
            response = self._post()
        assert response.status_code == 502, response.json()
        assert response.json() == {"detail": "JEV could not classify this text."}
