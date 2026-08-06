"""
Integration tests using the official Anthropic Python SDK through the gateway.

Skipped unless ANTHROPIC_API_KEY is set (for anthropic provider) or
LLM_GATEWAY_BEDROCK_REGION_NAME / AWS_REGION / AWS_DEFAULT_REGION is set
(for bedrock provider).
Run with: pytest tests/integration/test_anthropic_sdk.py -v
"""

import base64
import os
from dataclasses import dataclass
from typing import Any
from urllib.request import urlopen

import pytest
from anthropic import Anthropic, BadRequestError
from anthropic.types import TextBlock, ToolParam, ToolUseBlock

from .conftest import (
    BEDROCK_REGION,
    CLOUDFLARE_ACCOUNT_ID,
    CLOUDFLARE_API_KEY,
    CLOUDFLARE_MAX_RETRIES,
    CLOUDFLARE_REQUEST_TIMEOUT,
    CLOUDFLARE_SMOKE_MODELS,
    TEST_POSTHOG_API_KEY,
)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
CLOUDFLARE_CONFIGURED = bool(CLOUDFLARE_API_KEY and CLOUDFLARE_ACCOUNT_ID)

TEST_IMAGE_URL = "https://posthog.com/brand/posthog-logo.png"


pytestmark = pytest.mark.xfail(strict=False, reason="Anthropic may be rate-limited or temporarily unavailable")


def _get_text_block(response) -> TextBlock:
    """Extract the first TextBlock from a response, skipping ThinkingBlocks."""
    for block in response.content:
        if isinstance(block, TextBlock):
            return block
    raise AssertionError(f"No TextBlock found in response content: {response.content}")


def _skip_cloudflare_full_matrix(provider: str) -> None:
    """Smoke-test the Cloudflare routing path, don't run the whole behavioural matrix against it.

    CF Workers AI calls are slow and high-variance, so running every SDK behaviour against them
    blows the CI time budget. The adapter paths that matter (non-streaming, streaming, tool use)
    are smoke-tested elsewhere in this file; the rest of the matrix is covered by the other providers.
    """
    if provider == "cloudflare":
        pytest.skip("Cloudflare routing covered by smoke tests; skipping full matrix to bound CI time")


@dataclass
class SDKTestConfig:
    client: Anthropic
    model: str
    provider: str


@pytest.fixture(
    params=[
        pytest.param(
            "anthropic",
            id="anthropic",
            marks=pytest.mark.skipif(not ANTHROPIC_API_KEY, reason="ANTHROPIC_API_KEY not set"),
        ),
        pytest.param(
            "bedrock",
            id="bedrock",
            marks=pytest.mark.skipif(not BEDROCK_REGION, reason="Bedrock region not configured"),
        ),
        pytest.param(
            "cloudflare",
            id="cloudflare",
            marks=pytest.mark.skipif(not CLOUDFLARE_CONFIGURED, reason="CLOUDFLARE_API_KEY/ACCOUNT_ID not set"),
        ),
    ]
)
def sdk_config(request) -> SDKTestConfig:
    if request.param == "anthropic":
        url = request.getfixturevalue("gateway_url")
        client = Anthropic(api_key=TEST_POSTHOG_API_KEY, base_url=url)
        return SDKTestConfig(client=client, model="claude-haiku-4-5-20251001", provider="anthropic")
    elif request.param == "cloudflare":
        url = request.getfixturevalue("cloudflare_gateway_url")
        client = Anthropic(
            api_key=TEST_POSTHOG_API_KEY,
            base_url=url,
            default_headers={"X-PostHog-Provider": "cloudflare"},
            timeout=CLOUDFLARE_REQUEST_TIMEOUT,
            max_retries=CLOUDFLARE_MAX_RETRIES,
        )
        return SDKTestConfig(client=client, model="@cf/moonshotai/kimi-k2.6", provider="cloudflare")
    else:
        url = request.getfixturevalue("bedrock_gateway_url")
        client = Anthropic(
            api_key=TEST_POSTHOG_API_KEY,
            base_url=url,
            default_headers={"X-PostHog-Provider": "bedrock"},
        )
        return SDKTestConfig(client=client, model="claude-haiku-4-5", provider="bedrock")


