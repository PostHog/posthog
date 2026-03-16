"""
Integration tests for OpenRouter provider through the gateway.

OpenRouter exposes an OpenAI-compatible API, so tests use the openai SDK
with LiteLLM-prefixed model names (openrouter/...).

Skipped unless OPENROUTER_API_KEY is set.
Run with: OPENROUTER_API_KEY=<key> uv run pytest tests/integration/test_openrouter_sdk.py -v
"""

import os

import pytest
from openai import OpenAI

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

pytestmark = pytest.mark.skipif(not OPENROUTER_API_KEY, reason="OPENROUTER_API_KEY not set")

MODEL = "openrouter/meta-llama/llama-3.1-8b-instruct"


class TestOpenRouterChatCompletions:
    def test_non_streaming_request(self, openai_client: OpenAI):
        response = openai_client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": "Say 'hello' and nothing else."}],
            max_tokens=10,
        )

        assert response is not None
        assert len(response.choices) > 0
        assert response.choices[0].message.content is not None
        assert response.usage is not None
        assert response.usage.prompt_tokens > 0
        assert response.usage.completion_tokens > 0

    def test_streaming_request(self, openai_client: OpenAI):
        stream = openai_client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": "Say 'hi' and nothing else."}],
            max_tokens=10,
            stream=True,
        )

        chunks = list(stream)
        assert len(chunks) > 0

        content_chunks = [c for c in chunks if c.choices and c.choices[0].delta.content]
        assert len(content_chunks) > 0

    def test_with_system_message(self, openai_client: OpenAI):
        response = openai_client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that only says 'OK'."},
                {"role": "user", "content": "Hello"},
            ],
            max_tokens=10,
        )

        assert response is not None
        assert response.choices[0].message.content is not None
