"""
Integration tests for streaming usage extraction.

Tests that the gateway correctly proxies streaming responses and extracts usage data.

Run with: ANTHROPIC_API_KEY=... pytest tests/integration/test_streaming_usage.py -v -s
"""

import os

import pytest
from anthropic import Anthropic

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

pytestmark = pytest.mark.skipif(not ANTHROPIC_API_KEY, reason="ANTHROPIC_API_KEY not set")


class TestStreamingUsageExtraction:
    def test_streaming_returns_usage_in_final_message(self, anthropic_client: Anthropic):
        """Verify streaming through gateway returns complete response with usage."""
        with anthropic_client.messages.stream(
            model="claude-3-5-haiku-20241022",
            messages=[{"role": "user", "content": "Say 'hello world' and nothing else."}],
            max_tokens=20,
        ) as stream:
            text = stream.get_final_text()
            message = stream.get_final_message()

        assert text is not None
        assert len(text) > 0
        assert message.usage is not None
        assert message.usage.input_tokens > 0
        assert message.usage.output_tokens > 0
        print(f"\nStreaming usage: input={message.usage.input_tokens}, output={message.usage.output_tokens}")

    def test_non_streaming_returns_usage(self, anthropic_client: Anthropic):
        """Verify non-streaming requests through gateway return usage."""
        response = anthropic_client.messages.create(
            model="claude-3-5-haiku-20241022",
            messages=[{"role": "user", "content": "Say 'test' and nothing else."}],
            max_tokens=10,
        )

        assert response.usage is not None
        assert response.usage.input_tokens > 0
        assert response.usage.output_tokens > 0
        print(f"\nNon-streaming usage: input={response.usage.input_tokens}, output={response.usage.output_tokens}")
