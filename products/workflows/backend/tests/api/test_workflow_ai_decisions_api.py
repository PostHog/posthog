from datetime import timedelta
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status
from structlog.testing import capture_logs

from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.llm.gateway_client import GatewayNotConfiguredError
from posthog.redis import get_client
from posthog.token_bucket import BucketUnavailable

from products.ml_inference.backend.facade.contracts import (
    ChoiceAnswer,
    DecisionGatewayError,
    DecisionGatewayUnreachableError,
    DecisionQuestion,
    DecisionResult,
    DecisionsDisabledError,
    NoulAnswer,
)
from products.ml_inference.backend.facade.enums import DecisionQuestionType

SECRET = "test-workflow-ai-decision-jwt"
_DECIDE = "products.ml_inference.backend.facade.api.decide_when_available"
_FLAG = "posthoganalytics.feature_enabled"
_CREDITS = "ee.billing.quota_limiting.is_team_over_ai_credit_budget"
_CONSUME = "products.workflows.backend.services.ai_decision.consume"
OPTIONS = [
    {"name": "spam", "description": "Cold outreach or marketing"},
    {"name": "support", "description": "A customer asking for help"},
]


def _token(
    team_id: int,
    audience: PosthogJwtAudience = PosthogJwtAudience.WORKFLOW_AI_DECISION,
    hog_flow_id: str | None = "flow-1",
) -> str:
    claims: dict[str, Any] = {"team_id": team_id}
    if hog_flow_id is not None:
        claims["hog_flow_id"] = hog_flow_id
    return encode_jwt(claims, timedelta(minutes=5), audience, signing_key=SECRET)


def _pick_one_result() -> DecisionResult:
    return DecisionResult(
        model="posthog/hogference/jevk5-fp8-0.2",
        answers={"answer": ChoiceAnswer(choice="spam", confidence=0.9, probabilities={"spam": 0.8, "support": 0.2})},
        input_tokens=20,
    )


