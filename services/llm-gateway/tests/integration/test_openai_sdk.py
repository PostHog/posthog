"""
Integration tests using the official OpenAI Python SDK through the gateway.

Most tests skipped unless OPENAI_API_KEY is set.
Run with: pytest tests/integration/test_openai_sdk.py -v
"""

import json
import os
from dataclasses import dataclass
from typing import Any

import pytest
from openai import BadRequestError, OpenAI
from openai.types import Model
from openai.types.chat import ChatCompletionToolChoiceOptionParam, ChatCompletionToolParam

from .conftest import CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_KEY, CLOUDFLARE_SMOKE_MODELS

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
CLOUDFLARE_CONFIGURED = bool(CLOUDFLARE_API_KEY and CLOUDFLARE_ACCOUNT_ID)

skip_without_openai_key = pytest.mark.skipif(not OPENAI_API_KEY, reason="OPENAI_API_KEY not set")
xfail_provider_unavailable = pytest.mark.xfail(
    strict=False, reason="OpenAI may be rate-limited or temporarily unavailable"
)

TEST_IMAGE_URL = "https://posthog.com/brand/posthog-logo.png"


def _skip_cloudflare_full_matrix(provider: str) -> None:
    """Smoke-test the Cloudflare routing path, don't run the whole behavioural matrix against it.

    CF Workers AI calls are slow and high-variance, so running every SDK behaviour against them
    blows the CI time budget. The core adapter paths (non-streaming, streaming) are smoke-tested
    elsewhere in this file; the rest of the matrix is covered by the OpenAI provider.
    """
    if provider == "cloudflare":
        pytest.skip("Cloudflare routing covered by smoke tests; skipping full matrix to bound CI time")


@dataclass
class OpenAISDKTestConfig:
    client: OpenAI
    model: str
    provider: str


@pytest.fixture(
    params=[
        pytest.param(
            "openai",
            id="openai",
            marks=[pytest.mark.skipif(not OPENAI_API_KEY, reason="OPENAI_API_KEY not set"), xfail_provider_unavailable],
        ),
        pytest.param(
            "cloudflare",
            id="cloudflare",
            marks=pytest.mark.skipif(not CLOUDFLARE_CONFIGURED, reason="CLOUDFLARE_API_KEY/ACCOUNT_ID not set"),
        ),
    ]
)
def oai_sdk_config(request) -> OpenAISDKTestConfig:
    if request.param == "openai":
        client = request.getfixturevalue("openai_client")
        return OpenAISDKTestConfig(client=client, model="gpt-4o-mini", provider="openai")
    else:
        client = request.getfixturevalue("cloudflare_openai_client")
        return OpenAISDKTestConfig(client=client, model="@cf/moonshotai/kimi-k2.6", provider="cloudflare")


class TestOpenAIModelsEndpoint:
    def test_sdk_models_list_returns_models(self, openai_client_all_providers: OpenAI):
        models = list(openai_client_all_providers.models.list())
        assert len(models) > 0

    def test_sdk_model_objects_are_valid_type(self, openai_client_all_providers: OpenAI):
        models = list(openai_client_all_providers.models.list())
        for model in models:
            assert isinstance(model, Model)

    @pytest.mark.parametrize(
        "field,expected_type",
        [
            ("id", str),
            ("created", int),
            ("owned_by", str),
        ],
    )
    def test_model_has_required_openai_fields(
        self, openai_client_all_providers: OpenAI, field: str, expected_type: type
    ):
        models = list(openai_client_all_providers.models.list())
        model = models[0]
        assert hasattr(model, field)
        assert isinstance(getattr(model, field), expected_type)

    def test_model_object_field_is_model(self, openai_client_all_providers: OpenAI):
        models = list(openai_client_all_providers.models.list())
        model = models[0]
        assert model.object == "model"


