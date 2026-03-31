"""
Integration tests for AWS Bedrock provider through the gateway via the Anthropic routes.

Uses the Anthropic Python SDK pointed at the gateway, with provider="bedrock" in the request body.

Skipped unless AWS credentials and LLM_GATEWAY_BEDROCK_REGION_NAME are set.
Run with:
    AWS_PROFILE=... LLM_GATEWAY_BEDROCK_REGION_NAME=us-east-1 \
        pytest tests/integration/test_bedrock_sdk.py -v
"""

import base64
import os
from typing import Any
from urllib.request import urlopen

import httpx
import pytest

BEDROCK_ENABLED = bool(
    (os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("AWS_PROFILE"))
    and os.environ.get("LLM_GATEWAY_BEDROCK_REGION_NAME")
)

TEST_POSTHOG_API_KEY = "phx_fake_personal_api_key"

pytestmark = pytest.mark.skipif(
    not BEDROCK_ENABLED,
    reason="AWS credentials (AWS_ACCESS_KEY_ID or AWS_PROFILE) or LLM_GATEWAY_BEDROCK_REGION_NAME not set",
)

BEDROCK_HAIKU_MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
TEST_IMAGE_URL = "https://posthog.com/brand/posthog-logo.png"


def _bedrock_request(gateway_url: str, body: dict[str, Any], **kwargs) -> httpx.Response:
    """Send a request to the Anthropic messages endpoint with provider=bedrock."""
    body = {**body, "provider": "bedrock"}
    return httpx.post(
        f"{gateway_url}/v1/messages",
        json=body,
        headers={"Authorization": f"Bearer {TEST_POSTHOG_API_KEY}", **kwargs.get("headers", {})},
        timeout=60.0,
    )


