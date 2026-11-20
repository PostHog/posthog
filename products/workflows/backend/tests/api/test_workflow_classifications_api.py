import time
from datetime import timedelta
from functools import reduce
from typing import Any, cast
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.llm.gateway_client import GatewayNotConfiguredError
from posthog.test.authentication_checks import covers_authentication

from products.ml_inference.backend.facade.contracts import (
    DEFAULT_DECISION_MODEL,
    ChoiceAnswer,
    DecisionGatewayError,
    DecisionGatewayUnreachableError,
    DecisionQuestion,
    DecisionResult,
    DecisionsDisabledError,
    NoulAnswer,
)
from products.ml_inference.backend.facade.enums import DecisionQuestionType
from products.workflows.backend.presentation.views.workflow_classifications import WorkflowClassifyJWTAuthentication

from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, add_limited_team_tokens

SECRET = "test-workflow-classify-jwt"
_DECIDE = "products.ml_inference.backend.facade.api.decide_when_available"
CATEGORIES = {"spam": "Cold outreach or marketing", "support": "A customer asking for help"}


def _token(team_id: int, audience: PosthogJwtAudience = PosthogJwtAudience.WORKFLOW_CLASSIFY) -> str:
    return encode_jwt(
        {"team_id": team_id, "hog_flow_id": str(uuid4())}, timedelta(minutes=5), audience, signing_key=SECRET
    )


def _result(answer: Any) -> DecisionResult:
    return DecisionResult(model="jevk5", answers={"category": answer}, input_tokens=20)


@override_settings(WORKFLOW_CLASSIFY_JWT_SECRETS=[SECRET], TASKS_CREATE_JWT_SECRETS=[SECRET])
class TestWorkflowClassificationsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.client.logout()
        self.url = f"/api/projects/{self.team.id}/workflow_classifications/"
        flag_patch = patch("posthoganalytics.feature_enabled", return_value=True)
        self.feature_flag = flag_patch.start()
        self.addCleanup(flag_patch.stop)

    def _post(self, body: dict | None = None, token: str | None = None) -> Any:
        return self.client.post(
            self.url,
            {
                "question": "Is this ticket spam?",
                "context": {"subject": "Buy SEO"},
                "categories": CATEGORIES,
                **(body or {}),
            },
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token or _token(self.team.id)}",
        )

    @parameterized.expand(
        [
            ("disabled", False, None),
            ("unavailable", None, RuntimeError("Flag evaluation is unavailable")),
        ]
    )
    def test_refuses_classification_without_the_feature_flag(
        self, _name: str, enabled: bool | None, error: Exception | None
    ) -> None:
        self.feature_flag.return_value = enabled
        self.feature_flag.side_effect = error
        with patch(_DECIDE) as decide:
            response = self._post()

        assert response.status_code == status.HTTP_403_FORBIDDEN
        decide.assert_not_called()

    # The step sends a null model when the author never opened the picker.
    @parameterized.expand(
        [
            ("model_omitted", {}, DEFAULT_DECISION_MODEL),
            ("model_null", {"model": None}, DEFAULT_DECISION_MODEL),
            ("jev", {"model": "jev"}, DEFAULT_DECISION_MODEL),
        ]
    )
    @covers_authentication(WorkflowClassifyJWTAuthentication)
    def test_returns_the_chosen_category(self, _name: str, body: dict, expected_model: str) -> None:
        answer = ChoiceAnswer(choice="spam", confidence=0.9, probabilities={"spam": 0.9, "support": 0.1})
        with patch(_DECIDE, return_value=_result(answer)) as decide:
            response = self._post(body)

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {
            "category": "spam",
            "confidence": 0.9,
            "probabilities": {"spam": 0.9, "support": 0.1},
        }
        sent = decide.call_args.args[0]
        assert sent.team_id == self.team.id
        assert sent.privacy_mode is True
        assert sent.model == expected_model
        # User text stays in the state, never in the instructions.
        assert sent.state == {"subject": "Buy SEO"}
        assert sent.questions == {
            "category": DecisionQuestion(
                type=DecisionQuestionType.CHOICE, instructions="Is this ticket spam?", criteria=CATEGORIES
            )
        }

    @parameterized.expand(
        [
            ("unavailable_in_region", DecisionsDisabledError(1), status.HTTP_501_NOT_IMPLEMENTED),
            ("not_configured", GatewayNotConfiguredError("no gateway"), status.HTTP_501_NOT_IMPLEMENTED),
            ("rate_limited", DecisionGatewayError(429, "slow down"), status.HTTP_503_SERVICE_UNAVAILABLE),
            ("unreachable", DecisionGatewayUnreachableError("timeout"), status.HTTP_503_SERVICE_UNAVAILABLE),
            ("gateway_error", DecisionGatewayError(503, "down"), status.HTTP_503_SERVICE_UNAVAILABLE),
            ("malformed_answer", DecisionGatewayError(200, "unreadable"), status.HTTP_422_UNPROCESSABLE_ENTITY),
            ("bad_request", DecisionGatewayError(400, "bad"), status.HTTP_422_UNPROCESSABLE_ENTITY),
        ]
    )
    def test_a_model_failure_maps_onto_a_status_the_step_can_retry_or_fail_on(
        self, _name: str, error: Exception, expected: int
    ) -> None:
        with patch(_DECIDE, side_effect=error):
            response = self._post()

        assert response.status_code == expected

    @parameterized.expand(
        [
            (
                "unknown_category",
                ChoiceAnswer(choice="sales", confidence=0.9, probabilities={"spam": 0.1, "support": 0.0}),
            ),
            ("missing_probability", ChoiceAnswer(choice="spam", confidence=0.9, probabilities={"spam": 0.9})),
            ("out_of_range", ChoiceAnswer(choice="spam", confidence=1.5, probabilities={"spam": 0.9, "support": 0.1})),
            ("wrong_answer_type", NoulAnswer(probability=0.9)),
        ]
    )
    def test_fails_the_step_on_an_answer_it_cannot_branch_on(self, _name: str, answer: Any) -> None:
        with patch(_DECIDE, return_value=_result(answer)):
            response = self._post()

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_refuses_an_organization_without_ai_data_processing_approval(self) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()
        with patch(_DECIDE) as decide:
            response = self._post()

        assert response.status_code == status.HTTP_403_FORBIDDEN
        decide.assert_not_called()

    @parameterized.expand(
        [
            ("one_category", {"categories": {"spam": "Spam"}}),
            ("blank_category_name", {"categories": {" ": "Spam", "support": "Help"}}),
            ("long_category_name", {"categories": {"x" * 101: "Spam", "support": "Help"}}),
            ("too_many_categories", {"categories": {f"c{i}": "x" for i in range(17)}}),
            ("oversized_context", {"context": {"message": "x" * 65_536}}),
            ("unlisted_model", {"model": "openai/gpt-6-luna"}),
            ("hidden_model", {"model": "gpt-6-luna"}),
            ("deeply_nested_context", {"context": reduce(lambda inner, _: {"a": inner}, range(255), cast(Any, "x"))}),
        ]
    )
    def test_rejects_inputs_the_model_cannot_answer(self, _name: str, body: dict) -> None:
        with patch(_DECIDE) as decide:
            response = self._post(body)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        decide.assert_not_called()

    def test_rejects_a_token_minted_for_another_workflow_action(self) -> None:
        response = self._post(token=_token(self.team.id, audience=PosthogJwtAudience.TASKS_CREATE))

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_rejects_a_token_without_a_workflow_claim(self) -> None:
        token = encode_jwt(
            {"team_id": self.team.id}, timedelta(minutes=5), PosthogJwtAudience.WORKFLOW_CLASSIFY, signing_key=SECRET
        )
        with patch(_DECIDE) as decide:
            response = self._post(token=token)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        decide.assert_not_called()