class TestAnthropicMessages:
    def test_non_streaming_request(self, sdk_config: SDKTestConfig):
        response = sdk_config.client.messages.create(
            model=sdk_config.model,
            messages=[{"role": "user", "content": "Say 'hello' and nothing else."}],
            max_tokens=300,
        )

        assert response is not None
        assert len(response.content) > 0
        text_block = _get_text_block(response)
        assert text_block.text is not None
        assert response.usage is not None
        assert response.usage.input_tokens > 0
        assert response.usage.output_tokens > 0

    def test_streaming_request(self, sdk_config: SDKTestConfig):
        with sdk_config.client.messages.stream(
            model=sdk_config.model,
            messages=[{"role": "user", "content": "Say 'hi' and nothing else."}],
            max_tokens=300,
        ) as stream:
            text = stream.get_final_text()

        assert text is not None
        assert len(text) > 0

    def test_with_system_message(self, sdk_config: SDKTestConfig):
        _skip_cloudflare_full_matrix(sdk_config.provider)
        response = sdk_config.client.messages.create(
            model=sdk_config.model,
            system="You are a helpful assistant that only says 'OK'.",
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=300,
        )

        assert response is not None
        text_block = _get_text_block(response)
        assert text_block.text is not None

    def test_with_temperature(self, sdk_config: SDKTestConfig):
        _skip_cloudflare_full_matrix(sdk_config.provider)
        response = sdk_config.client.messages.create(
            model=sdk_config.model,
            messages=[{"role": "user", "content": "Say 'test'"}],
            max_tokens=300,
            temperature=0.0,
        )

        assert response is not None
        text_block = _get_text_block(response)
        assert text_block.text is not None

    @pytest.mark.skipif(not CLOUDFLARE_CONFIGURED, reason="CLOUDFLARE_API_KEY/ACCOUNT_ID not set")
    @pytest.mark.parametrize("model", CLOUDFLARE_SMOKE_MODELS)
    def test_each_cloudflare_model_routes_and_bills(self, cloudflare_anthropic_client: Anthropic, model: str):
        response = cloudflare_anthropic_client.messages.create(
            model=model,
            messages=[{"role": "user", "content": "Say 'hello' and nothing else."}],
            max_tokens=300,
        )

        text_block = _get_text_block(response)
        assert text_block.text is not None
        assert response.usage is not None
        assert response.usage.input_tokens > 0
        assert response.usage.output_tokens > 0


class TestAnthropicMultipleModels:
    def test_basic_request(self, sdk_config: SDKTestConfig):
        _skip_cloudflare_full_matrix(sdk_config.provider)
        response = sdk_config.client.messages.create(
            model=sdk_config.model,
            messages=[{"role": "user", "content": "Say 'A'"}],
            max_tokens=200,
        )

        assert response is not None
        text_block = _get_text_block(response)
        assert text_block.text is not None

    def test_sequential_requests_same_model(self, sdk_config: SDKTestConfig):
        _skip_cloudflare_full_matrix(sdk_config.provider)
        response1 = sdk_config.client.messages.create(
            model=sdk_config.model,
            messages=[{"role": "user", "content": "Say '1'"}],
            max_tokens=200,
        )

        response2 = sdk_config.client.messages.create(
            model=sdk_config.model,
            messages=[{"role": "user", "content": "Say '2'"}],
            max_tokens=200,
        )

        assert _get_text_block(response1).text is not None
        assert _get_text_block(response2).text is not None

    def test_streaming_then_non_streaming(self, sdk_config: SDKTestConfig):
        _skip_cloudflare_full_matrix(sdk_config.provider)
        with sdk_config.client.messages.stream(
            model=sdk_config.model,
            messages=[{"role": "user", "content": "Say 'stream'"}],
            max_tokens=300,
        ) as stream:
            text = stream.get_final_text()
        assert len(text) > 0

        response = sdk_config.client.messages.create(
            model=sdk_config.model,
            messages=[{"role": "user", "content": "Say 'sync'"}],
            max_tokens=300,
        )
        assert _get_text_block(response).text is not None


