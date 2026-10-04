import sys
import json
from datetime import timedelta
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from parameterized import parameterized
from rest_framework import status
from structlog.processors import format_exc_info
from structlog.testing import capture_logs

from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.llm.gateway_client import GatewayNotConfiguredError
from posthog.models import Team
from posthog.redis import get_client
from posthog.token_bucket import BucketDecision, BucketUnavailable

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
_GET_CLIENT = "products.workflows.backend.services.ai_decision.get_client"
_ADMITTED = BucketDecision(allowed=True, remaining=1, limit=2, retry_after=0, reset=1)
_OUTCOME_LOG_EVENTS = (
    "workflow_ai_decision_failed",
    "workflow_ai_decision_throttled",
    "workflow_ai_decision_unavailable",
)
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


@override_settings(WORKFLOW_AI_DECISION_JWT_SECRETS=[SECRET])
class TestWorkflowAIDecisionsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.client.logout()
        flag = patch(_FLAG, return_value=True)
        self.flag = flag.start()
        self.addCleanup(flag.stop)
        get_client().flushdb()

    def _post(
        self, body: dict | None = None, token: str | None = None, team_id: int | None = None, omit: tuple[str, ...] = ()
    ) -> Any:
        payload = {
            "invocation_id": "inv-1",
            "action_id": "action-1",
            "answer_type": "pick_one",
            "question": "Is this ticket spam?",
            "options": OPTIONS,
            "state": {"subject": "Buy SEO"},
            **(body or {}),
        }
        team_id = team_id or self.team.id
        # Escaped ASCII JSON, as the CDP worker's JSON.stringify sends a lone surrogate.
        return self.client.post(
            f"/api/projects/{team_id}/workflow_ai_decisions/",
            json.dumps({key: value for key, value in payload.items() if key not in omit}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token or _token(team_id)}",
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
        self.flag.assert_called_once_with(
            "workflows-ai-decision",
            str(self.team.uuid),
            groups={"organization": str(self.organization.id)},
            group_properties={"organization": {"id": str(self.organization.id)}},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )

    @parameterized.expand(
        [
            (
                "both_meanings",
                "A real company",
                "A free mailbox",
                {"true": "A real company", "false": "A free mailbox"},
            ),
            ("yes_meaning_only", "A real company", "", {"true": "A real company"}),
            ("no_meanings", "", "", None),
        ]
    )
    def test_yes_no_returns_yes_and_no_probabilities(
        self, _name: str, yes_means: str, no_means: str, criteria: dict[str, str] | None
    ) -> None:
        result = DecisionResult(model="jev", answers={"answer": NoulAnswer(probability=0.75)}, input_tokens=9)
        with patch(_DECIDE, return_value=result) as decide:
            response = self._post(
                {"answer_type": "yes_no", "options": [], "yes_means": yes_means, "no_means": no_means}
            )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["probabilities"] == {"yes": 0.75, "no": 0.25}
        assert decide.call_args.args[0].questions == {
            "answer": DecisionQuestion(
                type=DecisionQuestionType.NOUL, instructions="Is this ticket spam?", criteria=criteria
            )
        }

    @parameterized.expand(
        [
            ("one_option", {"options": OPTIONS[:1]}, (), "options"),
            ("seventeen_options", {"options": [{"name": f"o{i}"} for i in range(17)]}, (), "options"),
            ("duplicate_option_names", {"options": [OPTIONS[0], OPTIONS[0]]}, (), "options"),
            ("no_question", {"question": ""}, (), "question"),
            ("no_answer_type", {}, ("answer_type",), "answer_type"),
            ("state_not_an_object", {"state": ["Buy SEO"]}, (), "state"),
        ]
    )
    def test_rejects_a_request_the_save_would_reject(
        self, _name: str, body: dict, omit: tuple[str, ...], error_field: str
    ) -> None:
        with patch(_DECIDE) as decide:
            response = self._post(body, omit=omit)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert error_field in response.json()["attr"], response.json()
        decide.assert_not_called()

    def test_a_test_run_of_an_unsaved_workflow_has_no_workflow_label(self) -> None:
        with patch(_DECIDE, return_value=_pick_one_result()) as decide:
            response = self._post(token=_token(self.team.id, hog_flow_id=None))

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert decide.call_args.args[0].properties == {"action_id": "action-1"}

    def test_rejects_a_token_minted_for_another_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")

        with patch(_DECIDE) as decide:
            response = self._post(token=_token(self.team.id), team_id=other_team.id)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        decide.assert_not_called()

    @parameterized.expand(
        [
            ("another_audience", PosthogJwtAudience.TASKS_CREATE, SECRET),
            ("another_signing_key", PosthogJwtAudience.WORKFLOW_AI_DECISION, "a-key-for-another-use"),
        ]
    )
    def test_rejects_a_token_minted_for_another_use(
        self, _name: str, audience: PosthogJwtAudience, signing_key: str
    ) -> None:
        token = encode_jwt(
            {"team_id": self.team.id, "hog_flow_id": "flow-1"}, timedelta(minutes=5), audience, signing_key=signing_key
        )
        with override_settings(TASKS_CREATE_JWT_SECRETS=[SECRET]):
            response = self._post(token=token)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @parameterized.expand(
        [
            ("flag_off", 0, "feature_unavailable"),
            ("ai_processing_not_approved", 1, "ai_processing_not_approved"),
            ("out_of_ai_credits", 2, "quota_exceeded"),
            ("state_too_large", 3, "state_too_large"),
        ]
    )
    @override_settings(WORKFLOWS_AI_DECISION_TEAM_BURST=1, WORKFLOWS_AI_DECISION_TEAM_PER_HOUR=1)
    def test_the_first_closed_gate_fails_the_decision_without_asking_the_model_or_spending_admission(
        self, _name: str, first_closed_gate: int, expected_code: str
    ) -> None:
        self.flag.return_value = first_closed_gate > 0
        self.organization.is_ai_data_processing_approved = first_closed_gate > 1
        self.organization.save()
        with patch(_CREDITS, return_value=first_closed_gate <= 2) as credits, patch(_DECIDE) as decide:
            response = self._post({"state": {"reply": "x" * 9000}})
        decide.assert_not_called()
        if expected_code == "quota_exceeded":
            credits.assert_called_once_with(self.team.api_token)
        self.flag.return_value = True
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        with patch(_CREDITS, return_value=False), patch(_DECIDE, return_value=_pick_one_result()):
            next_valid = self._post()

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["status"] == "failed"
        assert response.json()["error"]["code"] == expected_code
        assert response.json()["error"]["message"]
        assert next_valid.status_code == status.HTTP_200_OK, next_valid.json()

    @parameterized.expand(
        [
            ("flag_check_raises", patch(_FLAG, side_effect=RuntimeError("blip")), 503, None),
            ("flag_definitions_not_loaded", patch(_FLAG, return_value=None), 503, None),
            ("credit_lookup_raises", patch(_CREDITS, side_effect=RuntimeError("blip")), 200, "succeeded"),
            ("billing_module_missing", patch.dict(sys.modules, {"ee.billing.quota_limiting": None}), 200, "succeeded"),
        ]
    )
    def test_a_lookup_that_raises_never_fails_the_decision_for_good(
        self, _name: str, lookup_failure: Any, expected_status: int, expected_outcome: str | None
    ) -> None:
        self.ensure_url_patterns_loaded()
        with lookup_failure, patch(_DECIDE, return_value=_pick_one_result()):
            response = self._post()

        assert response.status_code == expected_status, response.json()
        if expected_outcome is not None:
            assert response.json()["status"] == expected_outcome

    @parameterized.expand(
        [
            ("ascii_at_the_cap", "a" * 8184, "a" * 8184),
            ("two_byte_characters_at_the_cap", "é" * 4092, "é" * 4092),
            ("lone_surrogate_from_a_split_emoji", "ok \ud83d", "ok \ufffd"),
            ("property_the_person_does_not_have", None, None),
        ]
    )
    def test_sends_any_rendered_state_up_to_the_compact_utf8_byte_cap(
        self, _name: str, value: str | None, sent_value: str | None
    ) -> None:
        with patch(_DECIDE, return_value=_pick_one_result()) as decide:
            response = self._post({"state": {"t": value}})

        assert response.json()["status"] == "succeeded", response.json()
        assert decide.call_args.args[0].state == {"t": sent_value}

    @parameterized.expand(
        [
            ("two_byte_characters_over_the_cap", {"t": "é" * 4093}, "state_too_large"),
            ("nested_deeper_than_the_model_reads", {"t": json.loads("[" * 300 + "]" * 300)}, "model_refused"),
        ]
    )
    @override_settings(WORKFLOWS_AI_DECISION_TEAM_BURST=1, WORKFLOWS_AI_DECISION_TEAM_PER_HOUR=1)
    def test_refuses_a_state_the_model_cannot_take_without_asking_it_or_spending_admission(
        self, _name: str, state: dict[str, Any], expected_code: str
    ) -> None:
        with patch(_DECIDE) as decide:
            response = self._post({"state": state})
        decide.assert_not_called()
        with patch(_DECIDE, return_value=_pick_one_result()):
            next_valid = self._post()

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["error"]["code"] == expected_code
        assert next_valid.json()["status"] == "succeeded", next_valid.json()

    @parameterized.expand(
        [
            ("region_without_decisions", DecisionsDisabledError(1), status.HTTP_200_OK, "feature_unavailable"),
            ("gateway_not_configured", GatewayNotConfiguredError("unset"), status.HTTP_200_OK, "gateway_unavailable"),
            ("gateway_out_of_credits", DecisionGatewayError(402, "no credits"), status.HTTP_200_OK, "quota_exceeded"),
            ("gateway_bad_request", DecisionGatewayError(400, "bad"), status.HTTP_200_OK, "model_refused"),
            ("gateway_too_large", DecisionGatewayError(413, "big"), status.HTTP_200_OK, "model_refused"),
            ("gateway_unprocessable", DecisionGatewayError(422, "no"), status.HTTP_200_OK, "model_refused"),
            ("gateway_unreadable_answer", DecisionGatewayError(200, "bad answer"), status.HTTP_200_OK, "model_refused"),
            ("gateway_rejects_credential", DecisionGatewayError(401, "who"), status.HTTP_200_OK, "gateway_unavailable"),
            ("gateway_route_missing", DecisionGatewayError(404, "where"), status.HTTP_200_OK, "gateway_unavailable"),
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

    @parameterized.expand(
        [
            ("option_missing", {"spam": 1.0}),
            ("unknown_option", {"spam": 0.5, "support": 0.3, "other": 0.2}),
            ("probability_above_one", {"spam": 1.2, "support": 0.0}),
        ]
    )
    def test_an_answer_that_does_not_match_the_options_is_refused(
        self, _name: str, probabilities: dict[str, float]
    ) -> None:
        result = DecisionResult(
            model="jev",
            answers={"answer": ChoiceAnswer(choice="spam", confidence=0.9, probabilities=probabilities)},
            input_tokens=1,
        )
        with patch(_DECIDE, return_value=result):
            response = self._post()

        assert response.json()["error"]["code"] == "model_refused", response.json()

    @override_settings(
        WORKFLOWS_AI_DECISION_TEAM_BURST=1,
        WORKFLOWS_AI_DECISION_TEAM_PER_HOUR=1,
        WORKFLOWS_AI_DECISION_GLOBAL_BURST=2,
        WORKFLOWS_AI_DECISION_GLOBAL_PER_HOUR=1,
    )
    def test_one_team_over_its_budget_does_not_throttle_another(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        with patch(_DECIDE, return_value=_pick_one_result()) as decide:
            first = self._post()
            throttled = self._post()
            calls_after_throttle = decide.call_count
            other = self._post(team_id=other_team.id)

        assert first.status_code == status.HTTP_200_OK, first.json()
        assert throttled.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert int(throttled["Retry-After"]) > 0
        assert calls_after_throttle == 1
        assert other.status_code == status.HTTP_200_OK, other.json()

    @override_settings(
        WORKFLOWS_AI_DECISION_TEAM_BURST=1,
        WORKFLOWS_AI_DECISION_TEAM_PER_HOUR=1,
        WORKFLOWS_AI_DECISION_GLOBAL_BURST=1,
        WORKFLOWS_AI_DECISION_GLOBAL_PER_HOUR=3600,
    )
    def test_the_global_budget_throttles_every_team_and_keeps_their_own_budget(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        with time_machine.travel("2026-10-04 12:00:00", tick=False) as clock:
            with patch(_DECIDE, return_value=_pick_one_result()) as decide:
                first = self._post()
                throttled = self._post(team_id=other_team.id)
                assert decide.call_count == 1
                clock.shift(2)
                after_refill = self._post(team_id=other_team.id)

        assert first.status_code == status.HTTP_200_OK, first.json()
        assert throttled.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert after_refill.status_code == status.HTTP_200_OK, after_refill.json()

    @parameterized.expand(
        [
            ("bucket_unavailable", patch(_CONSUME, return_value=BucketUnavailable(error="down"))),
            (
                "global_bucket_unavailable",
                patch(_CONSUME, side_effect=[_ADMITTED, BucketUnavailable(error="down")]),
            ),
            ("redis_not_configured", patch(_GET_CLIENT, side_effect=ImproperlyConfigured("no redis"))),
        ]
    )
    def test_admission_fails_closed_when_redis_is_unavailable(self, _name: str, redis_failure: Any) -> None:
        with redis_failure, patch(_DECIDE) as decide:
            response = self._post()

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        decide.assert_not_called()

    @parameterized.expand(
        [
            ("unreadable_state", None, "debug"),
            ("model_refused", DecisionGatewayError(400, "gateway-body-secret"), "debug"),
            ("unreadable_answer", DecisionGatewayError(200, "gateway-body-secret"), "warning"),
            ("gateway_rejects_every_decision", DecisionGatewayError(403, "gateway-body-secret"), "warning"),
            ("throttled", DecisionGatewayError(429, "gateway-body-secret"), "debug"),
            ("unavailable", DecisionGatewayError(502, "gateway-body-secret"), "warning"),
        ]
    )
    def test_logs_never_carry_the_state_or_a_gateway_body(
        self, _name: str, error: Exception | None, outcome_log_level: str
    ) -> None:
        reply: Any = json.loads("[" * 300 + '"state-secret"' + "]" * 300) if error is None else "state-secret"
        with capture_logs(processors=[format_exc_info]) as logs, patch(_DECIDE, side_effect=error):
            response = self._post({"state": {"reply": reply}})

        assert [entry["log_level"] for entry in logs if entry["event"] in _OUTCOME_LOG_EVENTS] == [outcome_log_level]
        assert "secret" not in str(logs)
        assert "secret" not in str(response.json())
