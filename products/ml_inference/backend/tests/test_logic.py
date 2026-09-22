import json

import pytest

from django.test import override_settings

import httpx

from posthog.llm.gateway_client import GatewayNotConfiguredError

from products.ml_inference.backend.facade.contracts import (
    ChoiceAnswer,
    DecisionGatewayError,
    DecisionQuestion,
    DecisionRequest,
    NoulAnswer,
    ScoreAnswer,
)
from products.ml_inference.backend.facade.enums import DecisionQuestionType
from products.ml_inference.backend.logic import decisions

GATEWAY = {"AI_GATEWAY_URL": "https://gateway.example.com/v1", "AI_GATEWAY_API_KEY": "phs_test"}

ANSWERS = {
    "model": "kev-latest",
    "answers": {
        "urgent": {"noul": 0.91},
        "route": {"choice": "billing", "confidence": 0.6, "probabilities": {"billing": 0.7, "bug": 0.3}},
        "mood": {"score": 2.5, "confidence": 0.4, "probabilities": {"1": 0.2, "2": 0.3, "3": 0.5}, "legend": {}},
    },
    "usage": {"input_tokens": 772, "output_tokens": 0},
    "latency_ms": 31,
}


def _request() -> DecisionRequest:
    return DecisionRequest(
        team_id=42,
        state="ticket text",
        questions={
            "urgent": DecisionQuestion(type=DecisionQuestionType.NOUL, instructions="Is it urgent?"),
            "route": DecisionQuestion(
                type=DecisionQuestionType.CHOICE,
                instructions="Which queue?",
                criteria={"billing": "money", "bug": "broken"},
            ),
        },
    )


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
        result = decisions.parse_result(ANSWERS)

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
        ],
    )
    def test_rejects_a_200_that_is_not_a_decision(self, payload: object) -> None:
        with pytest.raises(DecisionGatewayError) as raised:
            decisions.parse_result(payload)

        assert raised.value.status_code == 200

    def test_surfaces_a_gateway_refusal_with_its_status(self) -> None:
        transport = httpx.MockTransport(lambda _request: httpx.Response(404, json={"error": {"code": "not_found"}}))

        with override_settings(**GATEWAY), pytest.raises(DecisionGatewayError) as raised:
            decisions.decide(_request(), transport=transport)

        assert raised.value.status_code == 404

    def test_refuses_to_call_without_a_configured_gateway(self) -> None:
        transport = httpx.MockTransport(lambda _request: pytest.fail("no request expected"))

        with override_settings(AI_GATEWAY_URL="", AI_GATEWAY_API_KEY=""), pytest.raises(GatewayNotConfiguredError):
            decisions.decide(_request(), transport=transport)
