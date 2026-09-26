import json
import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

import httpx
from google.genai import types

from products.replay_vision.backend import (
    feedback_themes,
    prompt_suggestions,
    scanner_draft,
    search_suggestions,
    tag_suggestions,
)
from products.replay_vision.backend.gemini_client import GatewayGeminiClient, replay_gemini_client

_GATEWAY = {"AI_GATEWAY_URL": "https://ai-gateway.example/v1", "AI_GATEWAY_API_KEY": "phs_test"}
_UNSET = {"AI_GATEWAY_URL": "", "AI_GATEWAY_API_KEY": ""}
_OK = {"candidates": [{"content": {"role": "model", "parts": [{"text": "ok"}]}}]}


def _wired_gateway_client(properties: dict[str, Any]) -> tuple[GatewayGeminiClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_OK)

    with override_settings(**_GATEWAY):
        client = replay_gemini_client(MagicMock(), properties=properties, distinct_id="replay-vision:42")
    assert isinstance(client, GatewayGeminiClient)
    api_client = client.models._models._api_client
    api_client._httpx_client = httpx.Client(transport=httpx.MockTransport(handler))
    api_client._async_httpx_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client, seen


class TestReplayGeminiClient:
    def test_direct_mode_returns_the_callers_client(self) -> None:
        direct = MagicMock()
        with override_settings(**_UNSET):
            assert replay_gemini_client(direct) is direct.return_value

    def test_gateway_mode_never_builds_the_direct_client(self) -> None:
        direct = MagicMock()
        with override_settings(**_GATEWAY), patch("posthog.llm.gateway_client.genai.Client"):
            assert isinstance(replay_gemini_client(direct), GatewayGeminiClient)
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
        assert str(request.url) == "https://ai-gateway.example/v1beta/models/gemini-test:generateContent"
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
        gateway_client.return_value.models.generate_content.side_effect = RuntimeError("stop")
        with pytest.raises(Exception):
            call()

    direct_client.assert_not_called()
    gateway_client.return_value.models.generate_content.assert_called()
    headers = gateway_client.call_args.kwargs["http_options"].headers
    assert headers["X-PostHog-Product"] == "replay_vision"
    assert headers["X-PostHog-Privacy-Mode"] == "true"
    request_headers = gateway_client.return_value.models.generate_content.call_args.kwargs[
        "config"
    ].http_options.headers
    labels = json.loads(request_headers["X-PostHog-Properties"])
    assert labels["ai_product"] == "replay_vision"
    assert labels["team_id"] == "1"
    assert labels["feature"]
    assert request_headers["X-PostHog-Distinct-Id"] == "u"