@override_settings(WORKFLOW_AI_DECISION_JWT_SECRETS=[SECRET], TASKS_CREATE_JWT_SECRETS=[SECRET])
class TestWorkflowAIDecisionsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.client.logout()
        self.url = f"/api/projects/{self.team.id}/workflow_ai_decisions/"
        flag = patch(_FLAG, return_value=True)
        self.flag = flag.start()
        self.addCleanup(flag.stop)
        get_client().flushdb()

    def _post(self, body: dict | None = None, token: str | None = None) -> Any:
        return self.client.post(
            self.url,
            {
                "invocation_id": "inv-1",
                "action_id": "action-1",
                "answer_type": "pick_one",
                "question": "Is this ticket spam?",
                "options": OPTIONS,
                "state": {"subject": "Buy SEO"},
                **(body or {}),
            },
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token or _token(self.team.id)}",
        )

    def test_pick_one_returns_every_option_probability(self) -> None:
        with patch(_DECIDE, return_value=_pick_one_result()) as decide:
            response = self._post()

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {
            "status": "succeeded",
            "probabilities": {"spam": 0.8, "support": 0.2},
            "model": "posthog/hogference/jevk5-fp8-0.2",
            "input_tokens": 20,
        }
        request = decide.call_args.args[0]
        assert request.team_id == self.team.id
        assert request.ai_product == "workflows"
        assert request.privacy_mode is True
        assert request.trace_id == "inv-1"
        assert request.properties == {"hog_flow_id": "flow-1", "action_id": "action-1"}
        assert request.state == {"subject": "Buy SEO"}
        assert request.questions == {
            "answer": DecisionQuestion(
                type=DecisionQuestionType.CHOICE,
                instructions="Is this ticket spam?",
                criteria={"spam": "Cold outreach or marketing", "support": "A customer asking for help"},
            )
        }
        assert decide.call_args.kwargs == {"timeout_seconds": 5}

    def test_yes_no_returns_yes_and_no_probabilities(self) -> None:
        result = DecisionResult(model="jev", answers={"answer": NoulAnswer(probability=0.75)}, input_tokens=9)
        with patch(_DECIDE, return_value=result) as decide:
            response = self._post(
                {"answer_type": "yes_no", "options": [], "yes_means": "A real company", "no_means": "A free mailbox"}
            )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["probabilities"] == {"yes": 0.75, "no": 0.25}
        assert decide.call_args.args[0].questions == {
            "answer": DecisionQuestion(
                type=DecisionQuestionType.NOUL,
                instructions="Is this ticket spam?",
                criteria={"true": "A real company", "false": "A free mailbox"},
            )
        }

    def test_a_test_run_of_an_unsaved_workflow_has_no_workflow_label(self) -> None:
        with patch(_DECIDE, return_value=_pick_one_result()) as decide:
            response = self._post(token=_token(self.team.id, hog_flow_id=None))

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert decide.call_args.args[0].properties == {"action_id": "action-1"}

    def test_rejects_a_token_minted_for_another_workflow_action(self) -> None:
        response = self._post(token=_token(self.team.id, audience=PosthogJwtAudience.TASKS_CREATE))

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @parameterized.expand(
        [
            ("flag_off", 0, "feature_unavailable"),
            ("ai_processing_not_approved", 1, "ai_processing_not_approved"),
            ("out_of_ai_credits", 2, "quota_exceeded"),
            ("state_too_large", 3, "state_too_large"),
        ]
    )
    def test_the_first_closed_gate_fails_the_decision_without_asking_the_model(
        self, _name: str, first_closed_gate: int, expected_code: str
    ) -> None:
        self.flag.return_value = first_closed_gate > 0
        if first_closed_gate <= 1:
            self.organization.is_ai_data_processing_approved = False
            self.organization.save()
        with (
            patch(_CREDITS, return_value=first_closed_gate <= 2),
            patch(_DECIDE) as decide,
        ):
            response = self._post({"state": {"reply": "x" * 9000}})

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["status"] == "failed"
        assert response.json()["error"]["code"] == expected_code
        assert response.json()["error"]["message"]
        decide.assert_not_called()

    @parameterized.expand(
        [
            ("ascii_at_the_cap", "a" * 8184, "succeeded"),
            ("two_byte_characters_over_the_cap", "é" * 4093, "failed"),
        ]
    )
    def test_the_state_cap_counts_compact_utf8_bytes(self, _name: str, value: str, expected_outcome: str) -> None:
        with patch(_DECIDE, return_value=_pick_one_result()):
            response = self._post({"state": {"t": value}})

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["status"] == expected_outcome

    @parameterized.expand(
        [
            ("region_without_decisions", DecisionsDisabledError(1), status.HTTP_200_OK, "feature_unavailable"),
            ("gateway_not_configured", GatewayNotConfiguredError("unset"), status.HTTP_200_OK, "gateway_unavailable"),
            ("gateway_out_of_credits", DecisionGatewayError(402, "no credits"), status.HTTP_200_OK, "quota_exceeded"),
            ("gateway_bad_request", DecisionGatewayError(400, "bad"), status.HTTP_200_OK, "model_refused"),
            ("gateway_too_large", DecisionGatewayError(413, "big"), status.HTTP_200_OK, "model_refused"),
            ("gateway_unprocessable", DecisionGatewayError(422, "no"), status.HTTP_200_OK, "model_refused"),
            ("gateway_rate_limited", DecisionGatewayError(429, "slow down"), status.HTTP_429_TOO_MANY_REQUESTS, None),
            ("gateway_server_error", DecisionGatewayError(502, "oops"), status.HTTP_503_SERVICE_UNAVAILABLE, None),
            ("gateway_timeout", DecisionGatewayUnreachableError("timeout"), status.HTTP_503_SERVICE_UNAVAILABLE, None),
        ]
    )
    def test_a_gateway_failure_maps_onto_the_status_contract(
        self, _name: str, error: Exception, expected_status: int, expected_code: str | None
    ) -> None:
        with patch(_DECIDE, side_effect=error):
            response = self._post()

        assert response.status_code == expected_status, response.json()
        if expected_code is not None:
            assert response.json()["error"]["code"] == expected_code
        if expected_status == status.HTTP_429_TOO_MANY_REQUESTS:
            assert int(response["Retry-After"]) > 0

    @override_settings(WORKFLOWS_AI_DECISION_TEAM_BURST=1, WORKFLOWS_AI_DECISION_TEAM_PER_HOUR=1)
    def test_a_team_over_its_admission_budget_is_told_when_to_retry(self) -> None:
        with patch(_DECIDE, return_value=_pick_one_result()) as decide:
            first = self._post()
            second = self._post()

        assert first.status_code == status.HTTP_200_OK, first.json()
        assert second.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert int(second["Retry-After"]) > 0
        assert decide.call_count == 1

    def test_admission_fails_closed_when_redis_is_unavailable(self) -> None:
        with (
            patch(_CONSUME, return_value=BucketUnavailable(error="down")),
            patch(_DECIDE) as decide,
        ):
            response = self._post()

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        decide.assert_not_called()

    def test_logs_never_carry_the_state_or_a_gateway_body(self) -> None:
        with capture_logs() as logs, patch(_DECIDE, side_effect=DecisionGatewayError(400, "gateway-body-secret")):
            response = self._post({"state": {"reply": "state-secret"}})

        assert response.json()["error"]["code"] == "model_refused"
        assert logs
        assert "secret" not in str(logs)
        assert "secret" not in str(response.json())
