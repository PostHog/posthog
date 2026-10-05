from datetime import timedelta
from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.llm.system_one import (
    ChoiceAnswer,
    ChoiceQuestion,
    SystemOneNotConfigured,
    SystemOneRequestFailed,
    SystemOneResult,
)

SECRET = "test-workflow-ai-decision-jwt"
_BUILD = "products.workflows.backend.presentation.views.workflow_ai_decisions.build_system_one_client"
OPTIONS = {"spam": "Cold outreach or marketing", "support": "A customer asking for help"}


def _token(team_id: int, audience: PosthogJwtAudience = PosthogJwtAudience.WORKFLOW_AI_DECISION) -> str:
    return encode_jwt(
        {"team_id": team_id, "hog_flow_id": str(uuid4())}, timedelta(minutes=5), audience, signing_key=SECRET
    )


@override_settings(WORKFLOW_AI_DECISION_JWT_SECRETS=[SECRET], TASKS_CREATE_JWT_SECRETS=[SECRET])
class TestWorkflowAiDecisionsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.client.logout()
        self.url = f"/api/projects/{self.team.id}/workflow_ai_decisions/"

    def _post(self, body: dict | None = None, token: str | None = None) -> Any:
        return self.client.post(
            self.url,
            {
                "question": "Is this ticket spam?",
                "context": {"subject": "Buy SEO"},
                "options": OPTIONS,
                **(body or {}),
            },
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token or _token(self.team.id)}",
        )

    def test_returns_the_chosen_option(self) -> None:
        client = MagicMock()
        client.decide.return_value = SystemOneResult(
            model="jevk5",
            answers={
                "decision": ChoiceAnswer(choice="spam", confidence=0.9, probabilities={"spam": 0.9, "support": 0.1})
            },
            input_tokens=20,
        )
        with patch(_BUILD, return_value=client) as build:
            response = self._post()

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {"decision": "spam", "confidence": 0.9}
        # No TypeSafe fallback, so the data never leaves PostHog.
        assert "typesafe_fallback" not in build.call_args.kwargs
        assert build.call_args.kwargs["ai_product"] == "workflows"
        assert build.call_args.kwargs["properties"]["team_id"] == str(self.team.id)
        # User text stays in the state, never in the instructions.
        client.decide.assert_called_once_with(
            state={"subject": "Buy SEO"},
            questions={"decision": ChoiceQuestion(instructions="Is this ticket spam?", criteria=OPTIONS)},
        )

    @parameterized.expand(
        [
            ("not_configured", SystemOneNotConfigured(), None, status.HTTP_501_NOT_IMPLEMENTED),
            ("rate_limited", None, SystemOneRequestFailed("429", status_code=429), status.HTTP_503_SERVICE_UNAVAILABLE),
            ("unreachable", None, SystemOneRequestFailed("down"), status.HTTP_503_SERVICE_UNAVAILABLE),
            (
                "gateway_error",
                None,
                SystemOneRequestFailed("503", status_code=503),
                status.HTTP_503_SERVICE_UNAVAILABLE,
            ),
            ("bad_request", None, SystemOneRequestFailed("400", status_code=400), status.HTTP_422_UNPROCESSABLE_ENTITY),
        ]
    )
    def test_a_model_failure_maps_onto_a_status_the_step_can_retry_or_fail_on(
        self, _name: str, build_error: Exception | None, decide_error: Exception | None, expected: int
    ) -> None:
        client = MagicMock()
        client.decide.side_effect = decide_error
        with patch(_BUILD, return_value=client, side_effect=build_error):
            response = self._post()

        assert response.status_code == expected

    def test_refuses_an_organization_without_ai_data_processing_approval(self) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()
        with patch(_BUILD) as build:
            response = self._post()

        assert response.status_code == status.HTTP_403_FORBIDDEN
        build.assert_not_called()

    @parameterized.expand(
        [
            ("one_option", {"options": {"spam": "Spam"}}),
            ("too_many_options", {"options": {f"c{i}": "x" for i in range(17)}}),
            ("oversized_context", {"context": {"message": "x" * 65_536}}),
        ]
    )
    def test_rejects_inputs_the_model_cannot_answer(self, _name: str, body: dict) -> None:
        with patch(_BUILD) as build:
            response = self._post(body)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        build.assert_not_called()

    def test_rejects_a_token_minted_for_another_workflow_action(self) -> None:
        response = self._post(token=_token(self.team.id, audience=PosthogJwtAudience.TASKS_CREATE))

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
