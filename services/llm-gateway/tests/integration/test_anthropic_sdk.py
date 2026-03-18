"""
Integration tests using the official Anthropic Python SDK through the gateway.

Skipped unless ANTHROPIC_API_KEY is set.
Run with: pytest tests/integration/test_anthropic_sdk.py -v
"""

import base64
import os
from typing import Any
from urllib.request import urlopen

import pytest
from anthropic import Anthropic, BadRequestError
from anthropic.types import TextBlock, ToolParam, ToolUseBlock

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

pytestmark = pytest.mark.skipif(not ANTHROPIC_API_KEY, reason="ANTHROPIC_API_KEY not set")

TEST_IMAGE_URL = "https://posthog.com/brand/posthog-logo.png"


class TestAnthropicMessages:
    def test_non_streaming_request(self, anthropic_client: Anthropic):
        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            messages=[{"role": "user", "content": "Say 'hello' and nothing else."}],
            max_tokens=10,
        )

        assert response is not None
        assert len(response.content) > 0
        first_block = response.content[0]
        assert isinstance(first_block, TextBlock)
        assert first_block.text is not None
        assert response.usage is not None
        assert response.usage.input_tokens > 0
        assert response.usage.output_tokens > 0

    def test_streaming_request(self, anthropic_client: Anthropic):
        with anthropic_client.messages.stream(
            model="claude-3-haiku-20240307",
            messages=[{"role": "user", "content": "Say 'hi' and nothing else."}],
            max_tokens=10,
        ) as stream:
            text = stream.get_final_text()

        assert text is not None
        assert len(text) > 0

    def test_with_system_message(self, anthropic_client: Anthropic):
        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            system="You are a helpful assistant that only says 'OK'.",
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=10,
        )

        assert response is not None
        first_block = response.content[0]
        assert isinstance(first_block, TextBlock)
        assert first_block.text is not None

    def test_with_temperature(self, anthropic_client: Anthropic):
        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            messages=[{"role": "user", "content": "Say 'test'"}],
            max_tokens=10,
            temperature=0.0,
        )

        assert response is not None
        first_block = response.content[0]
        assert isinstance(first_block, TextBlock)
        assert first_block.text is not None


class TestAnthropicMultipleModels:
    def test_haiku_request(self, anthropic_client: Anthropic):
        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            messages=[{"role": "user", "content": "Say 'A'"}],
            max_tokens=5,
        )

        assert response is not None
        first_block = response.content[0]
        assert isinstance(first_block, TextBlock)
        assert first_block.text is not None

    def test_sequential_requests_same_model(self, anthropic_client: Anthropic):
        response1 = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            messages=[{"role": "user", "content": "Say '1'"}],
            max_tokens=5,
        )

        response2 = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            messages=[{"role": "user", "content": "Say '2'"}],
            max_tokens=5,
        )

        first_block1 = response1.content[0]
        first_block2 = response2.content[0]
        assert isinstance(first_block1, TextBlock)
        assert isinstance(first_block2, TextBlock)
        assert first_block1.text is not None
        assert first_block2.text is not None

    def test_streaming_then_non_streaming(self, anthropic_client: Anthropic):
        with anthropic_client.messages.stream(
            model="claude-3-haiku-20240307",
            messages=[{"role": "user", "content": "Say 'stream'"}],
            max_tokens=10,
        ) as stream:
            text = stream.get_final_text()
        assert len(text) > 0

        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            messages=[{"role": "user", "content": "Say 'sync'"}],
            max_tokens=10,
        )
        first_block = response.content[0]
        assert isinstance(first_block, TextBlock)
        assert first_block.text is not None


class TestAnthropicToolUse:
    def test_tool_definition_and_response(self, anthropic_client: Anthropic):
        tools: list[ToolParam] = [
            {
                "name": "get_weather",
                "description": "Get the current weather in a location",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "location": {"type": "string", "description": "City name"},
                        "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
                    },
                    "required": ["location"],
                },
            }
        ]

        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            messages=[{"role": "user", "content": "What's the weather in Paris?"}],
            tools=tools,
            max_tokens=200,
        )

        assert response is not None
        assert len(response.content) > 0
        tool_use_blocks = [b for b in response.content if isinstance(b, ToolUseBlock)]
        if tool_use_blocks:
            tool_use = tool_use_blocks[0]
            assert tool_use.name == "get_weather"
            assert isinstance(tool_use.input, dict)
            assert "location" in tool_use.input

    def test_tool_choice_forced(self, anthropic_client: Anthropic):
        tools: list[ToolParam] = [
            {
                "name": "calculate",
                "description": "Perform a calculation",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "expression": {"type": "string"},
                    },
                    "required": ["expression"],
                },
            }
        ]

        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            messages=[{"role": "user", "content": "What is 2+2?"}],
            tools=tools,
            tool_choice={"type": "tool", "name": "calculate"},
            max_tokens=200,
        )

        tool_use_blocks = [b for b in response.content if isinstance(b, ToolUseBlock)]
        assert len(tool_use_blocks) > 0
        assert tool_use_blocks[0].name == "calculate"


class TestAnthropicVision:
    def test_image_url_input(self, anthropic_client: Anthropic):
        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What company logo is this? Reply with just the company name."},
                        {
                            "type": "image",
                            "source": {"type": "url", "url": TEST_IMAGE_URL},
                        },
                    ],
                }
            ],
            max_tokens=50,
        )

        assert response is not None
        assert len(response.content) > 0
        first_block = response.content[0]
        assert isinstance(first_block, TextBlock)
        assert first_block.text is not None

    def test_image_base64_input(self, anthropic_client: Anthropic):
        image_data = urlopen(TEST_IMAGE_URL).read()
        base64_image = base64.standard_b64encode(image_data).decode("utf-8")

        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe this image briefly."},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": base64_image,
                            },
                        },
                    ],
                }
            ],
            max_tokens=100,
        )

        assert response is not None
        assert len(response.content) > 0
        first_block = response.content[0]
        assert isinstance(first_block, TextBlock)
        assert first_block.text is not None


class TestAnthropicMultiTurn:
    def test_conversation_history(self, anthropic_client: Anthropic):
        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            system="You are a helpful assistant. Be very brief.",
            messages=[
                {"role": "user", "content": "My name is Alice."},
                {"role": "assistant", "content": "Hello Alice!"},
                {"role": "user", "content": "What is my name?"},
            ],
            max_tokens=20,
        )

        assert response is not None
        first_block = response.content[0]
        assert isinstance(first_block, TextBlock)
        assert "alice" in first_block.text.lower()


class TestAnthropicValidationErrors:
    @pytest.mark.parametrize(
        "invalid_param,value,expected_error",
        [
            pytest.param("temperature", 5.0, "temperature", id="temperature_out_of_range"),
            pytest.param("top_p", 5.0, "top_p", id="top_p_out_of_range"),
        ],
    )
    def test_invalid_parameters_rejected(
        self, anthropic_client: Anthropic, invalid_param: str, value: float, expected_error: str
    ):
        kwargs: dict[str, Any] = {
            "model": "claude-3-haiku-20240307",
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 10,
            invalid_param: value,
        }
        with pytest.raises(BadRequestError) as exc_info:
            anthropic_client.messages.create(**kwargs)
        assert expected_error in str(exc_info.value).lower()

    def test_empty_messages_rejected(self, anthropic_client: Anthropic):
        with pytest.raises(BadRequestError) as exc_info:
            anthropic_client.messages.create(
                model="claude-3-haiku-20240307",
                messages=[],
                max_tokens=10,
            )
        assert "messages" in str(exc_info.value).lower()
