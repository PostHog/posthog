import json
import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

import httpx
from google.genai import (
    errors as genai_errors,
    types,
)

from products.replay_vision.backend import (
    feedback_themes,
    prompt_suggestions,
    scanner_draft,
    search_suggestions,
    tag_suggestions,
)
from products.replay_vision.backend.gemini_client import (
    GATEWAY_FLAG,
    GatewayGeminiClient,
    assemble_stream,
    replay_gateway_enabled,
    replay_gemini_client,
)
from products.replay_vision.backend.temporal.errors import FailureKind
from products.replay_vision.backend.temporal.gemini import classify_gemini_error

_GATEWAY = {"AI_GATEWAY_URL": "https://ai-gateway.example/v1", "AI_GATEWAY_API_KEY": "phs_test"}
_UNSET = {"AI_GATEWAY_URL": "", "AI_GATEWAY_API_KEY": ""}
_OK = {"candidates": [{"content": {"role": "model", "parts": [{"text": "ok"}]}, "finishReason": "STOP"}]}
_FLAG = "products.replay_vision.backend.gemini_client.feature_enabled_or_false"


@pytest.fixture(autouse=True)
def flag_on() -> Any:
    with patch(_FLAG, return_value=True) as flag:
        yield flag


def _sse(*chunks: dict[str, Any]) -> bytes:
    return b"".join(b"data: " + json.dumps(chunk).encode() + b"\r\n\r\n" for chunk in chunks)


def _wired_gateway_client(properties: dict[str, Any]) -> tuple[GatewayGeminiClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=_sse(_OK), headers={"content-type": "text/event-stream"})

    with override_settings(**_GATEWAY):
        client = replay_gemini_client(MagicMock(), team_id=42, properties=properties, distinct_id="replay-vision:42")
    assert isinstance(client, GatewayGeminiClient)
    api_client = client.models._models._api_client
    api_client._httpx_client = httpx.Client(transport=httpx.MockTransport(handler))
    api_client._async_httpx_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client, seen


class TestReplayGeminiClient:
    def test_direct_mode_returns_the_callers_client(self) -> None:
        direct = MagicMock()
        with override_settings(**_UNSET):
            assert replay_gemini_client(direct, team_id=42) is direct.return_value

    def test_flag_off_keeps_the_team_direct_even_with_the_gateway_configured(self, flag_on: MagicMock) -> None:
        flag_on.return_value = False
        direct = MagicMock()
        with override_settings(**_GATEWAY), patch("posthog.llm.gateway_client.genai.Client") as gateway_client:
            assert replay_gemini_client(direct, team_id=42) is direct.return_value
        gateway_client.assert_not_called()

    def test_flag_is_evaluated_locally_per_project_without_events(self, flag_on: MagicMock) -> None:
        with override_settings(**_GATEWAY):
            assert replay_gateway_enabled(42) is True
        flag_on.assert_called_once_with(
            GATEWAY_FLAG,
            "team-42",
            groups={"project": "42"},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )

    def test_unset_gateway_skips_the_flag(self, flag_on: MagicMock) -> None:
        with override_settings(**_UNSET):
            assert replay_gateway_enabled(42) is False
        flag_on.assert_not_called()

    def test_gateway_mode_never_builds_the_direct_client(self) -> None:
        direct = MagicMock()
        with override_settings(**_GATEWAY), patch("posthog.llm.gateway_client.genai.Client"):
            assert isinstance(replay_gemini_client(direct, team_id=42), GatewayGeminiClient)
        direct.assert_not_called()

    def test_per_call_capture_kwargs_become_request_headers(self) -> None:
        client, seen = _wired_gateway_client({"feature": "scanner", "team_id": 42})

        client.models.generate_content(
            model="models/gemini-test",
            contents=[types.Part.from_bytes(data=b"mp4", mime_type="video/mp4"), "hi"],
            config=types.GenerateContentConfig(temperature=0.2),
            posthog_distinct_id="user-1",
            posthog_trace_id="trace-1",
            posthog_properties={"$ai_span_name": "core", "feature": "override"},
            posthog_groups={"project": "42"},
        )

        request = seen[0]
        assert str(request.url) == "https://ai-gateway.example/v1beta/models/gemini-test:streamGenerateContent?alt=sse"
        assert request.headers["x-goog-api-key"] == "phs_test"
        assert request.headers["x-posthog-trace-id"] == "trace-1"
        assert request.headers["x-posthog-distinct-id"] == "user-1"
        assert request.headers["x-posthog-privacy-mode"] == "true"
        assert json.loads(request.headers["x-posthog-properties"]) == {
            "feature": "override",
            "team_id": "42",
            "span_name": "core",
            "ai_product": "replay_vision",
        }
        body = json.loads(request.content)
        assert body["contents"][0]["parts"][0]["inlineData"]["mimeType"] == "video/mp4"
        assert "httpOptions" not in body and "http_options" not in body

    def test_async_surface_uses_the_same_headers(self) -> None:
        client, seen = _wired_gateway_client({"feature": "scanner"})

        asyncio.run(client.aio.models.generate_content(model="gemini-test", contents="hi", posthog_trace_id="t"))

        assert seen[0].headers["x-posthog-trace-id"] == "t"
        assert seen[0].headers["x-posthog-distinct-id"] == "replay-vision:42"


