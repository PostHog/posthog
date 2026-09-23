from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache.backends.locmem import LocMemCache
from django.test import SimpleTestCase, override_settings

from parameterized import parameterized
from rest_framework import status
from rest_framework.exceptions import Throttled
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory
from rest_framework.throttling import SimpleRateThrottle

from posthog.models import User
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle

from products.ml_inference.backend.facade.contracts import (
    ChoiceAnswer,
    DecisionGatewayError,
    DecisionGatewayUnreachableError,
    DecisionResult,
    DecisionsDisabledError,
    NoulAnswer,
)
from products.ml_inference.backend.presentation.serializers import DecideRequestSerializer
from products.ml_inference.backend.presentation.views import DecisionViewSet

QUESTIONS = {
    "urgent": {"type": "noul", "instructions": "Is this urgent?"},
    "queue": {"type": "choice", "instructions": "Which team?", "criteria": {"billing": "money", "support": "product"}},
}


class TestDecideRequestValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("score_with_a_scale", "score", ["calm", "irritated", "angry"], True),
            ("score_with_options_keyed_by_name", "score", {"calm": "not upset"}, False),
            ("score_with_one_label", "score", ["calm"], False),
            ("choice_with_a_list", "choice", ["billing", "support"], False),
            ("choice_without_options", "choice", None, False),
            ("noul_with_a_list", "noul", ["yes", "no"], False),
            ("noul_without_criteria", "noul", None, True),
        ]
    )
    def test_criteria_shape_follows_the_question_type(self, _name, question_type, criteria, valid) -> None:
        question = {"type": question_type, "instructions": "How is it?"}
        if criteria is not None:
            question["criteria"] = criteria
        serializer = DecideRequestSerializer(data={"state": "text", "questions": {"q": question}})

        assert serializer.is_valid() == valid, serializer.errors

    def test_rejects_an_unknown_question_type(self) -> None:
        serializer = DecideRequestSerializer(
            data={"state": "text", "questions": {"q": {"type": "essay", "instructions": "Write one"}}}
        )

        assert not serializer.is_valid()
        assert "questions" in serializer.errors

    def test_caps_the_number_of_questions(self) -> None:
        too_many = {f"q{i}": {"type": "noul", "instructions": "Is it?"} for i in range(33)}
        serializer = DecideRequestSerializer(data={"state": "text", "questions": too_many})

        assert not serializer.is_valid()
        assert "questions" in serializer.errors

    @parameterized.expand(
        [
            ("state", {"state": "x" * 65_537, "questions": QUESTIONS}),
            ("instructions", {"state": "text", "questions": {"q": {"type": "noul", "instructions": "x" * 2_001}}}),
            (
                "option_count",
                {
                    "state": "text",
                    "questions": {
                        "q": {"type": "choice", "instructions": "?", "criteria": {str(i): "m" for i in range(256)}}
                    },
                },
            ),
            (
                "option_length",
                {
                    "state": "text",
                    "questions": {"q": {"type": "score", "instructions": "?", "criteria": ["low", "x" * 501]}},
                },
            ),
        ]
    )
    def test_bounds_the_size_of_every_text_field(self, _name, data) -> None:
        serializer = DecideRequestSerializer(data=data)

        assert not serializer.is_valid()

    def test_defaults_the_model(self) -> None:
        serializer = DecideRequestSerializer(data={"state": "text", "questions": QUESTIONS})

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["model"] == "posthog/posthog/decision-4b"


class TestDecisionThrottles(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.cache = LocMemCache(self.id(), {})
        self.cache.clear()
        self.addCleanup(self.cache.clear)
        cache_patch = patch.object(SimpleRateThrottle, "cache", self.cache)
        cache_patch.start()
        self.addCleanup(cache_patch.stop)
        timer_patch = patch.object(SimpleRateThrottle, "timer", return_value=1_000.0)
        self.timer = timer_patch.start()
        self.addCleanup(timer_patch.stop)
        self.request = Request(APIRequestFactory().post("/"))
        self.request.user = User(pk=1)
        self.view = DecisionViewSet()

    def test_autocomplete_has_its_own_budget_even_when_other_ai_limits_are_exhausted(self) -> None:
        for throttle in [AIBurstRateThrottle(), AISustainedRateThrottle()]:
            request_limit, _ = throttle.parse_rate(throttle.rate)
            assert request_limit is not None
            self.cache.set(throttle.get_cache_key(self.request, self.view), [1_000.0] * request_limit)

        for _ in range(12):
            self.view.check_throttles(self.request)

    @parameterized.expand(
        [
            ("burst", "2/minute", "100/hour", 61),
            ("sustained", "100/minute", "2/hour", 3_601),
        ]
    )
    def test_configured_limits_block_then_recover_per_user(
        self, _name: str, burst_rate: str, sustained_rate: str, recovery_seconds: int
    ) -> None:
        with override_settings(
            ML_INFERENCE_DECISIONS_BURST_RATE=burst_rate,
            ML_INFERENCE_DECISIONS_SUSTAINED_RATE=sustained_rate,
        ):
            self.view.check_throttles(self.request)
            self.view.check_throttles(self.request)
            with self.assertRaises(Throttled):
                self.view.check_throttles(self.request)

            self.request.user = User(pk=2)
            self.view.check_throttles(self.request)

            self.request.user = User(pk=1)
            self.timer.return_value = 1_000.0 + recovery_seconds
            self.view.check_throttles(self.request)


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
