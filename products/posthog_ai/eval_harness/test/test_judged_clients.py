from typing import Any

import pytest

import httpx
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