class TestChatCompletions:
    def test_non_streaming_request(self, oai_sdk_config: OpenAISDKTestConfig):
        response = oai_sdk_config.client.chat.completions.create(
            model=oai_sdk_config.model,
            messages=[{"role": "user", "content": "Say 'hello' and nothing else."}],
            max_tokens=300,
        )

        assert response is not None
        assert len(response.choices) > 0
        assert response.choices[0].message.content is not None
        assert response.usage is not None
        assert response.usage.prompt_tokens > 0
        assert response.usage.completion_tokens > 0

    def test_streaming_request(self, oai_sdk_config: OpenAISDKTestConfig):
        stream = oai_sdk_config.client.chat.completions.create(
            model=oai_sdk_config.model,
            messages=[{"role": "user", "content": "Say 'hi' and nothing else."}],
            max_tokens=300,
            stream=True,
        )

        chunks = list(stream)
        assert len(chunks) > 0

        content_chunks = [c for c in chunks if c.choices and c.choices[0].delta.content]
        assert len(content_chunks) > 0

    def test_with_system_message(self, oai_sdk_config: OpenAISDKTestConfig):
        _skip_cloudflare_full_matrix(oai_sdk_config.provider)
        response = oai_sdk_config.client.chat.completions.create(
            model=oai_sdk_config.model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that only says 'OK'."},
                {"role": "user", "content": "Hello"},
            ],
            max_tokens=300,
        )

        assert response is not None
        assert response.choices[0].message.content is not None

    def test_with_temperature(self, oai_sdk_config: OpenAISDKTestConfig):
        _skip_cloudflare_full_matrix(oai_sdk_config.provider)
        response = oai_sdk_config.client.chat.completions.create(
            model=oai_sdk_config.model,
            messages=[{"role": "user", "content": "Say 'test'"}],
            max_tokens=300,
            temperature=0.0,
        )

        assert response is not None
        assert response.choices[0].message.content is not None

    @pytest.mark.skipif(not CLOUDFLARE_CONFIGURED, reason="CLOUDFLARE_API_KEY/ACCOUNT_ID not set")
    @pytest.mark.parametrize("model", CLOUDFLARE_SMOKE_MODELS)
    def test_each_cloudflare_model_routes_and_bills(self, cloudflare_openai_client: OpenAI, model: str):
        response = cloudflare_openai_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Say 'hello' and nothing else."}],
            max_tokens=300,
        )

        assert response.choices[0].message.content is not None
        assert response.usage is not None
        assert response.usage.prompt_tokens > 0
        assert response.usage.completion_tokens > 0


class TestMultipleModels:
    def test_basic_request(self, oai_sdk_config: OpenAISDKTestConfig):
        _skip_cloudflare_full_matrix(oai_sdk_config.provider)
        response = oai_sdk_config.client.chat.completions.create(
            model=oai_sdk_config.model,
            messages=[{"role": "user", "content": "Say 'A'"}],
            max_tokens=300,
        )

        assert response is not None
        assert response.choices[0].message.content is not None

    def test_sequential_requests_same_model(self, oai_sdk_config: OpenAISDKTestConfig):
        _skip_cloudflare_full_matrix(oai_sdk_config.provider)
        response1 = oai_sdk_config.client.chat.completions.create(
            model=oai_sdk_config.model,
            messages=[{"role": "user", "content": "Say '1'"}],
            max_tokens=300,
        )

        response2 = oai_sdk_config.client.chat.completions.create(
            model=oai_sdk_config.model,
            messages=[{"role": "user", "content": "Say '2'"}],
            max_tokens=300,
        )

        assert response1.choices[0].message.content is not None
        assert response2.choices[0].message.content is not None

    def test_streaming_then_non_streaming(self, oai_sdk_config: OpenAISDKTestConfig):
        _skip_cloudflare_full_matrix(oai_sdk_config.provider)
        stream = oai_sdk_config.client.chat.completions.create(
            model=oai_sdk_config.model,
            messages=[{"role": "user", "content": "Say 'stream'"}],
            max_tokens=300,
            stream=True,
        )
        chunks = list(stream)
        assert len(chunks) > 0

        response = oai_sdk_config.client.chat.completions.create(
            model=oai_sdk_config.model,
            messages=[{"role": "user", "content": "Say 'sync'"}],
            max_tokens=300,
        )
        assert response.choices[0].message.content is not None