def _call_search() -> None:
    search_suggestions._generate(user_content="x", team_id=1, distinct_id="u")


def _call_tags() -> None:
    tag_suggestions._generate(user_content="x", team_id=1, distinct_id="u")


def _call_draft() -> None:
    scanner_draft._generate(user_content="x", team_id=1, distinct_id="u")


def _call_themes() -> None:
    feedback_themes._summarize(comments=["x"], team_id=1, distinct_id="u")


def _call_prompt() -> None:
    prompt_suggestions._generate(
        user_content="x", team_id=1, distinct_id="u", system_prompt="s", output_schema={"type": "object"}
    )


@pytest.mark.parametrize(
    ("module", "call"),
    [
        (search_suggestions, _call_search),
        (tag_suggestions, _call_tags),
        (scanner_draft, _call_draft),
        (feedback_themes, _call_themes),
        (prompt_suggestions, _call_prompt),
    ],
)
def test_text_call_sites_use_the_gateway_when_configured(module: Any, call: Callable[[], None]) -> None:
    with (
        override_settings(**_GATEWAY),
        patch("posthog.llm.gateway_client.genai.Client") as gateway_client,
        patch.object(module.genai, "Client") as direct_client,
    ):
        gateway_client.return_value.models.generate_content_stream.side_effect = RuntimeError("stop")
        with pytest.raises(Exception):
            call()

    direct_client.assert_not_called()
    gateway_client.return_value.models.generate_content_stream.assert_called()
    headers = gateway_client.call_args.kwargs["http_options"].headers
    assert headers["X-PostHog-Product"] == "replay_vision"
    assert headers["X-PostHog-Privacy-Mode"] == "true"
    request_headers = gateway_client.return_value.models.generate_content_stream.call_args.kwargs[
        "config"
    ].http_options.headers
    labels = json.loads(request_headers["X-PostHog-Properties"])
    assert labels["ai_product"] == "replay_vision"
    assert labels["team_id"] == "1"
    assert labels["feature"]
    assert request_headers["X-PostHog-Distinct-Id"] == "u"


def test_a_stream_assembles_into_the_buffered_response() -> None:
    client, seen = _wired_gateway_client({"feature": "scanner"})
    chunks: list[dict[str, Any]] = [
        {"candidates": [{"content": {"role": "model", "parts": [{"text": "Hel"}]}}]},
        {"candidates": [{"content": {"role": "model", "parts": [{"text": "lo"}]}}]},
        {
            "candidates": [{"content": {"role": "model", "parts": [{"text": ""}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2},
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=_sse(*chunks), headers={"content-type": "text/event-stream"})

    client.models._models._api_client._httpx_client = httpx.Client(transport=httpx.MockTransport(handler))

    response = client.models.generate_content(model="gemini-test", contents="hi")

    assert response.text == "Hello"
    assert response.candidates is not None
    assert response.candidates[0].finish_reason == types.FinishReason.STOP
    assert response.usage_metadata is not None and response.usage_metadata.candidates_token_count == 2
    content = response.candidates[0].content
    assert content is not None and content.parts is not None and len(content.parts) == 1


def _chunk(*parts: types.Part, finish: types.FinishReason | None = None) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=list(parts)), finish_reason=finish)]
    )


