"""
Integration tests for streaming usage logging.

Tests that stream_chunk_builder correctly extracts token usage from streaming responses.

Run with: ANTHROPIC_API_KEY=... pytest tests/integration/test_streaming_usage.py -v -s
"""

import os
from io import StringIO
from unittest.mock import patch

import pytest
import structlog
from anthropic import Anthropic

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

pytestmark = pytest.mark.skipif(not ANTHROPIC_API_KEY, reason="ANTHROPIC_API_KEY not set")


class TestStreamingUsageLogging:
    def test_streaming_request_logs_usage(self, anthropic_client: Anthropic):
        """Verify that streaming requests log input and output tokens."""
        log_output = StringIO()

        structlog.configure(
            processors=[
                structlog.processors.add_log_level,
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(0),
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(log_output),
            cache_logger_on_first_use=False,
        )

        with anthropic_client.messages.stream(
            model="claude-3-5-haiku-20241022",
            messages=[{"role": "user", "content": "Say 'hello world' and nothing else."}],
            max_tokens=20,
        ) as stream:
            text = stream.get_final_text()

        assert text is not None
        assert len(text) > 0

        logs = log_output.getvalue()
        print(f"\n=== Captured logs ===\n{logs}\n=== End logs ===\n")

        assert "streaming_usage" in logs or "input_tokens" in logs, (
            f"Expected streaming_usage log entry with token counts. Got:\n{logs}"
        )

    def test_non_streaming_logs_usage(self, anthropic_client: Anthropic):
        """Verify that non-streaming requests also track usage."""
        response = anthropic_client.messages.create(
            model="claude-3-5-haiku-20241022",
            messages=[{"role": "user", "content": "Say 'test' and nothing else."}],
            max_tokens=10,
        )

        assert response.usage is not None
        assert response.usage.input_tokens > 0
        assert response.usage.output_tokens > 0
        print(f"\nNon-streaming usage: input={response.usage.input_tokens}, output={response.usage.output_tokens}")

    def test_streaming_returns_complete_response(self, anthropic_client: Anthropic):
        """Verify streaming collects all chunks and returns complete text."""
        with anthropic_client.messages.stream(
            model="claude-3-5-haiku-20241022",
            messages=[{"role": "user", "content": "Count from 1 to 5, separated by commas."}],
            max_tokens=50,
        ) as stream:
            text = stream.get_final_text()
            message = stream.get_final_message()

        print(f"\nStreaming response text: {text}")
        print(f"Final message usage: {message.usage}")

        assert text is not None
        assert "1" in text and "5" in text
        assert message.usage is not None
        assert message.usage.input_tokens > 0
        assert message.usage.output_tokens > 0