_GATEWAY_POST = "products.tasks.backend.temporal.process_task.ai_gateway_token.requests.post"
_MINT_BACKOFF = "products.tasks.backend.temporal.process_task.ai_gateway_token.time.sleep"
_MINT_KEY = "phs_test_mint_key"
_EXPIRES_AT = "2026-11-20T12:30:00Z"


class _FakeGateway:
    def __init__(self, mint_status: int = 201, echo_capture_mode: bool = True) -> None:
        self.mint_status = mint_status
        self.echo_capture_mode = echo_capture_mode
        self.expires_at: str | None = _EXPIRES_AT
        self.revoke_status = 200
        self.mints: list[dict[str, Any]] = []
        self.revoked: list[str] = []

    def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str], **_kwargs: Any) -> Any:
        assert headers["Authorization"] == f"Bearer {_MINT_KEY}"
        if url == "https://gateway.example.com/v1/tokens/revoke":
            if self.revoke_status != 200:
                return _FakeResponse(self.revoke_status, {"error": "unavailable"})
            self.revoked.append(json["token"])
            return _FakeResponse(200, {"revoked": True})
        assert url == "https://gateway.example.com/v1/tokens"
        self.mints.append(json)
        if self.mint_status != 201:
            return _FakeResponse(self.mint_status, {"error": "refused"})
        minted: dict[str, Any] = {
            "token": f"phe_minted_{len(self.mints)}",
            "cap_usd": json["cap_usd"],
            "allowed_models": json.get("allowed_models"),
        }
        if self.expires_at is not None:
            minted["expires_at"] = self.expires_at
        if self.echo_capture_mode and "capture_mode" in json:
            minted["capture_mode"] = json["capture_mode"]
        return _FakeResponse(201, minted)


class _FakeResponse:
    def __init__(self, status_code: int, body: dict[str, Any]) -> None:
        self.status_code = status_code
        self._body = body
        self.text = str(body)

    def json(self) -> dict[str, Any]:
        return self._body