class TestAnthropicToolUse:
    def test_tool_definition_and_response(self, sdk_config: SDKTestConfig):
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

        response = sdk_config.client.messages.create(
            model=sdk_config.model,
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

    def test_tool_choice_forced(self, sdk_config: SDKTestConfig):
        _skip_cloudflare_full_matrix(sdk_config.provider)
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

        response = sdk_config.client.messages.create(
            model=sdk_config.model,
            messages=[{"role": "user", "content": "What is 2+2?"}],
            tools=tools,
            tool_choice={"type": "tool", "name": "calculate"},
            max_tokens=200,
        )

        tool_use_blocks = [b for b in response.content if isinstance(b, ToolUseBlock)]
        assert len(tool_use_blocks) > 0
        assert tool_use_blocks[0].name == "calculate"


class TestAnthropicVision:
    def test_image_url_input(self, sdk_config: SDKTestConfig):
        if sdk_config.provider in ("bedrock", "cloudflare"):
            pytest.skip(f"{sdk_config.provider} does not support URL image source via Anthropic format")

        response = sdk_config.client.messages.create(
            model=sdk_config.model,
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
            max_tokens=200,
        )

        assert response is not None
        assert len(response.content) > 0
        text_block = _get_text_block(response)
        assert text_block.text is not None

    def test_image_base64_input(self, sdk_config: SDKTestConfig):
        if sdk_config.provider == "cloudflare":
            pytest.skip("Cloudflare adapter does not support Anthropic vision content blocks")
        image_data = urlopen(TEST_IMAGE_URL).read()
        base64_image = base64.standard_b64encode(image_data).decode("utf-8")

        response = sdk_config.client.messages.create(
            model=sdk_config.model,
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
            max_tokens=300,
        )

        assert response is not None
        assert len(response.content) > 0
        text_block = _get_text_block(response)
        assert text_block.text is not None


class TestAnthropicMultiTurn:
    def test_conversation_history(self, sdk_config: SDKTestConfig):
        _skip_cloudflare_full_matrix(sdk_config.provider)
        response = sdk_config.client.messages.create(
            model=sdk_config.model,
            system="You are a helpful assistant. Be very brief.",
            messages=[
                {"role": "user", "content": "My name is Alice."},
                {"role": "assistant", "content": "Hello Alice!"},
                {"role": "user", "content": "What is my name?"},
            ],
            max_tokens=300,
        )

        assert response is not None
        text_block = _get_text_block(response)
        assert "alice" in text_block.text.lower()


class TestAnthropicValidationErrors:
    @pytest.mark.parametrize(
        "invalid_param,value,expected_error",
        [
            pytest.param("temperature", 5.0, "temperature", id="temperature_out_of_range"),
            pytest.param("top_p", 5.0, "top_p", id="top_p_out_of_range"),
        ],
    )
    def test_invalid_parameters_rejected(
        self, sdk_config: SDKTestConfig, invalid_param: str, value: float, expected_error: str
    ):
        if sdk_config.provider == "cloudflare":
            pytest.skip("Cloudflare Workers AI handles parameter validation differently")
        kwargs: dict[str, Any] = {
            "model": sdk_config.model,
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 10,
            invalid_param: value,
        }
        with pytest.raises(BadRequestError) as exc_info:
            sdk_config.client.messages.create(**kwargs)
        assert expected_error in str(exc_info.value).lower()

    def test_empty_messages_rejected(self, sdk_config: SDKTestConfig):
        if sdk_config.provider == "cloudflare":
            pytest.skip("Cloudflare Workers AI handles parameter validation differently")
        with pytest.raises(BadRequestError) as exc_info:
            sdk_config.client.messages.create(
                model=sdk_config.model,
                messages=[],
                max_tokens=10,
            )
        assert "messages" in str(exc_info.value).lower()