class TestToolCalling:
    def test_tool_definition_and_response(self, oai_sdk_config: OpenAISDKTestConfig):
        _skip_cloudflare_full_matrix(oai_sdk_config.provider)
        tools: list[ChatCompletionToolParam] = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get the current weather in a location",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {"type": "string", "description": "City name"},
                            "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
                        },
                        "required": ["location"],
                    },
                },
            }
        ]

        response = oai_sdk_config.client.chat.completions.create(
            model=oai_sdk_config.model,
            messages=[{"role": "user", "content": "What's the weather in Paris?"}],
            tools=tools,
            tool_choice="auto",
            max_tokens=200,
        )

        assert response is not None
        assert len(response.choices) > 0
        choice = response.choices[0]
        assert choice.message is not None
        if choice.message.tool_calls:
            tool_call = choice.message.tool_calls[0]
            assert hasattr(tool_call, "function")
            assert tool_call.function.name == "get_weather"
            args = json.loads(tool_call.function.arguments)
            assert "location" in args

    def test_tool_choice_required(self, oai_sdk_config: OpenAISDKTestConfig):
        if oai_sdk_config.provider == "cloudflare":
            pytest.skip("Cloudflare Workers AI does not support tool_choice with specific function")

        tools: list[ChatCompletionToolParam] = [
            {
                "type": "function",
                "function": {
                    "name": "calculate",
                    "description": "Perform a calculation",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "expression": {"type": "string"},
                        },
                        "required": ["expression"],
                    },
                },
            }
        ]

        tool_choice: ChatCompletionToolChoiceOptionParam = {"type": "function", "function": {"name": "calculate"}}

        response = oai_sdk_config.client.chat.completions.create(
            model=oai_sdk_config.model,
            messages=[{"role": "user", "content": "What is 2+2?"}],
            tools=tools,
            tool_choice=tool_choice,
            max_tokens=200,
        )

        tool_calls = response.choices[0].message.tool_calls
        assert tool_calls is not None
        tool_call = tool_calls[0]
        assert hasattr(tool_call, "function")
        assert tool_call.function.name == "calculate"


class TestMultiTurnParametrized:
    def test_conversation_history(self, oai_sdk_config: OpenAISDKTestConfig):
        _skip_cloudflare_full_matrix(oai_sdk_config.provider)
        response = oai_sdk_config.client.chat.completions.create(
            model=oai_sdk_config.model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant. Be very brief."},
                {"role": "user", "content": "My name is Alice."},
                {"role": "assistant", "content": "Hello Alice!"},
                {"role": "user", "content": "What is my name?"},
            ],
            max_tokens=300,
        )

        assert response is not None
        content = response.choices[0].message.content
        assert content is not None
        assert "alice" in content.lower()


@skip_without_openai_key
@xfail_provider_unavailable
class TestOpenAIVision:
    def test_image_url_input(self, openai_client: OpenAI):
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What colors do you see in this image? Reply in one word."},
                        {"type": "image_url", "image_url": {"url": TEST_IMAGE_URL}},
                    ],
                }
            ],
            max_tokens=300,
        )

        assert response is not None
        assert response.choices[0].message.content is not None

    def test_image_with_detail_parameter(self, openai_client: OpenAI):
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe this image briefly."},
                        {"type": "image_url", "image_url": {"url": TEST_IMAGE_URL, "detail": "low"}},
                    ],
                }
            ],
            max_tokens=300,
        )

        assert response is not None
        assert response.choices[0].message.content is not None


@skip_without_openai_key
@xfail_provider_unavailable
class TestOpenAIMultiTurn:
    def test_conversation_history(self, openai_client: OpenAI):
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful assistant. Be very brief."},
                {"role": "user", "content": "My name is Alice."},
                {"role": "assistant", "content": "Hello Alice!"},
                {"role": "user", "content": "What is my name?"},
            ],
            max_tokens=20,
        )

        assert response is not None
        content = response.choices[0].message.content
        assert content is not None
        assert "alice" in content.lower()


@skip_without_openai_key
@xfail_provider_unavailable
class TestOpenAIJSONMode:
    def test_json_response_format(self, openai_client: OpenAI):
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You output JSON only. Output a JSON object with a 'greeting' field.",
                },
                {"role": "user", "content": "Say hello"},
            ],
            response_format={"type": "json_object"},
            max_tokens=300,
        )

        assert response is not None
        content = response.choices[0].message.content
        assert content is not None
        parsed = json.loads(content)
        assert "greeting" in parsed


@skip_without_openai_key
@xfail_provider_unavailable
class TestOpenAIValidationErrors:
    @pytest.mark.parametrize(
        "invalid_param,value,expected_error",
        [
            pytest.param("temperature", 5.0, "temperature", id="temperature_out_of_range"),
            pytest.param("presence_penalty", -3.0, "presence_penalty", id="presence_penalty_out_of_range"),
            pytest.param("frequency_penalty", 5.0, "frequency_penalty", id="frequency_penalty_out_of_range"),
        ],
    )
    def test_invalid_parameters_rejected(
        self, openai_client: OpenAI, invalid_param: str, value: float, expected_error: str
    ):
        kwargs: dict[str, Any] = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 10,
            invalid_param: value,
        }
        with pytest.raises(BadRequestError) as exc_info:
            openai_client.chat.completions.create(**kwargs)
        assert expected_error in str(exc_info.value).lower()

    def test_empty_messages_rejected(self, openai_client: OpenAI):
        with pytest.raises(BadRequestError) as exc_info:
            openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[],
                max_tokens=10,
            )
        assert "messages" in str(exc_info.value).lower()