@override_settings(
    WORKFLOW_CLASSIFY_JWT_SECRETS=[SECRET],
    TASKS_CREATE_JWT_SECRETS=[SECRET],
    SANDBOX_AI_GATEWAY_URL="https://gateway.example.com/v1",
    SANDBOX_AI_GATEWAY_MINT_KEY=_MINT_KEY,
)
class TestWorkflowClassifyGatewayTokenAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.client.logout()
        self.url = f"/api/projects/{self.team.id}/workflow_classifications/gateway_token/"
        flag_patch = patch("posthoganalytics.feature_enabled", return_value=True)
        self.feature_flag = flag_patch.start()
        self.addCleanup(flag_patch.stop)
        self.gateway = _FakeGateway()
        gateway_patch = patch(_GATEWAY_POST, side_effect=self.gateway.post)
        gateway_patch.start()
        self.addCleanup(gateway_patch.stop)
        backoff_patch = patch(_MINT_BACKOFF)
        backoff_patch.start()
        self.addCleanup(backoff_patch.stop)

    def _post(self, token: str | None = None) -> Any:
        return self.client.post(
            self.url, {}, format="json", HTTP_AUTHORIZATION=f"Bearer {token or _token(self.team.id)}"
        )

    @covers_authentication(WorkflowClassifyJWTAuthentication)
    def test_mints_a_content_redacted_jev_token_billed_to_the_team(self) -> None:
        response = self._post()

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {"token": "phe_minted_1", "expires_at": _EXPIRES_AT}
        [mint] = self.gateway.mints
        assert mint == {
            "product": "workflows_classify",
            "obo": str(self.team.id),
            "allowed_models": [DEFAULT_DECISION_MODEL],
            "capture_mode": "content_none",
            "ttl_seconds": 1800,
            "cap_usd": "1",
        }

    def test_refuses_without_the_feature_flag(self) -> None:
        self.feature_flag.return_value = False

        response = self._post()

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert self.gateway.mints == []

    def test_refuses_an_organization_without_ai_data_processing_approval(self) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        response = self._post()

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert self.gateway.mints == []

    def test_refuses_a_team_with_exhausted_ai_credits(self) -> None:
        add_limited_team_tokens(
            QuotaResource.AI_CREDITS,
            {self.team.api_token: int(time.time()) + 3600},
            QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY,
        )

        response = self._post()

        assert response.status_code == status.HTTP_402_PAYMENT_REQUIRED
        assert self.gateway.mints == []

    @parameterized.expand(
        [
            ("no_content_redaction", False, _EXPIRES_AT),
            ("no_expiry", True, None),
            ("unreadable_expiry", True, "in half an hour"),
            ("expiry_without_timezone", True, "2026-11-20T12:30:00"),
        ]
    )
    def test_revokes_a_token_the_worker_must_not_use(
        self, _name: str, echo_capture_mode: bool, expires_at: str | None
    ) -> None:
        self.gateway.echo_capture_mode = echo_capture_mode
        self.gateway.expires_at = expires_at

        response = self._post()

        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert "token" not in response.json()
        assert self.gateway.revoked == ["phe_minted_1"]

    @parameterized.expand([("no_content_redaction", False, _EXPIRES_AT), ("no_expiry", True, None)])
    def test_reports_a_gateway_failure_when_the_revoke_fails_too(
        self, _name: str, echo_capture_mode: bool, expires_at: str | None
    ) -> None:
        self.gateway.echo_capture_mode = echo_capture_mode
        self.gateway.expires_at = expires_at
        self.gateway.revoke_status = 503

        response = self._post()

        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert "token" not in response.json()

    @parameterized.expand(
        [
            ("rate_limited", 429, status.HTTP_503_SERVICE_UNAVAILABLE),
            ("gateway_down", 503, status.HTTP_503_SERVICE_UNAVAILABLE),
            ("refused", 400, status.HTTP_502_BAD_GATEWAY),
        ]
    )
    def test_a_mint_failure_maps_onto_a_status_the_worker_can_retry_or_fail_on(
        self, _name: str, mint_status: int, expected: int
    ) -> None:
        self.gateway.mint_status = mint_status

        response = self._post()

        assert response.status_code == expected
        assert "token" not in response.json()

    @override_settings(SANDBOX_AI_GATEWAY_MINT_KEY=None)
    def test_reports_a_deployment_without_a_gateway_mint_key(self) -> None:
        response = self._post()

        assert response.status_code == status.HTTP_501_NOT_IMPLEMENTED
        assert self.gateway.mints == []

    def test_rejects_a_token_minted_for_another_workflow_action(self) -> None:
        response = self._post(token=_token(self.team.id, audience=PosthogJwtAudience.TASKS_CREATE))

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert self.gateway.mints == []
