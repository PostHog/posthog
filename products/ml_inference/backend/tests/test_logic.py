import json
from typing import Any

import pytest
from unittest.mock import patch

from django.test import override_settings

import httpx

from posthog.llm.gateway_client import GatewayNotConfiguredError

from products.ml_inference.backend.facade.contracts import (
    ChoiceAnswer,
    DecisionGatewayError,
    DecisionGatewayUnreachableError,
    DecisionQuestion,
    DecisionRequest,
    NoulAnswer,
    ScoreAnswer,
)
from products.ml_inference.backend.facade.enums import DecisionQuestionType
from products.ml_inference.backend.logic import decisions

GATEWAY = {"AI_GATEWAY_URL": "https://gateway.example.com/v1", "AI_GATEWAY_API_KEY": "phs_test"}

ANSWERS: dict[str, Any] = {
    "model": "kev-latest",
    "answers": {
        "urgent": {"noul": 0.91},
        "route": {"choice": "billing", "confidence": 0.6, "probabilities": {"billing": 0.7, "bug": 0.3}},
        "mood": {"score": 2.5, "confidence": 0.4, "probabilities": {"1": 0.2, "2": 0.3, "3": 0.5}, "legend": {}},
    },
    "usage": {"input_tokens": 772, "output_tokens": 0},
    "latency_ms": 31,
}


QUESTIONS = {
    "urgent": DecisionQuestion(type=DecisionQuestionType.NOUL, instructions="Is it urgent?"),
    "route": DecisionQuestion(
        type=DecisionQuestionType.CHOICE,
        instructions="Which queue?",
        criteria={"billing": "money", "bug": "broken"},
    ),
    "mood": DecisionQuestion(type=DecisionQuestionType.SCORE, instructions="Mood?", criteria=["1", "2", "3"]),
}


def _request() -> DecisionRequest:
    return DecisionRequest(team_id=42, state="ticket text", questions=QUESTIONS)


def test_a_request_refuses_more_questions_than_the_cap() -> None:
    question = DecisionQuestion(type=DecisionQuestionType.NOUL, instructions="Is it?")
    with pytest.raises(ValueError, match="at most 32"):
        DecisionRequest(team_id=1, state="text", questions={f"q{i}": question for i in range(33)})


class TestDecide:
    @pytest.mark.parametrize(
        "gateway_url",
        ["https://gateway.example.com/v1", "https://gateway.example.com/v1/"],
    )
    def test_posts_to_the_decision_route_off_the_gateway_origin(self, gateway_url: str) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=ANSWERS)

        with override_settings(AI_GATEWAY_URL=gateway_url, AI_GATEWAY_API_KEY="phs_test"):
            result = decisions.decide(_request(), transport=httpx.MockTransport(handler))

        assert [str(request.url) for request in seen] == ["https://gateway.example.com/v1/systemone"]
        request = seen[0]
        assert request.headers["Authorization"] == "Bearer phs_test"
        assert json.loads(request.headers["X-PostHog-Properties"]) == {"ai_product": "ml_inference"}
        assert request.headers["X-PostHog-Distinct-Id"] == "team-42"
        body = json.loads(request.content)
        assert body["model"] == "posthog/posthog/decision-4b"
        assert body["state"] == "ticket text"
        assert body["questions"]["urgent"] == {"type": "noul", "instructions": "Is it urgent?"}
        assert body["questions"]["route"]["criteria"] == {"billing": "money", "bug": "broken"}
        assert result.input_tokens == 772
        assert result.latency_ms == 31

    def test_parses_every_answer_type(self) -> None:
        result = decisions.parse_result(ANSWERS, QUESTIONS)

        assert result.answers["urgent"] == NoulAnswer(probability=0.91)
        assert result.answers["route"] == ChoiceAnswer(
            choice="billing", confidence=0.6, probabilities={"billing": 0.7, "bug": 0.3}
        )
        assert result.answers["mood"] == ScoreAnswer(
            score=2.5, confidence=0.4, probabilities={"1": 0.2, "2": 0.3, "3": 0.5}
        )

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            [],
            {"model": "kev-latest", "answers": {}, "usage": {}},
            {"model": "kev-latest", "answers": {"q": {"verdict": "maybe"}}, "usage": {"input_tokens": 1}},
            {"model": "kev-latest", "answers": {"q": "yes"}, "usage": {"input_tokens": 1}},
            {**ANSWERS, "answers": {**ANSWERS["answers"], "extra": {"noul": 0.5}}},
            {**ANSWERS, "answers": {k: v for k, v in ANSWERS["answers"].items() if k != "mood"}},
            {**ANSWERS, "answers": {**ANSWERS["answers"], "urgent": {"noul": 0.9, "choice": "billing"}}},
            {**ANSWERS, "answers": {**ANSWERS["answers"], "urgent": ANSWERS["answers"]["route"]}},
        ],
    )
    def test_rejects_a_200_that_is_not_a_decision(self, payload: object) -> None:
        with pytest.raises(DecisionGatewayError) as raised:
            decisions.parse_result(payload, QUESTIONS)

        assert raised.value.status_code == 200

    def test_reports_a_transport_failure_as_the_gateway_being_unreachable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        with override_settings(**GATEWAY), pytest.raises(DecisionGatewayUnreachableError):
            decisions.decide(_request(), transport=httpx.MockTransport(handler))

    def test_surfaces_a_gateway_refusal_with_its_status(self) -> None:
        transport = httpx.MockTransport(lambda _request: httpx.Response(404, json={"error": {"code": "not_found"}}))

        with override_settings(**GATEWAY), pytest.raises(DecisionGatewayError) as raised:
            decisions.decide(_request(), transport=transport)

        assert raised.value.status_code == 404

    @pytest.mark.parametrize(
        "gateway_url,allowed",
        [
            ("https://gateway.example.com/v1", True),
            ("http://localhost:8080/v1", True),
            ("http://127.0.0.1:8080/v1", True),
            ("http://gateway.example.com/v1", False),
        ],
    )
    def test_sends_the_bearer_in_clear_only_to_this_machine(self, gateway_url: str, allowed: bool) -> None:
        transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=ANSWERS))

        with override_settings(AI_GATEWAY_URL=gateway_url, AI_GATEWAY_API_KEY="phs_test"):
            if allowed:
                assert decisions.decide(_request(), transport=transport).model == "kev-latest"
            else:
                with pytest.raises(GatewayNotConfiguredError):
                    decisions.decide(_request(), transport=transport)

    def test_refuses_to_call_without_a_configured_gateway(self) -> None:
        transport = httpx.MockTransport(lambda _request: pytest.fail("no request expected"))

        with override_settings(AI_GATEWAY_URL="", AI_GATEWAY_API_KEY=""), pytest.raises(GatewayNotConfiguredError):
            decisions.decide(_request(), transport=transport)


class TestDecisionsEnabled:
    @pytest.mark.parametrize(
        "debug,deployment,expected",
        [
            (True, "EU", True),
            (False, "EU", False),
            (False, None, False),
        ],
    )
    def test_region_guard_runs_before_the_flag(self, debug: bool, deployment: str | None, expected: bool) -> None:
        with (
            override_settings(DEBUG=debug, CLOUD_DEPLOYMENT=deployment),
            patch("products.ml_inference.backend.logic.decisions.posthoganalytics.feature_enabled") as flag,
        ):
            assert decisions.decisions_enabled(team_id=1) is expected

        flag.assert_not_called()
