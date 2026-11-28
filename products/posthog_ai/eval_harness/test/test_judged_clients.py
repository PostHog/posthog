import json
from typing import Any

import pytest

import httpx
import posthoganalytics.ai.openai
from openai import AsyncOpenAI, OpenAIError
from posthoganalytics import Posthog

from products.posthog_ai.eval_harness.scorers import judged
from products.posthog_ai.eval_harness.scorers.tracing import TracedScorer, create_traced_scorer_clients


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
@pytest.mark.parametrize("traced", [False, True])
@pytest.mark.parametrize("choice, expected_score", [("yes", 1.0), ("no", 0.0)])
async def test_gpt6_judges_answer_through_the_responses_api(
    monkeypatch: pytest.MonkeyPatch, choice: str, expected_score: float, traced: bool
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "test-response",
                "object": "response",
                "created_at": 0,
                "model": "gpt-6.2-sol",
                "output": [
                    {
                        "type": "function_call",
                        "id": "test-item",
                        "call_id": "test-call",
                        "name": "select_choice",
                        "arguments": f'{{"choice":"{choice}"}}',
                        "status": "completed",
                    }
                ],
            },
        )

    monkeypatch.setattr(
        judged,
        "AsyncOpenAI",
        lambda: AsyncOpenAI(http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))),
    )
    traced_openai = posthoganalytics.ai.openai.AsyncOpenAI
    monkeypatch.setattr(
        posthoganalytics.ai.openai,
        "AsyncOpenAI",
        lambda posthog_client: traced_openai(
            posthog_client=posthog_client, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))
        ),
    )
    generations: list[dict[str, Any]] = []
    posthog_client = Posthog("phc_test", host="http://localhost", sync_mode=True)
    monkeypatch.setattr(posthog_client, "capture_ai", lambda **kwargs: generations.append(kwargs))

    class PreparedJudge(judged.JudgedScorer):
        def _prepare(self, output: Any, expected: Any) -> dict[str, Any]:
            return {"output": output}

    judge = PreparedJudge(
        name="judge", prompt_template="{{output}}", choice_scores={"yes": 1.0, "no": 0.0}, model="gpt-6.2-sol"
    )
    run_metadata = {"agent_model": "claude-test", "trials": 1, "git_sha": "abc123", "git_dirty": False}
    scorer: Any = (
        TracedScorer(
            judge,
            create_traced_scorer_clients(posthog_client),
            {"experiment_id": "exp-1", "experiment_name": "ns/suite", "run_metadata": run_metadata},
            {},
        )
        if traced
        else judge
    )

    score = await scorer.eval_async("Synthetic answer", metadata={"trial_id": "trial-1"})

    assert score.score == expected_score, score.metadata
    assert len(generations) == (1 if traced else 0)
    assert [request.url for request in requests] == ["https://api.openai.com/v1/responses"]
    body = json.loads(requests[0].content)
    assert [tool["name"] for tool in body["tools"]] == ["select_choice"]
    assert body["tool_choice"] == "required"