class TestAssembleStream:
    def test_function_calls_and_thought_signatures_survive_unmerged(self) -> None:
        call = types.Part(function_call=types.FunctionCall(name="get_events", args={"n": 1}), thought_signature=b"sig")
        response = assemble_stream(
            [
                _chunk(types.Part(text="plan", thought=True)),
                _chunk(types.Part(text="ning", thought=True)),
                _chunk(call),
                _chunk(types.Part(text="done", thought_signature=b"sig2"), finish=types.FinishReason.STOP),
            ]
        )

        assert response.candidates is not None and response.candidates[0].content is not None
        parts = response.candidates[0].content.parts
        assert parts is not None
        assert [p.text for p in parts] == ["planning", None, "done"]
        assert parts[0].thought is True
        assert parts[1].function_call is not None and parts[1].thought_signature == b"sig"
        assert parts[2].thought_signature == b"sig2"
        assert response.function_calls is not None and response.function_calls[0].name == "get_events"
        assert response.candidates[0].finish_reason == types.FinishReason.STOP

    def test_a_signed_text_part_is_never_merged(self) -> None:
        response = assemble_stream(
            [
                _chunk(types.Part(text="a")),
                _chunk(types.Part(text="b", thought_signature=b"sig")),
                _chunk(types.Part(text="c"), finish=types.FinishReason.STOP),
            ]
        )

        assert response.candidates is not None and response.candidates[0].content is not None
        parts = response.candidates[0].content.parts
        assert parts is not None
        assert [(p.text, p.thought_signature) for p in parts] == [("a", None), ("b", b"sig"), ("c", None)]

    def test_thought_text_does_not_merge_into_answer_text(self) -> None:
        response = assemble_stream(
            [
                _chunk(types.Part(text="think", thought=True)),
                _chunk(types.Part(text="answer"), finish=types.FinishReason.STOP),
            ]
        )

        assert response.candidates is not None and response.candidates[0].content is not None
        parts = response.candidates[0].content.parts
        assert parts is not None and len(parts) == 2
        assert response.text == "answer"

    def test_a_blocked_prompt_keeps_its_feedback(self) -> None:
        blocked = types.GenerateContentResponse(
            prompt_feedback=types.GenerateContentResponsePromptFeedback(block_reason=types.BlockedReason.SAFETY)
        )

        response = assemble_stream([blocked])

        assert not response.candidates
        assert response.prompt_feedback is not None
        assert response.prompt_feedback.block_reason == types.BlockedReason.SAFETY

    @pytest.mark.parametrize(
        "chunks",
        [
            [],
            [_chunk(types.Part(text='{"verdict": "ye'))],
            [
                types.GenerateContentResponse(
                    usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=3)
                )
            ],
        ],
        ids=["empty", "cut-after-text", "usage-only"],
    )
    def test_a_stream_without_a_finish_reason_raises_a_transient_error(
        self, chunks: list[types.GenerateContentResponse]
    ) -> None:
        with pytest.raises(genai_errors.ServerError) as exc_info:
            assemble_stream(chunks)

        assert exc_info.value.code == 503
        assert classify_gemini_error(exc_info.value) == FailureKind.PROVIDER_TRANSIENT


_ERROR_FRAME = {"error": {"code": 503, "message": "upstream idle", "status": "UNAVAILABLE"}}
_PARTIAL = {"candidates": [{"content": {"role": "model", "parts": [{"text": '{"verdict": "ye'}]}}]}


@pytest.mark.parametrize(
    "body",
    [_sse(_PARTIAL, _ERROR_FRAME), _sse(_ERROR_FRAME), _sse(_PARTIAL)],
    ids=["partial-then-error", "error-only", "clean-close-mid-answer"],
)
def test_a_cut_gateway_stream_raises_on_both_surfaces(body: bytes) -> None:
    client, _ = _wired_gateway_client({"feature": "scanner"})
    api_client = client.models._models._api_client
    api_client._httpx_client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})
        )
    )
    api_client._async_httpx_client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})
        )
    )

    with pytest.raises(genai_errors.ServerError):
        client.models.generate_content(model="gemini-test", contents="hi")
    with pytest.raises(genai_errors.ServerError):
        asyncio.run(client.aio.models.generate_content(model="gemini-test", contents="hi"))