class TestBedrockMessages:
    def test_non_streaming_request(self, gateway_url: str):
        response = _bedrock_request(
            gateway_url,
            {
                "model": BEDROCK_HAIKU_MODEL,
                "messages": [{"role": "user", "content": "Say 'hello' and nothing else."}],
                "max_tokens": 10,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["content"]) > 0
        assert data["content"][0]["type"] == "text"
        assert data["content"][0]["text"] is not None
        assert data["usage"]["input_tokens"] > 0
        assert data["usage"]["output_tokens"] > 0

    def test_streaming_request(self, gateway_url: str):
        body = {
            "model": BEDROCK_HAIKU_MODEL,
            "messages": [{"role": "user", "content": "Say 'hi' and nothing else."}],
            "max_tokens": 10,
            "stream": True,
            "provider": "bedrock",
        }
        with httpx.stream(
            "POST",
            f"{gateway_url}/v1/messages",
            json=body,
            headers={"Authorization": f"Bearer {TEST_POSTHOG_API_KEY}"},
            timeout=60.0,
        ) as response:
            assert response.status_code == 200
            chunks = list(response.iter_lines())
            assert len(chunks) > 0

    def test_with_system_message(self, gateway_url: str):
        response = _bedrock_request(
            gateway_url,
            {
                "model": BEDROCK_HAIKU_MODEL,
                "system": "You are a helpful assistant that only says 'OK'.",
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 10,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["content"]) > 0
        assert data["content"][0]["text"] is not None

    def test_with_temperature(self, gateway_url: str):
        response = _bedrock_request(
            gateway_url,
            {
                "model": BEDROCK_HAIKU_MODEL,
                "messages": [{"role": "user", "content": "Say 'test'"}],
                "max_tokens": 10,
                "temperature": 0.0,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["content"][0]["text"] is not None


class TestBedrockMultipleModels:
    def test_haiku_request(self, gateway_url: str):
        response = _bedrock_request(
            gateway_url,
            {
                "model": BEDROCK_HAIKU_MODEL,
                "messages": [{"role": "user", "content": "Say 'A'"}],
                "max_tokens": 5,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["content"][0]["text"] is not None

    def test_sequential_requests_same_model(self, gateway_url: str):
        response1 = _bedrock_request(
            gateway_url,
            {
                "model": BEDROCK_HAIKU_MODEL,
                "messages": [{"role": "user", "content": "Say '1'"}],
                "max_tokens": 5,
            },
        )

        response2 = _bedrock_request(
            gateway_url,
            {
                "model": BEDROCK_HAIKU_MODEL,
                "messages": [{"role": "user", "content": "Say '2'"}],
                "max_tokens": 5,
            },
        )

        assert response1.status_code == 200
        assert response2.status_code == 200
        assert response1.json()["content"][0]["text"] is not None
        assert response2.json()["content"][0]["text"] is not None


class TestBedrockToolUse:
    def test_tool_definition_and_response(self, gateway_url: str):
        tools = [
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

        response = _bedrock_request(
            gateway_url,
            {
                "model": BEDROCK_HAIKU_MODEL,
                "messages": [{"role": "user", "content": "What's the weather in Paris?"}],
                "tools": tools,
                "max_tokens": 200,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["content"]) > 0

    def test_tool_choice_forced(self, gateway_url: str):
        tools = [
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

        response = _bedrock_request(
            gateway_url,
            {
                "model": BEDROCK_HAIKU_MODEL,
                "messages": [{"role": "user", "content": "What is 2+2?"}],
                "tools": tools,
                "tool_choice": {"type": "tool", "name": "calculate"},
                "max_tokens": 200,
            },
        )

        assert response.status_code == 200
        data = response.json()
        tool_use_blocks = [b for b in data["content"] if b["type"] == "tool_use"]
        assert len(tool_use_blocks) > 0
        assert tool_use_blocks[0]["name"] == "calculate"


class TestBedrockVision:
    def test_image_base64_input(self, gateway_url: str):
        image_data = urlopen(TEST_IMAGE_URL).read()
        base64_image = base64.standard_b64encode(image_data).decode("utf-8")

        response = _bedrock_request(
            gateway_url,
            {
                "model": BEDROCK_HAIKU_MODEL,
                "messages": [
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
                "max_tokens": 100,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["content"][0]["text"] is not None


class TestBedrockMultiTurn:
    def test_conversation_history(self, gateway_url: str):
        response = _bedrock_request(
            gateway_url,
            {
                "model": BEDROCK_HAIKU_MODEL,
                "system": "You are a helpful assistant. Be very brief.",
                "messages": [
                    {"role": "user", "content": "My name is Alice."},
                    {"role": "assistant", "content": "Hello Alice!"},
                    {"role": "user", "content": "What is my name?"},
                ],
                "max_tokens": 20,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "alice" in data["content"][0]["text"].lower()


class TestBedrockCountTokens:
    def test_count_tokens(self, gateway_url: str):
        response = httpx.post(
            f"{gateway_url}/v1/messages/count_tokens",
            json={
                "model": BEDROCK_HAIKU_MODEL,
                "messages": [{"role": "user", "content": "Hello"}],
                "provider": "bedrock",
            },
            headers={"Authorization": f"Bearer {TEST_POSTHOG_API_KEY}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "input_tokens" in data
        assert data["input_tokens"] > 0

    def test_count_tokens_with_custom_max_tokens(self, gateway_url: str):
        response = httpx.post(
            f"{gateway_url}/v1/messages/count_tokens",
            json={
                "model": BEDROCK_HAIKU_MODEL,
                "messages": [{"role": "user", "content": "Hello, how are you?"}],
                "max_tokens": 8192,
                "provider": "bedrock",
            },
            headers={"Authorization": f"Bearer {TEST_POSTHOG_API_KEY}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "input_tokens" in data
        assert data["input_tokens"] > 0


class TestBedrockValidationErrors:
    @pytest.mark.parametrize(
        "invalid_param,value",
        [
            pytest.param("temperature", 5.0, id="temperature_out_of_range"),
            pytest.param("top_p", 5.0, id="top_p_out_of_range"),
        ],
    )
    def test_invalid_parameters_rejected(self, gateway_url: str, invalid_param: str, value: float):
        body = {
            "model": BEDROCK_HAIKU_MODEL,
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 10,
            "provider": "bedrock",
            invalid_param: value,
        }
        response = httpx.post(
            f"{gateway_url}/v1/messages",
            json=body,
            headers={"Authorization": f"Bearer {TEST_POSTHOG_API_KEY}"},
            timeout=60.0,
        )
        assert response.status_code >= 400

    def test_empty_messages_rejected(self, gateway_url: str):
        response = httpx.post(
            f"{gateway_url}/v1/messages",
            json={
                "model": BEDROCK_HAIKU_MODEL,
                "messages": [],
                "max_tokens": 10,
                "provider": "bedrock",
            },
            headers={"Authorization": f"Bearer {TEST_POSTHOG_API_KEY}"},
            timeout=60.0,
        )
        assert response.status_code >= 400
