import json
from typing import Any
from unittest.mock import MagicMock, patch

from django.test import TestCase

from products.editor.backend.providers.anthropic import AnthropicConfig, AnthropicProvider


@patch("django.conf.settings.ANTHROPIC_API_KEY", "test_key")
class TestAnthropicProvider(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.model_id = "claude-3-5-sonnet-20241022"

    def test_init_validates_model(self):
        # Valid model
        provider = AnthropicProvider(self.model_id)
        self.assertEqual(provider.model_id, self.model_id)

        # Invalid model
        with self.assertRaises(ValueError) as cm:
            AnthropicProvider("invalid-model")
        self.assertEqual(str(cm.exception), "Model invalid-model is not supported")

    def test_validate_messages(self):
        provider = AnthropicProvider(self.model_id)

        # Valid messages
        valid_messages = [{"role": "user", "content": "test"}]
        provider.validate_messages(valid_messages)  # Should not raise

        # Empty messages
        with self.assertRaises(ValueError) as cm:
            provider.validate_messages([])
        self.assertEqual(str(cm.exception), "Messages list cannot be empty")

        # Missing role
        with self.assertRaises(ValueError) as cm:
            provider.validate_messages([{"content": "test"}])
        self.assertEqual(str(cm.exception), "Each message must contain 'role' and 'content' fields")

        # Missing content
        with self.assertRaises(ValueError) as cm:
            provider.validate_messages([{"role": "user"}])
        self.assertEqual(str(cm.exception), "Each message must contain 'role' and 'content' fields")

    @patch("anthropic.Anthropic")
    def test_prepare_messages_with_cache_control(self, mock_anthropic):
        provider = AnthropicProvider(self.model_id)
        messages = [
            {"role": "assistant", "content": [{"type": "text", "text": "Hello, how can I help you?"}]},
            {"role": "user", "content": [{"type": "text", "text": "Test"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "How can I help?"}]},
            {"role": "user", "content": [{"type": "text", "text": "Test"}]},
        ]

        prepared_messages = provider.prepare_messages_with_cache_control(messages)

        # Check that only the last and second-to-last user messages are marked ephemeral
        self.assertEqual(len(prepared_messages), 4)

        # Convert MessageParam objects to dicts for easier testing
        prepared_dicts: list[dict[str, Any]] = []
        for msg in prepared_messages:
            content_blocks: list[dict[str, Any]] = []
            for block in msg["content"]:
                if isinstance(block, dict) and block.get("type") == "text":
                    content_blocks.append(
                        {"type": "text", "text": block.get("text", ""), "cache_control": block.get("cache_control")}
                    )
            prepared_dicts.append({"role": msg["role"], "content": content_blocks})
        # First assistant message - no cache control
        self.assertIsNone(prepared_dicts[0]["content"][0]["cache_control"])

        # First user message - should be ephemeral
        self.assertEqual(prepared_dicts[1]["content"][0]["cache_control"], {"type": "ephemeral"})

        # Second assistant message - no cache control
        self.assertIsNone(prepared_dicts[2]["content"][0]["cache_control"])

        # Last user message - should be ephemeral
        self.assertEqual(prepared_dicts[3]["content"][0]["cache_control"], {"type": "ephemeral"})

    @patch("anthropic.Anthropic")
    def test_stream_response_with_thinking(self, mock_anthropic):
        provider = AnthropicProvider("claude-3-7-sonnet-20250219")
        mock_stream = MagicMock()
        mock_anthropic.return_value.messages.create.return_value = mock_stream

        # Mock stream chunks
        # Mock stream chunks with proper attribute access
        mock_stream.__iter__.return_value = [
            type(
                "MessageStart",
                (),
                {
                    "type": "message_start",
                    "message": type(
                        "Message",
                        (),
                        {
                            "usage": type(
                                "Usage",
                                (),
                                {
                                    "input_tokens": 10,
                                    "output_tokens": 20,
                                    "cache_creation_input_tokens": None,
                                    "cache_read_input_tokens": None,
                                },
                            )
                        },
                    ),
                },
            )(),
            type(
                "ContentBlockStart",
                (),
                {
                    "type": "content_block_start",
                    "content_block": type("ContentBlock", (), {"type": "thinking", "thinking": "Reasoning..."}),
                    "index": 0,
                },
            )(),
            type(
                "ContentBlockDelta",
                (),
                {
                    "type": "content_block_delta",
                    "delta": type("Delta", (), {"type": "thinking_delta", "thinking": " more reasoning"}),
                },
            )(),
            type(
                "ContentBlockStart",
                (),
                {
                    "type": "content_block_start",
                    "content_block": type("ContentBlock", (), {"type": "text", "text": "Final answer"}),
                    "index": 1,
                },
            )(),
        ]

        system = "test system"
        messages = [{"role": "user", "content": "test"}]

        response_stream = provider.stream_response(system, messages, thinking=True)
        responses = list(response_stream)

        # Verify the responses
        self.assertEqual(
            json.loads(responses[0].split("data: ")[1]),
            {"type": "usage", "input_tokens": 10, "output_tokens": 20, "cache_writes": None, "cache_reads": None},
        )
        self.assertEqual(
            json.loads(responses[1].split("data: ")[1]), {"type": "reasoning", "reasoning": "Reasoning..."}
        )
        self.assertEqual(
            json.loads(responses[2].split("data: ")[1]), {"type": "reasoning", "reasoning": " more reasoning"}
        )
        self.assertEqual(json.loads(responses[3].split("data: ")[1]), {"type": "text", "text": "\n"})
        self.assertEqual(json.loads(responses[4].split("data: ")[1]), {"type": "text", "text": "Final answer"})

        # Verify thinking config was passed
        mock_anthropic.return_value.messages.create.assert_called_once()
        call_kwargs = mock_anthropic.return_value.messages.create.call_args[1]
        self.assertEqual(call_kwargs["thinking"]["type"], "enabled")
        self.assertEqual(call_kwargs["thinking"]["budget_tokens"], AnthropicConfig.MAX_THINKING_TOKENS)

    @patch("anthropic.Anthropic")
    def test_stream_response_without_thinking(self, mock_anthropic):
        provider = AnthropicProvider(self.model_id)
        mock_stream = MagicMock()
        mock_anthropic.return_value.messages.create.return_value = mock_stream

        # Mock stream chunks
        mock_stream.__iter__.return_value = [
            type(
                "MessageStart",
                (),
                {
                    "type": "message_start",
                    "message": type(
                        "Message", (), {"usage": type("Usage", (), {"input_tokens": 5, "output_tokens": 10})}
                    ),
                },
            )(),
            type(
                "ContentBlockStart",
                (),
                {
                    "type": "content_block_start",
                    "content_block": type("ContentBlock", (), {"type": "text", "text": "Answer"}),
                    "index": 0,
                },
            )(),
        ]

        system = "test system"
        messages = [{"role": "user", "content": "test"}]

        response_stream = provider.stream_response(system, messages, thinking=False)
        responses = list(response_stream)

        # Verify the responses
        self.assertEqual(
            json.loads(responses[0].split("data: ")[1]),
            {"type": "usage", "input_tokens": 5, "output_tokens": 10, "cache_writes": None, "cache_reads": None},
        )
        self.assertEqual(json.loads(responses[1].split("data: ")[1]), {"type": "text", "text": "Answer"})

        # Verify thinking config was not passed
        mock_anthropic.return_value.messages.create.assert_called_once()
        self.assertNotIn("thinking", mock_anthropic.return_value.messages.create.call_args[1])

    @patch("anthropic.Anthropic")
    def test_stream_response_handles_api_error(self, mock_anthropic):
        provider = AnthropicProvider(self.model_id)
        mock_anthropic.return_value.messages.create.side_effect = Exception("API Error")

        system = "test system"
        messages = [{"role": "user", "content": "test"}]

        response_stream = provider.stream_response(system, messages)
        responses = list(response_stream)

        self.assertEqual(len(responses), 1)
        self.assertIn("error", json.loads(responses[0].split("data: ")[1]))

    @patch("anthropic.Anthropic")
    def test_stream_response_with_cache_control(self, mock_anthropic):
        provider = AnthropicProvider(self.model_id)  # Using a model that supports cache control
        mock_stream = MagicMock()
        mock_anthropic.return_value.messages.create.return_value = mock_stream

        # Mock stream chunks with cache metrics
        mock_stream.__iter__.return_value = [
            MagicMock(
                type="message_start",
                message=MagicMock(
                    usage=MagicMock(
                        input_tokens=10, output_tokens=20, cache_creation_input_tokens=5, cache_read_input_tokens=3
                    )
                ),
            )
        ]

        system = "test system"
        messages = [{"role": "user", "content": "test"}]

        response_stream = provider.stream_response(system, messages)
        responses = list(response_stream)

        # Verify cache metrics in response
        self.assertEqual(
            json.loads(responses[0].split("data: ")[1]),
            {"type": "usage", "input_tokens": 10, "output_tokens": 20, "cache_writes": 5, "cache_reads": 3},
        )

        # Verify system message has ephemeral cache control
        mock_anthropic.return_value.messages.create.assert_called_once()
        call_kwargs = mock_anthropic.return_value.messages.create.call_args[1]
        self.assertEqual(call_kwargs["system"][0]["cache_control"], {"type": "ephemeral"})
