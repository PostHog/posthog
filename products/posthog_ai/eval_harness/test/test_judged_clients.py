import json
from typing import Any

import pytest
from unittest.mock import MagicMock

import httpx
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI, OpenAIError

from products.posthog_ai.eval_harness.scorers import judged


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_key", [None, "test-openai-key"])
@pytest.mark.parametrize("scorer_type", ["nested", "judged"])
async def test_judges_use_direct_provider_without_braintrust_fallback(
    monkeypatch: pytest.MonkeyPatch, provider_key: str | None, scorer_type: str
) -> None:
    monkeypatch.setenv("BRAINTRUST_API_KEY", "test-braintrust-key")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    if provider_key:
        monkeypatch.setenv("OPENAI_API_KEY", provider_key)
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "test-completion",
                "object": "chat.completion",
                "created": 0,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "test-call",
                                    "type": "function",
                                    "function": {"name": "select_choice", "arguments": '{"choice":"yes"}'},
                                }
                            ],
                        },
                    }
                ],
            },
        )

    clients: list[AsyncOpenAI] = []

    def create_client() -> AsyncOpenAI:
        client = AsyncOpenAI(http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
        clients.append(client)
        return client

    monkeypatch.setattr(judged, "AsyncOpenAI", create_client)

    class PreparedJudge(judged.JudgedScorer):
        def _prepare(self, output: Any, expected: Any) -> dict[str, Any]:
            return {"output": output}

    classifier = judged.LocalLLMClassifier if scorer_type == "nested" else PreparedJudge
    scorer = classifier(name="judge", prompt_template="{{output}}", choice_scores={"yes": 1.0}, model="test-model")
    if provider_key is None and scorer_type == "nested":
        with pytest.raises(OpenAIError, match="OPENAI_API_KEY"):
            await scorer.eval_async("Synthetic answer")
    else:
        score = await scorer.eval_async("Synthetic answer")
        assert score.score == (1.0 if provider_key else 0.0)
        if provider_key is None:
            assert "OPENAI_API_KEY" in score.metadata["reason"]

    assert len(requests) == (1 if provider_key else 0)
    if requests:
        assert requests[0].url == "https://api.openai.com/v1/chat/completions"
        assert requests[0].headers["authorization"] == "Bearer test-openai-key"
    assert all(client.is_closed() for client in clients)
    assert scorer.client is None


@pytest.mark.asyncio
@pytest.mark.parametrize("judge_text,expected_score", [('{"reasons": "Grounded.", "choice": "yes"}', 1.0), ("", 0.0)])
async def test_claude_judges_call_anthropic_without_a_forced_tool(
    monkeypatch: pytest.MonkeyPatch, judge_text: str, expected_score: float
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5-5",
                "content": [{"type": "text", "text": judge_text}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    def create_client(**kwargs: Any) -> AsyncAnthropic:
        return AsyncAnthropic(**kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))

    monkeypatch.setattr(judged, "AsyncAnthropic", create_client)
    monkeypatch.setattr(judged, "AsyncOpenAI", MagicMock(side_effect=AssertionError("OpenAI must not be called")))

    class PreparedJudge(judged.JudgedScorer):
        def _prepare(self, output: Any, expected: Any) -> dict[str, Any]:
            return {"output": output}

    scorer = PreparedJudge(
        name="judge",
        prompt_template="Grade {{output}}",
        choice_scores={"yes": 1.0, "no": 0.0},
        model="claude-opus-5-5",
    )
    score = await scorer.eval_async("Synthetic answer")

    assert score.score == expected_score
    assert len(requests) == 1
    assert requests[0].url == "https://api.anthropic.com/v1/messages"
    assert requests[0].headers["x-api-key"] == "test-anthropic-key"
    body = json.loads(requests[0].content)
    assert "tool_choice" not in body and "tools" not in body
    schema = body["output_config"]["format"]["schema"]
    assert schema["properties"]["choice"]["enum"] == ["yes", "no"]
    assert schema["additionalProperties"] is False
    assert body["messages"][0]["content"].startswith("Grade Synthetic answer")
