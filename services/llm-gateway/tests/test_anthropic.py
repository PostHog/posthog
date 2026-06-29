import asyncio
import os
from collections.abc import AsyncIterator
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from llm_gateway.api.anthropic import _is_anthropic_billing_block
from llm_gateway.api.handler import ProviderError
from llm_gateway.request_context import (
    extract_posthog_flags_from_headers,
    extract_posthog_properties_from_headers,
    extract_posthog_provider_from_headers,
    extract_posthog_use_bedrock_fallback_from_headers,
)

DANGEROUS_PARAMS: list[tuple[str, str]] = [
    ("api_key", "sk-stolen-key"),
    ("api_base", "https://attacker.example.com"),
    ("base_url", "https://attacker.example.com"),
    ("api_version", "2024-10-01"),
    ("organization", "org-attacker"),
]


class TestExtractPosthogFlagsFromHeaders:
    def test_extracts_x_posthog_flag_headers(self) -> None:
        request = MagicMock()
        request.headers = MagicMock()
        request.headers.items.return_value = [
            ("X-POSTHOG-FLAG-EXPERIMENT-FEATURE-FLAG-KEY", "variant-name"),
            ("X-POSTHOG-FLAG-ANOTHER-FLAG", "control"),
            ("Content-Type", "application/json"),
        ]
        result = extract_posthog_flags_from_headers(request)
        assert result == {
            "experiment-feature-flag-key": "variant-name",
            "another-flag": "control",
        }

    def test_extract_case_insensitive(self) -> None:
        request = MagicMock()
        request.headers = MagicMock()
        request.headers.items.return_value = [
            ("x-posthog-flag-my-flag", "value"),
        ]
        result = extract_posthog_flags_from_headers(request)
        assert result == {"my-flag": "value"}

    def test_extract_ignores_non_matching_headers(self) -> None:
        request = MagicMock()
        request.headers = MagicMock()
        request.headers.items.return_value = [
            ("X-POSTHOG-PROPERTY-FOO", "prop"),
            ("Authorization", "Bearer x"),
        ]
        result = extract_posthog_flags_from_headers(request)
        assert result == {}


class TestExtractPosthogPropertiesFromHeaders:
    def test_extracts_x_posthog_property_headers(self) -> None:
        request = MagicMock()
        request.headers = MagicMock()
        request.headers.items.return_value = [
            ("X-POSTHOG-PROPERTY-VARIANT", "memes"),
            ("X-POSTHOG-PROPERTY-FOO", "bar"),
            ("Content-Type", "application/json"),
        ]
        result = extract_posthog_properties_from_headers(request)
        assert result == {"variant": "memes", "foo": "bar"}

    def test_extract_case_insensitive(self) -> None:
        request = MagicMock()
        request.headers = MagicMock()
        request.headers.items.return_value = [
            ("x-posthog-property-key", "value"),
        ]
        result = extract_posthog_properties_from_headers(request)
        assert result == {"key": "value"}

    def test_extract_ignores_non_matching_headers(self) -> None:
        request = MagicMock()
        request.headers = MagicMock()
        request.headers.items.return_value = [
            ("X-Other-Header", "other"),
            ("Authorization", "Bearer x"),
        ]
        result = extract_posthog_properties_from_headers(request)
        assert result == {}


class TestExtractPosthogProviderFromHeaders:
    def test_extracts_provider_header(self) -> None:
        request = MagicMock()
        request.headers = Headers({"X-PostHog-Provider": "bedrock"})

        assert extract_posthog_provider_from_headers(request) == "bedrock"

    def test_extracts_provider_header_case_insensitive(self) -> None:
        request = MagicMock()
        request.headers = Headers({"x-posthog-provider": "ANTHROPIC"})

        assert extract_posthog_provider_from_headers(request) == "anthropic"

    def test_invalid_provider_header_raises(self) -> None:
        request = MagicMock()
        request.headers = Headers({"X-PostHog-Provider": "vertex"})

        with pytest.raises(ValueError, match="Expected one of: anthropic, bedrock"):
            extract_posthog_provider_from_headers(request)


class TestExtractPosthogUseBedrockFallbackFromHeaders:
    def test_extracts_true_fallback_header(self) -> None:
        request = MagicMock()
        request.headers = Headers({"X-PostHog-Use-Bedrock-Fallback": "true"})

        assert extract_posthog_use_bedrock_fallback_from_headers(request) is True

    def test_extracts_false_fallback_header(self) -> None:
        request = MagicMock()
        request.headers = Headers({"X-PostHog-Use-Bedrock-Fallback": "FALSE"})

        assert extract_posthog_use_bedrock_fallback_from_headers(request) is False

    def test_invalid_fallback_header_raises(self) -> None:
        request = MagicMock()
        request.headers = Headers({"X-PostHog-Use-Bedrock-Fallback": "1"})

        with pytest.raises(ValueError, match="Expected: true or false"):
            extract_posthog_use_bedrock_fallback_from_headers(request)


class TestAnthropicMessagesEndpoint:
    @pytest.fixture
    def valid_request_body(self) -> dict[str, Any]:
        return {
            "model": "claude-3-5-sonnet-20241022",
            "messages": [{"role": "user", "content": "Hello"}],
        }

    @pytest.fixture(
        params=[
            pytest.param("anthropic", id="anthropic"),
            pytest.param("bedrock", id="bedrock"),
        ]
    )
    def provider(self, request):
        if request.param == "bedrock":
            with patch(
                "llm_gateway.api.anthropic.get_settings",
                return_value=MagicMock(bedrock_region_name="us-east-1", request_timeout=300.0),
            ):
                yield request.param
        else:
            yield request.param

    @pytest.fixture
    def provider_request_body(self) -> dict[str, Any]:
        return {
            "model": "claude-sonnet-4-6",
            "messages": [{"role": "user", "content": "Hello"}],
        }

    @pytest.fixture
    def provider_request_headers(self, provider) -> dict[str, str]:
        headers = {"Authorization": "Bearer phx_test_key"}
        if provider == "bedrock":
            headers["X-PostHog-Provider"] = "bedrock"
        return headers

    @pytest.fixture
    def provider_mock_response(self) -> dict[str, Any]:
        return {
            "id": "msg_123",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "Hello!"}],
            "model": "claude-sonnet-4-6",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

    def test_unauthenticated_request_returns_401(self, client: TestClient, valid_request_body: dict) -> None:
        response = client.post("/v1/messages", json=valid_request_body)
        assert response.status_code == 401

    @pytest.mark.parametrize(
        "invalid_body,expected_field",
        [
            pytest.param({}, "model", id="missing_model"),
            pytest.param({"model": "claude-3"}, "messages", id="missing_messages"),
        ],
    )
    def test_validation_errors(
        self,
        authenticated_client: TestClient,
        invalid_body: dict,
        expected_field: str,
    ) -> None:
        response = authenticated_client.post(
            "/v1/messages",
            json=invalid_body,
            headers={"Authorization": "Bearer phx_test_key"},
        )
        assert response.status_code == 422
        assert expected_field in str(response.json())

    @patch("llm_gateway.api.anthropic.litellm.anthropic_messages")
    def test_successful_request(
        self,
        mock_anthropic: MagicMock,
        authenticated_client: TestClient,
        provider_request_body: dict,
        provider_request_headers: dict[str, str],
        provider_mock_response: dict,
    ) -> None:
        mock_response = MagicMock()
        mock_response.model_dump = MagicMock(return_value=provider_mock_response)
        mock_anthropic.return_value = mock_response

        response = authenticated_client.post(
            "/v1/messages",
            json=provider_request_body,
            headers=provider_request_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "msg_123"
        assert data["role"] == "assistant"
        assert data["usage"]["input_tokens"] == 10

    @patch("llm_gateway.api.anthropic.litellm.anthropic_messages")
    def test_bare_claude_model_is_prefixed_for_litellm_routing(
        self,
        mock_anthropic: MagicMock,
        authenticated_client: TestClient,
        provider_mock_response: dict,
    ) -> None:
        mock_response = MagicMock()
        mock_response.model_dump = MagicMock(return_value=provider_mock_response)
        mock_anthropic.return_value = mock_response

        response = authenticated_client.post(
            "/v1/messages",
            json={
                "model": "claude-opus-4-8",
                "messages": [{"role": "user", "content": "Hello"}],
            },
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 200
        assert mock_anthropic.call_args.kwargs["model"] == "anthropic/claude-opus-4-8"

    @pytest.mark.parametrize(
        "error_status,error_message,error_type",
        [
            pytest.param(400, "Invalid request", "invalid_request_error", id="bad_request"),
            pytest.param(429, "Rate limit exceeded", "rate_limit_error", id="rate_limited"),
            pytest.param(500, "Internal error", "internal_error", id="server_error"),
        ],
    )
    @patch("llm_gateway.api.anthropic.litellm.anthropic_messages")
    def test_provider_errors(
        self,
        mock_anthropic: MagicMock,
        authenticated_client: TestClient,
        provider_request_body: dict,
        provider_request_headers: dict[str, str],
        error_status: int,
        error_message: str,
        error_type: str,
    ) -> None:
        error = Exception(error_message)
        error.status_code = error_status  # type: ignore[attr-defined]
        error.message = error_message  # type: ignore[attr-defined]
        error.type = error_type  # type: ignore[attr-defined]
        mock_anthropic.side_effect = error

        response = authenticated_client.post(
            "/v1/messages",
            json=provider_request_body,
            headers=provider_request_headers,
        )

        assert response.status_code == error_status
        data = response.json()
        assert data["error"]["message"] == error_message
        assert data["error"]["type"] == error_type

    @pytest.mark.parametrize(
        "param_name,param_value",
        [pytest.param(name, value, id=name) for name, value in DANGEROUS_PARAMS],
    )
    @patch("llm_gateway.api.anthropic.litellm.anthropic_messages")
    def test_dangerous_params_not_forwarded_to_llm(
        self,
        mock_anthropic: MagicMock,
        authenticated_client: TestClient,
        provider_request_body: dict,
        provider_request_headers: dict[str, str],
        provider_mock_response: dict,
        param_name: str,
        param_value: str,
    ) -> None:
        mock_response = MagicMock()
        mock_response.model_dump = MagicMock(return_value=provider_mock_response)
        mock_anthropic.return_value = mock_response

        body_with_injection = {**provider_request_body, param_name: param_value}
        response = authenticated_client.post(
            "/v1/messages",
            json=body_with_injection,
            headers=provider_request_headers,
        )

        assert response.status_code == 200
        call_kwargs = mock_anthropic.call_args
        assert param_name not in call_kwargs.kwargs, (
            f"Dangerous parameter '{param_name}' was forwarded to litellm.anthropic_messages"
        )

    @patch("llm_gateway.api.anthropic.litellm.anthropic_messages")
    def test_model_list_not_forwarded_to_llm(
        self,
        mock_anthropic: MagicMock,
        authenticated_client: TestClient,
        provider_request_body: dict,
        provider_request_headers: dict[str, str],
        provider_mock_response: dict,
    ) -> None:
        mock_response = MagicMock()
        mock_response.model_dump = MagicMock(return_value=provider_mock_response)
        mock_anthropic.return_value = mock_response

        body_with_model_list = {
            **provider_request_body,
            "model_list": [
                {
                    "model_name": "claude-sonnet-4-6",
                    "litellm_params": {
                        "model": "claude-sonnet-4-6",
                        "api_base": "https://attacker.example.com",
                        "api_key": "sk-stolen-key",
                    },
                }
            ],
        }
        response = authenticated_client.post(
            "/v1/messages",
            json=body_with_model_list,
            headers=provider_request_headers,
        )

        assert response.status_code == 200
        call_kwargs = mock_anthropic.call_args
        assert "model_list" not in call_kwargs.kwargs

    @patch("llm_gateway.api.anthropic.litellm.anthropic_messages")
    def test_nested_dangerous_params_sanitized(
        self,
        mock_anthropic: MagicMock,
        authenticated_client: TestClient,
        provider_request_body: dict,
        provider_request_headers: dict[str, str],
        provider_mock_response: dict,
    ) -> None:
        mock_response = MagicMock()
        mock_response.model_dump = MagicMock(return_value=provider_mock_response)
        mock_anthropic.return_value = mock_response

        body_with_nested_injection = {
            **provider_request_body,
            "metadata": {
                "safe": "value",
                "api_key": "sk-stolen-key",
                "nested": {
                    "keep": "ok",
                    "base_url": "https://attacker.example.com",
                },
            },
        }
        response = authenticated_client.post(
            "/v1/messages",
            json=body_with_nested_injection,
            headers=provider_request_headers,
        )

        assert response.status_code == 200
        call_kwargs = mock_anthropic.call_args
        forwarded_metadata = call_kwargs.kwargs["metadata"]
        assert "api_key" not in forwarded_metadata
        assert "base_url" not in forwarded_metadata["nested"]
        assert forwarded_metadata["safe"] == "value"
        assert forwarded_metadata["nested"]["keep"] == "ok"

    @patch("llm_gateway.api.anthropic.litellm.anthropic_messages")
    def test_product_prefix_route(
        self,
        mock_anthropic: MagicMock,
        authenticated_client: TestClient,
        provider_request_body: dict,
        provider_request_headers: dict[str, str],
        provider_mock_response: dict,
    ) -> None:
        mock_response = MagicMock()
        mock_response.model_dump = MagicMock(return_value=provider_mock_response)
        mock_anthropic.return_value = mock_response

        response = authenticated_client.post(
            "/wizard/v1/messages",
            json=provider_request_body,
            headers=provider_request_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "msg_123"

    @pytest.mark.parametrize(
        "product",
        [
            pytest.param("llm_gateway", id="llm_gateway_product"),
            pytest.param("wizard", id="wizard_product"),
        ],
    )
    @patch("llm_gateway.api.anthropic.litellm.anthropic_messages")
    def test_allowed_product_prefixes(
        self,
        mock_anthropic: MagicMock,
        authenticated_client: TestClient,
        provider_request_body: dict,
        provider_request_headers: dict[str, str],
        provider_mock_response: dict,
        product: str,
    ) -> None:
        mock_response = MagicMock()
        mock_response.model_dump = MagicMock(return_value=provider_mock_response)
        mock_anthropic.return_value = mock_response

        response = authenticated_client.post(
            f"/{product}/v1/messages",
            json=provider_request_body,
            headers=provider_request_headers,
        )

        assert response.status_code == 200

    @pytest.mark.parametrize(
        "product",
        [
            pytest.param("invalid", id="invalid_product"),
            pytest.param("max", id="max_product"),
            pytest.param("claude-code", id="claude_code_product"),
        ],
    )
    def test_invalid_product_returns_400(
        self,
        authenticated_client: TestClient,
        valid_request_body: dict,
        product: str,
    ) -> None:
        response = authenticated_client.post(
            f"/{product}/v1/messages",
            json=valid_request_body,
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 400
        assert "Invalid product" in response.json()["detail"]

    @patch("llm_gateway.api.anthropic.litellm.anthropic_messages")
    def test_gateway_fields_stripped_from_request_data(
        self,
        mock_anthropic: MagicMock,
        authenticated_client: TestClient,
        provider_mock_response: dict,
    ) -> None:
        mock_response = MagicMock()
        mock_response.model_dump = MagicMock(return_value=provider_mock_response)
        mock_anthropic.return_value = mock_response

        response = authenticated_client.post(
            "/v1/messages",
            json={
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "Hello"}],
                "provider": "bedrock",
                "use_bedrock_fallback": True,
            },
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 200
        call_kwargs = mock_anthropic.call_args.kwargs
        assert call_kwargs["model"] == "anthropic/claude-sonnet-4-6"
        assert "provider" not in call_kwargs
        assert "use_bedrock_fallback" not in call_kwargs

    @patch("llm_gateway.api.anthropic.litellm.anthropic_messages")
    def test_cloudflare_provider_routes_to_cloudflare(
        self,
        mock_anthropic: MagicMock,
        authenticated_client: TestClient,
        provider_mock_response: dict,
    ) -> None:
        mock_response = MagicMock()
        mock_response.model_dump = MagicMock(return_value=provider_mock_response)

        with patch(
            "llm_gateway.api.anthropic.make_cloudflare_anthropic_call",
        ) as mock_make_call:
            mock_llm_call = AsyncMock(return_value=mock_response)
            mock_make_call.return_value = mock_llm_call

            with patch(
                "llm_gateway.api.anthropic.ensure_cloudflare_configured",
                return_value=("https://api.cloudflare.com/ai/v1", "test-key"),
            ):
                response = authenticated_client.post(
                    "/v1/messages",
                    json={
                        "model": "@cf/moonshotai/kimi-k2.6",
                        "messages": [{"role": "user", "content": "Hello"}],
                    },
                    headers={
                        "Authorization": "Bearer phx_test_key",
                        "X-PostHog-Provider": "cloudflare",
                    },
                )

            assert response.status_code == 200
            mock_make_call.assert_called_once()
            mock_anthropic.assert_not_called()

    @patch("llm_gateway.api.anthropic.litellm.anthropic_messages")
    def test_cf_model_routes_to_cloudflare_without_provider_header(
        self,
        mock_anthropic: MagicMock,
        authenticated_client: TestClient,
        provider_mock_response: dict,
    ) -> None:
        # Real scout case: the harness derives the provider header from the runtime (claude->anthropic)
        # and never sends "cloudflare", so a claude-runtime scout on GLM arrives as provider="anthropic".
        # Without id-based routing it would hit the real Anthropic API with a @cf/... model and 404.
        # Tools are forwarded — the Anthropic->chat/completions adapter translates them (unlike Responses).
        mock_response = MagicMock()
        mock_response.model_dump = MagicMock(return_value=provider_mock_response)

        with patch("llm_gateway.api.anthropic.make_cloudflare_anthropic_call") as mock_make_call:
            mock_make_call.return_value = AsyncMock(return_value=mock_response)
            with patch(
                "llm_gateway.api.anthropic.ensure_cloudflare_configured",
                return_value=("https://api.cloudflare.com/ai/v1", "test-key"),
            ):
                response = authenticated_client.post(
                    "/v1/messages",
                    json={
                        "model": "@cf/zai-org/glm-5.2",
                        "messages": [{"role": "user", "content": "find issues"}],
                        "tools": [
                            {
                                "name": "emit_signal",
                                "description": "emit a finding",
                                "input_schema": {"type": "object", "properties": {"title": {"type": "string"}}},
                            }
                        ],
                    },
                    # No X-PostHog-Provider header -> defaults to anthropic, as a claude-runtime scout sends.
                    headers={"Authorization": "Bearer phx_test_key"},
                )

        assert response.status_code == 200
        mock_make_call.assert_called_once()
        # Must never reach the real Anthropic path with a `@cf/` model.
        mock_anthropic.assert_not_called()
        forwarded = mock_make_call.return_value.call_args.kwargs
        assert forwarded["model"] == "@cf/zai-org/glm-5.2"
        assert forwarded["tools"][0]["name"] == "emit_signal"

    @patch("llm_gateway.api.anthropic.litellm.anthropic_messages")
    def test_cloudflare_provider_streams_through_cloudflare(
        self,
        mock_anthropic: MagicMock,
        authenticated_client: TestClient,
    ) -> None:
        """Exercises the streaming branch of the Cloudflare Anthropic route end to end:
        the routed llm_call returns an async iterator of Anthropic-shaped events,
        format_sse_stream forwards them, and the gateway emits SSE chunks to the client.
        """

        async def fake_stream():
            yield b'event: message_start\ndata: {"type":"message_start"}\n\n'
            yield b'event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"text":"hi"}}\n\n'
            yield b'event: message_stop\ndata: {"type":"message_stop"}\n\n'

        with patch(
            "llm_gateway.api.anthropic.make_cloudflare_anthropic_call",
        ) as mock_make_call:
            mock_make_call.return_value = AsyncMock(return_value=fake_stream())

            with patch(
                "llm_gateway.api.anthropic.ensure_cloudflare_configured",
                return_value=("https://api.cloudflare.com/ai/v1", "test-key"),
            ):
                with authenticated_client.stream(
                    "POST",
                    "/v1/messages",
                    json={
                        "model": "@cf/moonshotai/kimi-k2.6",
                        "messages": [{"role": "user", "content": "Hello"}],
                        "stream": True,
                    },
                    headers={
                        "Authorization": "Bearer phx_test_key",
                        "X-PostHog-Provider": "cloudflare",
                    },
                ) as response:
                    assert response.status_code == 200
                    body = "".join(response.iter_text())

            assert "message_start" in body
            assert "content_block_delta" in body
            assert "message_stop" in body
            mock_make_call.assert_called_once()
            mock_anthropic.assert_not_called()

    def test_cloudflare_provider_rejects_unpriced_model(
        self,
        authenticated_client: TestClient,
    ) -> None:
        with patch("llm_gateway.api.anthropic.ensure_cloudflare_configured") as mock_ensure_configured:
            with patch("llm_gateway.api.anthropic.make_cloudflare_anthropic_call") as mock_make_call:
                response = authenticated_client.post(
                    "/v1/messages",
                    json={
                        "model": "@cf/meta/llama-3.3-70b-instruct",
                        "messages": [{"role": "user", "content": "Hello"}],
                    },
                    headers={
                        "Authorization": "Bearer phx_test_key",
                        "X-PostHog-Provider": "cloudflare",
                    },
                )

        assert response.status_code == 400
        assert response.json()["error"]["type"] == "invalid_request_error"
        assert "@cf/meta/llama-3.3-70b-instruct" in response.json()["error"]["message"]
        # Rejection must happen before we hand the model off to CF, otherwise the
        # gateway eats the real CF bill while billing the user $0.01 fallback.
        mock_ensure_configured.assert_not_called()
        mock_make_call.assert_not_called()

    def test_invalid_provider_header_returns_400(
        self,
        authenticated_client: TestClient,
        valid_request_body: dict,
    ) -> None:
        response = authenticated_client.post(
            "/v1/messages",
            json=valid_request_body,
            headers={"Authorization": "Bearer phx_test_key", "X-PostHog-Provider": "vertex"},
        )

        assert response.status_code == 400
        assert response.json()["error"]["type"] == "invalid_request_error"
        assert "Expected one of: anthropic, bedrock, cloudflare" in response.json()["error"]["message"]

    def test_invalid_fallback_header_returns_400(
        self,
        authenticated_client: TestClient,
        valid_request_body: dict,
    ) -> None:
        response = authenticated_client.post(
            "/v1/messages",
            json=valid_request_body,
            headers={"Authorization": "Bearer phx_test_key", "X-PostHog-Use-Bedrock-Fallback": "1"},
        )

        assert response.status_code == 400
        assert response.json()["error"]["type"] == "invalid_request_error"
        assert "Expected: true or false" in response.json()["error"]["message"]


class TestStripServerSideTools:
    """Unit tests for strip_server_side_tools helper."""

    CUSTOM_TOOL: dict[str, Any] = {
        "name": "read_data",
        "description": "Reads data",
        "input_schema": {"type": "object", "properties": {}},
    }
    WEB_SEARCH_TOOL: dict[str, Any] = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}
    TEXT_EDITOR_TOOL: dict[str, Any] = {"type": "text_editor_20250124", "name": "text_editor"}

    def _call(self, data: dict[str, Any]) -> None:
        from llm_gateway.api.anthropic import strip_server_side_tools

        strip_server_side_tools(data, model="test-model", product="test")

    def test_strips_server_side_keeps_custom(self) -> None:
        data: dict[str, Any] = {"tools": [self.CUSTOM_TOOL, self.WEB_SEARCH_TOOL]}
        self._call(data)
        assert len(data["tools"]) == 1
        assert data["tools"][0]["name"] == "read_data"

    def test_keeps_explicit_custom_type(self) -> None:
        explicit = {**self.CUSTOM_TOOL, "type": "custom"}
        data: dict[str, Any] = {"tools": [self.CUSTOM_TOOL, explicit]}
        self._call(data)
        assert len(data["tools"]) == 2

    def test_keeps_function_type(self) -> None:
        fn_tool = {**self.CUSTOM_TOOL, "type": "function"}
        data: dict[str, Any] = {"tools": [fn_tool]}
        self._call(data)
        assert len(data["tools"]) == 1

    def test_removes_tools_key_when_all_stripped(self) -> None:
        data: dict[str, Any] = {"tools": [self.WEB_SEARCH_TOOL]}
        self._call(data)
        assert "tools" not in data

    def test_noop_when_no_tools_key(self) -> None:
        data: dict[str, Any] = {"model": "test"}
        self._call(data)
        assert "tools" not in data

    def test_logs_warning_per_stripped_tool(self) -> None:
        from llm_gateway.api.anthropic import strip_server_side_tools

        data: dict[str, Any] = {"tools": [self.CUSTOM_TOOL, self.WEB_SEARCH_TOOL, self.TEXT_EDITOR_TOOL]}
        with patch("llm_gateway.api.anthropic.logger") as mock_logger:
            strip_server_side_tools(data, model="test-model", product="test")

            assert mock_logger.warning.call_count == 2
            warned_tool_names = {call.kwargs["tool_name"] for call in mock_logger.warning.call_args_list}
            assert warned_tool_names == {"web_search", "text_editor"}

    def test_strips_multiple_server_side_tool_types(self) -> None:
        code_exec_tool: dict[str, Any] = {"type": "code_execution_20250522", "name": "code_execution"}
        data: dict[str, Any] = {
            "tools": [self.CUSTOM_TOOL, self.WEB_SEARCH_TOOL, self.TEXT_EDITOR_TOOL, code_exec_tool]
        }
        self._call(data)
        assert len(data["tools"]) == 1
        assert data["tools"][0]["name"] == "read_data"


class TestSanitizeForBedrock:
    """Unit tests for sanitize_for_bedrock — the allowlist boundary for Anthropic->Bedrock requests."""

    def _call(self, data: dict[str, Any]) -> dict[str, Any]:
        from llm_gateway.api.anthropic import sanitize_for_bedrock

        return sanitize_for_bedrock(data, model="test-model", product="test")

    def test_drops_anthropic_only_param(self) -> None:
        data: dict[str, Any] = {
            "model": "bedrock/us.anthropic.claude-sonnet-4-6",
            "messages": [{"role": "user", "content": "hi"}],
            "context_management": {"edits": [{"type": "clear_tool_uses_20250919"}]},
        }
        result = self._call(data)
        assert "context_management" not in result
        assert result["model"] == "bedrock/us.anthropic.claude-sonnet-4-6"
        assert result["messages"] == [{"role": "user", "content": "hi"}]

    @pytest.mark.parametrize(
        "param",
        [
            "model",
            "messages",
            "system",
            "max_tokens",
            "stream",
            "stop_sequences",
            "temperature",
            "top_p",
            "top_k",
            "tools",
            "tool_choice",
            "thinking",
            "metadata",
            "anthropic_version",
            "anthropic_beta",
            "output_format",
            "output_config",
        ],
    )
    def test_keeps_supported_param(self, param: str) -> None:
        # A valid tools list so the nested server-side-tool stripper leaves it intact.
        value: Any = [{"name": "t", "input_schema": {"type": "object", "properties": {}}}]
        data: dict[str, Any] = {"model": "m", param: value}
        assert param in self._call(data)

    @pytest.mark.parametrize(
        "param",
        # Anthropic-only params litellm forwards verbatim but Bedrock rejects, plus an unknown
        # future param (the case that ends the cat-and-mouse: dropped by default).
        [
            "context_management",
            "inference_geo",
            "speed",
            "mcp_servers",
            "container",
            "service_tier",
            "some_future_beta_param",
        ],
    )
    def test_drops_unsupported_param(self, param: str) -> None:
        data: dict[str, Any] = {"model": "m", param: "value"}
        assert param not in self._call(data)

    def test_does_not_mutate_input(self) -> None:
        data: dict[str, Any] = {"model": "m", "context_management": {}}
        self._call(data)
        assert "context_management" in data

    def test_increments_metric_per_dropped_param(self) -> None:
        from llm_gateway.api.anthropic import sanitize_for_bedrock
        from llm_gateway.metrics.prometheus import BEDROCK_PARAM_STRIPPED

        before = BEDROCK_PARAM_STRIPPED.labels(param="context_management", product="test")._value.get()
        sanitize_for_bedrock({"model": "m", "context_management": {}}, model="test-model", product="test")
        after = BEDROCK_PARAM_STRIPPED.labels(param="context_management", product="test")._value.get()
        assert after == before + 1

    def test_logs_warning_per_dropped_param(self) -> None:
        from llm_gateway.api.anthropic import sanitize_for_bedrock

        data: dict[str, Any] = {"model": "m", "context_management": {}, "mcp_servers": []}
        with patch("llm_gateway.api.anthropic.logger") as mock_logger:
            sanitize_for_bedrock(data, model="test-model", product="test")
            warned = {call.kwargs["param"] for call in mock_logger.warning.call_args_list}
        assert {"context_management", "mcp_servers"} <= warned

    def test_still_strips_server_side_tools(self) -> None:
        data: dict[str, Any] = {
            "model": "m",
            "tools": [
                {"name": "read_data", "input_schema": {"type": "object", "properties": {}}},
                {"type": "web_search_20250305", "name": "web_search"},
            ],
        }
        result = self._call(data)
        assert len(result["tools"]) == 1
        assert result["tools"][0]["name"] == "read_data"


class TestAnthropicCountTokensEndpoint:
    @pytest.fixture
    def valid_request_body(self) -> dict[str, Any]:
        return {
            "model": "claude-3-5-sonnet-20241022",
            "messages": [{"role": "user", "content": "Hello"}],
        }

    @pytest.fixture
    def mock_count_tokens_response(self) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={"input_tokens": 14},
        )

    def test_unauthenticated_request_returns_401(self, client: TestClient, valid_request_body: dict) -> None:
        response = client.post("/v1/messages/count_tokens", json=valid_request_body)
        assert response.status_code == 401

    @pytest.mark.parametrize(
        "invalid_body,expected_field",
        [
            pytest.param({}, "model", id="missing_model"),
            pytest.param({"model": "claude-3"}, "messages", id="missing_messages"),
        ],
    )
    def test_validation_errors(
        self,
        authenticated_client: TestClient,
        invalid_body: dict,
        expected_field: str,
    ) -> None:
        response = authenticated_client.post(
            "/v1/messages/count_tokens",
            json=invalid_body,
            headers={"Authorization": "Bearer phx_test_key"},
        )
        assert response.status_code == 422
        assert expected_field in str(response.json())

    @patch("llm_gateway.api.anthropic.get_settings")
    @patch("llm_gateway.api.anthropic.httpx.AsyncClient")
    def test_successful_request(
        self,
        mock_httpx_client_cls: MagicMock,
        mock_get_settings: MagicMock,
        authenticated_client: TestClient,
        valid_request_body: dict,
        mock_count_tokens_response: httpx.Response,
    ) -> None:
        mock_settings = MagicMock()
        mock_settings.anthropic_api_key = "test-anthropic-key"
        mock_settings.request_timeout = 300.0
        mock_get_settings.return_value = mock_settings

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_count_tokens_response)
        mock_httpx_client_cls.return_value = mock_client

        response = authenticated_client.post(
            "/v1/messages/count_tokens",
            json=valid_request_body,
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["input_tokens"] == 14

        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs[0][0] == "https://api.anthropic.com/v1/messages/count_tokens"
        assert call_kwargs[1]["headers"]["x-api-key"] == "test-anthropic-key"

    @patch("llm_gateway.api.anthropic.get_settings")
    @patch("llm_gateway.api.anthropic.httpx.AsyncClient")
    def test_extra_fields_not_forwarded(
        self,
        mock_httpx_client_cls: MagicMock,
        mock_get_settings: MagicMock,
        authenticated_client: TestClient,
        mock_count_tokens_response: httpx.Response,
    ) -> None:
        mock_settings = MagicMock()
        mock_settings.anthropic_api_key = "test-anthropic-key"
        mock_settings.request_timeout = 300.0
        mock_get_settings.return_value = mock_settings

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_count_tokens_response)
        mock_httpx_client_cls.return_value = mock_client

        body_with_extras = {
            "model": "claude-3-5-sonnet-20241022",
            "messages": [{"role": "user", "content": "Hello"}],
            "api_key": "sk-stolen-key",
            "base_url": "https://attacker.example.com",
            "model_list": [
                {
                    "model_name": "claude-3-5-sonnet-20241022",
                    "litellm_params": {
                        "model": "claude-3-5-sonnet-20241022",
                        "api_base": "https://attacker.example.com",
                        "api_key": "sk-stolen-key",
                    },
                }
            ],
            "metadata": {
                "safe": "value",
                "api_key": "sk-stolen-key",
                "nested": {
                    "keep": "ok",
                    "base_url": "https://attacker.example.com",
                },
            },
        }

        response = authenticated_client.post(
            "/v1/messages/count_tokens",
            json=body_with_extras,
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 200
        call_kwargs = mock_client.post.call_args
        sent_json = call_kwargs[1]["json"]
        assert "api_key" not in sent_json
        assert "base_url" not in sent_json
        assert "model_list" not in sent_json
        assert "api_key" not in sent_json["metadata"]
        assert "base_url" not in sent_json["metadata"]["nested"]
        assert sent_json["metadata"]["safe"] == "value"
        assert sent_json["metadata"]["nested"]["keep"] == "ok"

    @patch.dict(os.environ, {}, clear=False)
    @patch("llm_gateway.api.anthropic.get_settings")
    def test_missing_api_key_returns_503(
        self,
        mock_get_settings: MagicMock,
        authenticated_client: TestClient,
        valid_request_body: dict,
    ) -> None:
        os.environ.pop("ANTHROPIC_API_KEY", None)
        mock_settings = MagicMock()
        mock_settings.anthropic_api_key = None
        mock_get_settings.return_value = mock_settings

        response = authenticated_client.post(
            "/v1/messages/count_tokens",
            json=valid_request_body,
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 503
        assert "not configured" in response.json()["error"]["message"]

    @pytest.mark.parametrize(
        "error_status,error_body",
        [
            pytest.param(
                400,
                {"error": {"message": "Invalid model", "type": "invalid_request_error"}},
                id="bad_request",
            ),
            pytest.param(
                429,
                {"error": {"message": "Rate limit exceeded", "type": "rate_limit_error"}},
                id="rate_limited",
            ),
        ],
    )
    @patch("llm_gateway.api.anthropic.get_settings")
    @patch("llm_gateway.api.anthropic.httpx.AsyncClient")
    def test_anthropic_errors_forwarded(
        self,
        mock_httpx_client_cls: MagicMock,
        mock_get_settings: MagicMock,
        authenticated_client: TestClient,
        valid_request_body: dict,
        error_status: int,
        error_body: dict,
    ) -> None:
        mock_settings = MagicMock()
        mock_settings.anthropic_api_key = "test-anthropic-key"
        mock_settings.request_timeout = 300.0
        mock_get_settings.return_value = mock_settings

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=httpx.Response(status_code=error_status, json=error_body))
        mock_httpx_client_cls.return_value = mock_client

        response = authenticated_client.post(
            "/v1/messages/count_tokens",
            json=valid_request_body,
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == error_status

    @patch("llm_gateway.api.anthropic.get_settings")
    @patch("llm_gateway.api.anthropic.httpx.AsyncClient")
    def test_product_prefix_route(
        self,
        mock_httpx_client_cls: MagicMock,
        mock_get_settings: MagicMock,
        authenticated_client: TestClient,
        valid_request_body: dict,
        mock_count_tokens_response: httpx.Response,
    ) -> None:
        mock_settings = MagicMock()
        mock_settings.anthropic_api_key = "test-anthropic-key"
        mock_settings.request_timeout = 300.0
        mock_get_settings.return_value = mock_settings

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_count_tokens_response)
        mock_httpx_client_cls.return_value = mock_client

        response = authenticated_client.post(
            "/wizard/v1/messages/count_tokens",
            json=valid_request_body,
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 200
        assert response.json()["input_tokens"] == 14

    @pytest.mark.parametrize(
        "product",
        [
            pytest.param("invalid", id="invalid_product"),
            pytest.param("claude-code", id="claude_code_product"),
        ],
    )
    def test_invalid_product_returns_400(
        self,
        authenticated_client: TestClient,
        valid_request_body: dict,
        product: str,
    ) -> None:
        response = authenticated_client.post(
            f"/{product}/v1/messages/count_tokens",
            json=valid_request_body,
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 400
        assert "Invalid product" in response.json()["detail"]

    @patch("llm_gateway.api.anthropic.get_settings")
    @patch("llm_gateway.api.anthropic.httpx.AsyncClient")
    def test_does_not_trigger_ai_generation_event(
        self,
        mock_httpx_client_cls: MagicMock,
        mock_get_settings: MagicMock,
        authenticated_client: TestClient,
        valid_request_body: dict,
        mock_count_tokens_response: httpx.Response,
    ) -> None:
        mock_settings = MagicMock()
        mock_settings.anthropic_api_key = "test-anthropic-key"
        mock_settings.request_timeout = 300.0
        mock_get_settings.return_value = mock_settings

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_count_tokens_response)
        mock_httpx_client_cls.return_value = mock_client

        with patch("llm_gateway.api.anthropic.litellm.anthropic_messages") as mock_litellm:
            response = authenticated_client.post(
                "/v1/messages/count_tokens",
                json=valid_request_body,
                headers={"Authorization": "Bearer phx_test_key"},
            )

            assert response.status_code == 200
            mock_litellm.assert_not_called()

    @patch("llm_gateway.api.anthropic.get_settings")
    @patch("llm_gateway.api.anthropic.httpx.AsyncClient")
    def test_gateway_fields_stripped_from_count_tokens_data(
        self,
        mock_httpx_client_cls: MagicMock,
        mock_get_settings: MagicMock,
        authenticated_client: TestClient,
        mock_count_tokens_response: httpx.Response,
    ) -> None:
        mock_settings = MagicMock()
        mock_settings.anthropic_api_key = "test-anthropic-key"
        mock_settings.request_timeout = 300.0
        mock_get_settings.return_value = mock_settings

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_count_tokens_response)
        mock_httpx_client_cls.return_value = mock_client

        response = authenticated_client.post(
            "/v1/messages/count_tokens",
            json={
                "model": "claude-3-5-sonnet-20241022",
                "messages": [{"role": "user", "content": "Hello"}],
                "provider": "bedrock",
                "use_bedrock_fallback": True,
            },
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 200
        call_kwargs = mock_client.post.call_args
        sent_json = call_kwargs[1]["json"]
        assert "provider" not in sent_json
        assert "use_bedrock_fallback" not in sent_json

    def test_invalid_provider_header_returns_400(
        self,
        authenticated_client: TestClient,
        valid_request_body: dict,
    ) -> None:
        response = authenticated_client.post(
            "/v1/messages/count_tokens",
            json=valid_request_body,
            headers={"Authorization": "Bearer phx_test_key", "X-PostHog-Provider": "vertex"},
        )

        assert response.status_code == 400
        assert response.json()["error"]["type"] == "invalid_request_error"
        assert "Expected one of: anthropic, bedrock, cloudflare" in response.json()["error"]["message"]

    def test_cloudflare_provider_approximates_count(
        self,
        authenticated_client: TestClient,
    ) -> None:
        response = authenticated_client.post(
            "/v1/messages/count_tokens",
            json={
                "model": "@cf/moonshotai/kimi-k2.6",
                "messages": [{"role": "user", "content": "Hello"}],
            },
            headers={"Authorization": "Bearer phx_test_key", "X-PostHog-Provider": "cloudflare"},
        )

        assert response.status_code == 200
        # Don't lock the exact value — litellm's tokenizer is the source of truth.
        # Just assert it's a positive integer so the Claude Agent SDK gets a usable budget.
        assert isinstance(response.json()["input_tokens"], int)
        assert response.json()["input_tokens"] > 0

    def test_cf_model_approximates_count_without_provider_header(
        self,
        authenticated_client: TestClient,
    ) -> None:
        # The claude-runtime scout calls count_tokens with provider="anthropic"; CF has no
        # count_tokens endpoint, so route a @cf/ model by id and approximate rather than POST a
        # @cf/... id to the real Anthropic count_tokens API (which would 404).
        with patch("llm_gateway.api.anthropic._anthropic_count_tokens_impl") as mock_real_count:
            response = authenticated_client.post(
                "/v1/messages/count_tokens",
                json={
                    "model": "@cf/zai-org/glm-5.2",
                    "messages": [{"role": "user", "content": "Hello"}],
                },
                # No X-PostHog-Provider header -> defaults to anthropic, as a claude-runtime scout sends.
                headers={"Authorization": "Bearer phx_test_key"},
            )

        assert response.status_code == 200
        assert isinstance(response.json()["input_tokens"], int)
        assert response.json()["input_tokens"] > 0
        mock_real_count.assert_not_called()

    def test_cloudflare_provider_rejects_unpriced_model(
        self,
        authenticated_client: TestClient,
    ) -> None:
        response = authenticated_client.post(
            "/v1/messages/count_tokens",
            json={
                "model": "@cf/meta/llama-3.3-70b-instruct",
                "messages": [{"role": "user", "content": "Hello"}],
            },
            headers={"Authorization": "Bearer phx_test_key", "X-PostHog-Provider": "cloudflare"},
        )

        assert response.status_code == 400
        assert response.json()["error"]["type"] == "invalid_request_error"
        assert "@cf/meta/llama-3.3-70b-instruct" in response.json()["error"]["message"]

    def test_invalid_fallback_header_returns_400(
        self,
        authenticated_client: TestClient,
        valid_request_body: dict,
    ) -> None:
        response = authenticated_client.post(
            "/v1/messages/count_tokens",
            json=valid_request_body,
            headers={"Authorization": "Bearer phx_test_key", "X-PostHog-Use-Bedrock-Fallback": "1"},
        )

        assert response.status_code == 400
        assert response.json()["error"]["type"] == "invalid_request_error"
        assert "Expected: true or false" in response.json()["error"]["message"]


class TestAnthropicCircuitBreakerIntegration:
    """End-to-end behavior of the Anthropic->Bedrock circuit breaker in /v1/messages."""

    @pytest.fixture
    def request_body(self) -> dict[str, Any]:
        return {"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "Hi"}]}

    @pytest.fixture
    def mock_response_dict(self) -> dict[str, Any]:
        return {
            "id": "msg_123",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "Hi!"}],
            "model": "claude-sonnet-4-6",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

    @pytest.fixture
    def install_breaker(self, authenticated_client: TestClient):
        from llm_gateway.circuit_breaker import BreakerDecision

        def _install(*, bypass: bool) -> MagicMock:
            breaker = MagicMock()
            breaker.evaluate = AsyncMock(
                return_value=BreakerDecision(
                    bypass=bypass,
                    open=bypass,
                    failure_rate=0.5 if bypass else 0.0,
                    total_requests=30,
                )
            )
            breaker.record_outcome = AsyncMock()
            authenticated_client.app.state.anthropic_circuit_breaker = breaker
            return breaker

        return _install

    @patch("llm_gateway.api.anthropic.litellm.anthropic_messages")
    def test_open_breaker_with_fallback_routes_to_bedrock(
        self,
        mock_anthropic: MagicMock,
        authenticated_client: TestClient,
        install_breaker,
        request_body: dict,
        mock_response_dict: dict,
    ) -> None:
        breaker = install_breaker(bypass=True)
        mock_response = MagicMock()
        mock_response.model_dump = MagicMock(return_value=mock_response_dict)
        mock_anthropic.return_value = mock_response

        with patch(
            "llm_gateway.api.anthropic.get_settings",
            return_value=MagicMock(bedrock_region_name="us-east-1", request_timeout=300.0),
        ):
            response = authenticated_client.post(
                "/v1/messages",
                json=request_body,
                headers={
                    "Authorization": "Bearer phx_test_key",
                    "X-PostHog-Use-Bedrock-Fallback": "true",
                },
            )

        assert response.status_code == 200
        assert mock_anthropic.call_count == 1
        forwarded_model = mock_anthropic.call_args.kwargs["model"]
        # The model is prefixed with 'bedrock/' for litellm routing
        assert forwarded_model.startswith("bedrock/")
        bedrock_model = forwarded_model.removeprefix("bedrock/")
        assert bedrock_model.startswith(("us.anthropic.", "eu.anthropic.", "anthropic."))
        breaker.record_outcome.assert_not_called()

    @patch("llm_gateway.api.anthropic.litellm.anthropic_messages")
    def test_open_breaker_without_fallback_still_uses_anthropic(
        self,
        mock_anthropic: MagicMock,
        authenticated_client: TestClient,
        install_breaker,
        request_body: dict,
        mock_response_dict: dict,
    ) -> None:
        breaker = install_breaker(bypass=True)
        mock_response = MagicMock()
        mock_response.model_dump = MagicMock(return_value=mock_response_dict)
        mock_anthropic.return_value = mock_response

        response = authenticated_client.post(
            "/v1/messages",
            json=request_body,
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 200
        forwarded_model = mock_anthropic.call_args.kwargs["model"]
        assert forwarded_model == "anthropic/claude-sonnet-4-6"
        breaker.record_outcome.assert_awaited_with(success=True)
        breaker.evaluate.assert_not_called()

    @patch("llm_gateway.api.anthropic.litellm.anthropic_messages")
    def test_closed_breaker_routes_to_anthropic(
        self,
        mock_anthropic: MagicMock,
        authenticated_client: TestClient,
        install_breaker,
        request_body: dict,
        mock_response_dict: dict,
    ) -> None:
        breaker = install_breaker(bypass=False)
        mock_response = MagicMock()
        mock_response.model_dump = MagicMock(return_value=mock_response_dict)
        mock_anthropic.return_value = mock_response

        response = authenticated_client.post(
            "/v1/messages",
            json=request_body,
            headers={
                "Authorization": "Bearer phx_test_key",
                "X-PostHog-Use-Bedrock-Fallback": "true",
            },
        )

        assert response.status_code == 200
        forwarded_model = mock_anthropic.call_args.kwargs["model"]
        assert forwarded_model == "anthropic/claude-sonnet-4-6"
        breaker.record_outcome.assert_awaited_with(success=True)

    @patch("llm_gateway.api.anthropic.litellm.anthropic_messages")
    def test_anthropic_5xx_records_failure(
        self,
        mock_anthropic: MagicMock,
        authenticated_client: TestClient,
        install_breaker,
        request_body: dict,
    ) -> None:
        breaker = install_breaker(bypass=False)
        error = Exception("Internal error")
        error.status_code = 503  # type: ignore[attr-defined]
        error.message = "Internal error"  # type: ignore[attr-defined]
        error.type = "internal_error"  # type: ignore[attr-defined]
        mock_anthropic.side_effect = error

        response = authenticated_client.post(
            "/v1/messages",
            json=request_body,
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 503
        breaker.record_outcome.assert_awaited_with(success=False)

    @patch("llm_gateway.api.anthropic.litellm.anthropic_messages")
    def test_anthropic_4xx_recorded_as_success(
        self,
        mock_anthropic: MagicMock,
        authenticated_client: TestClient,
        install_breaker,
        request_body: dict,
    ) -> None:
        breaker = install_breaker(bypass=False)
        error = Exception("bad request")
        error.status_code = 400  # type: ignore[attr-defined]
        error.message = "bad request"  # type: ignore[attr-defined]
        error.type = "invalid_request_error"  # type: ignore[attr-defined]
        mock_anthropic.side_effect = error

        response = authenticated_client.post(
            "/v1/messages",
            json=request_body,
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 400
        breaker.record_outcome.assert_awaited_with(success=True)

    @patch("llm_gateway.api.anthropic.litellm.anthropic_messages")
    def test_anthropic_429_recorded_as_failure(
        self,
        mock_anthropic: MagicMock,
        authenticated_client: TestClient,
        install_breaker,
        request_body: dict,
    ) -> None:
        breaker = install_breaker(bypass=False)
        error = Exception("rate limited")
        error.status_code = 429  # type: ignore[attr-defined]
        error.message = "rate limited"  # type: ignore[attr-defined]
        error.type = "rate_limit_error"  # type: ignore[attr-defined]
        mock_anthropic.side_effect = error

        response = authenticated_client.post(
            "/v1/messages",
            json=request_body,
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 429
        breaker.record_outcome.assert_awaited_with(success=False)

    @patch("llm_gateway.api.anthropic.litellm.anthropic_messages")
    def test_anthropic_429_with_fallback_routes_to_bedrock(
        self,
        mock_anthropic: MagicMock,
        authenticated_client: TestClient,
        install_breaker,
        mock_response_dict: dict,
    ) -> None:
        request_body = {"model": "claude-opus-4-8", "messages": [{"role": "user", "content": "Hi"}]}
        breaker = install_breaker(bypass=False)
        error = Exception("rate limited")
        error.status_code = 429  # type: ignore[attr-defined]
        error.message = "rate limited"  # type: ignore[attr-defined]
        error.type = "rate_limit_error"  # type: ignore[attr-defined]

        bedrock_response = MagicMock()
        bedrock_response.model_dump = MagicMock(return_value=mock_response_dict)
        mock_anthropic.side_effect = [error, bedrock_response]

        with patch(
            "llm_gateway.api.anthropic.get_settings",
            return_value=MagicMock(bedrock_region_name="us-east-1", request_timeout=300.0),
        ):
            response = authenticated_client.post(
                "/v1/messages",
                json=request_body,
                headers={
                    "Authorization": "Bearer phx_test_key",
                    "X-PostHog-Use-Bedrock-Fallback": "true",
                },
            )

        assert response.status_code == 200
        breaker.record_outcome.assert_awaited_with(success=False)
        assert mock_anthropic.call_count == 2
        assert mock_anthropic.call_args_list[0].kwargs["model"] == "anthropic/claude-opus-4-8"
        assert mock_anthropic.call_args_list[1].kwargs["model"] == "bedrock/us.anthropic.claude-opus-4-8"

    @patch("llm_gateway.api.anthropic.litellm.anthropic_messages")
    def test_anthropic_only_param_stripped_before_bedrock_fallback(
        self,
        mock_anthropic: MagicMock,
        authenticated_client: TestClient,
        install_breaker,
        mock_response_dict: dict,
    ) -> None:
        """Regression: an Anthropic-only beta param (context_management) used to 400 every Bedrock
        fallback. The allowlist must drop it on the Bedrock leg while keeping it on the Anthropic leg.
        """
        request_body = {
            "model": "claude-opus-4-8",
            "messages": [{"role": "user", "content": "Hi"}],
            "context_management": {"edits": [{"type": "clear_tool_uses_20250919"}]},
        }
        install_breaker(bypass=False)
        error = Exception("internal error")
        error.status_code = 500  # type: ignore[attr-defined]
        error.message = "internal error"  # type: ignore[attr-defined]
        error.type = "internal_error"  # type: ignore[attr-defined]

        bedrock_response = MagicMock()
        bedrock_response.model_dump = MagicMock(return_value=mock_response_dict)
        mock_anthropic.side_effect = [error, bedrock_response]

        with patch(
            "llm_gateway.api.anthropic.get_settings",
            return_value=MagicMock(bedrock_region_name="us-east-1", request_timeout=300.0),
        ):
            response = authenticated_client.post(
                "/v1/messages",
                json=request_body,
                headers={
                    "Authorization": "Bearer phx_test_key",
                    "X-PostHog-Use-Bedrock-Fallback": "true",
                },
            )

        assert response.status_code == 200
        assert mock_anthropic.call_count == 2
        anthropic_kwargs = mock_anthropic.call_args_list[0].kwargs
        bedrock_kwargs = mock_anthropic.call_args_list[1].kwargs
        assert "context_management" in anthropic_kwargs
        assert "context_management" not in bedrock_kwargs

    @patch("llm_gateway.api.anthropic.litellm.anthropic_messages")
    def test_anthropic_billing_block_with_fallback_routes_to_bedrock(
        self,
        mock_anthropic: MagicMock,
        authenticated_client: TestClient,
        install_breaker,
        mock_response_dict: dict,
    ) -> None:
        """A workspace usage-limit / out-of-funds block arrives as HTTP 400 invalid_request_error,
        not 5xx/429 — it must still fail over to Bedrock instead of being passed back to the caller."""
        request_body = {"model": "claude-opus-4-8", "messages": [{"role": "user", "content": "Hi"}]}
        breaker = install_breaker(bypass=False)
        error = Exception("billing")
        error.status_code = 400  # type: ignore[attr-defined]
        error.message = '{"type":"error","error":{"type":"invalid_request_error","message":"You have reached your specified workspace API usage limits. You will regain access on 2026-07-01 at 00:00 UTC."}}'  # type: ignore[attr-defined]
        error.type = "invalid_request_error"  # type: ignore[attr-defined]

        bedrock_response = MagicMock()
        bedrock_response.model_dump = MagicMock(return_value=mock_response_dict)
        mock_anthropic.side_effect = [error, bedrock_response]

        with patch(
            "llm_gateway.api.anthropic.get_settings",
            return_value=MagicMock(bedrock_region_name="us-east-1", request_timeout=300.0),
        ):
            response = authenticated_client.post(
                "/v1/messages",
                json=request_body,
                headers={
                    "Authorization": "Bearer phx_test_key",
                    "X-PostHog-Use-Bedrock-Fallback": "true",
                },
            )

        assert response.status_code == 200
        breaker.record_outcome.assert_awaited_with(success=False)
        assert mock_anthropic.call_count == 2
        assert mock_anthropic.call_args_list[1].kwargs["model"] == "bedrock/us.anthropic.claude-opus-4-8"

    @patch("llm_gateway.api.anthropic.litellm.anthropic_messages")
    def test_anthropic_billing_block_recorded_as_failure(
        self,
        mock_anthropic: MagicMock,
        authenticated_client: TestClient,
        install_breaker,
        request_body: dict,
    ) -> None:
        """Even without the fallback header, a billing block is provider-attributable, so the breaker
        must record it as a failure (so it can open) rather than as a caller-side success."""
        breaker = install_breaker(bypass=False)
        error = Exception("billing")
        error.status_code = 400  # type: ignore[attr-defined]
        error.message = "Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits."  # type: ignore[attr-defined]
        error.type = "invalid_request_error"  # type: ignore[attr-defined]
        mock_anthropic.side_effect = error

        response = authenticated_client.post(
            "/v1/messages",
            json=request_body,
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 400
        breaker.record_outcome.assert_awaited_with(success=False)

    @patch("llm_gateway.api.anthropic.litellm.anthropic_messages")
    def test_gateway_validation_400_does_not_poison_breaker(
        self,
        mock_anthropic: MagicMock,
        authenticated_client: TestClient,
        install_breaker,
    ) -> None:
        """A gateway-generated unsupported-model 400 echoes the caller's model name. A crafted name
        containing a billing phrase must NOT be recorded as an Anthropic provider failure — otherwise
        an authenticated caller could open the shared circuit breaker (breaker poisoning)."""
        breaker = install_breaker(bypass=False)
        request_body = {"model": "gemini/credit balance is too low", "messages": [{"role": "user", "content": "Hi"}]}

        response = authenticated_client.post(
            "/v1/messages",
            json=request_body,
            headers={
                "Authorization": "Bearer phx_test_key",
                "X-PostHog-Use-Bedrock-Fallback": "true",
            },
        )

        assert response.status_code == 400
        assert mock_anthropic.call_count == 0  # rejected before any provider call
        breaker.record_outcome.assert_awaited_with(success=True)

    @patch("llm_gateway.api.anthropic.litellm.anthropic_messages")
    def test_generic_400_not_routed_to_bedrock(
        self,
        mock_anthropic: MagicMock,
        authenticated_client: TestClient,
        install_breaker,
    ) -> None:
        """A genuinely malformed request (also HTTP 400 invalid_request_error) must NOT fail over —
        Bedrock would reject it identically, so it stays a caller error and a breaker success."""
        request_body = {"model": "claude-opus-4-8", "messages": [{"role": "user", "content": "Hi"}]}
        breaker = install_breaker(bypass=False)
        error = Exception("bad request")
        error.status_code = 400  # type: ignore[attr-defined]
        error.message = "prompt is too long: 1010381 tokens > 1000000 maximum"  # type: ignore[attr-defined]
        error.type = "invalid_request_error"  # type: ignore[attr-defined]
        mock_anthropic.side_effect = error

        response = authenticated_client.post(
            "/v1/messages",
            json=request_body,
            headers={
                "Authorization": "Bearer phx_test_key",
                "X-PostHog-Use-Bedrock-Fallback": "true",
            },
        )

        assert response.status_code == 400
        assert mock_anthropic.call_count == 1
        breaker.record_outcome.assert_awaited_with(success=True)

    def test_streaming_success_records_after_stream_completes(
        self,
        authenticated_client: TestClient,
        install_breaker,
    ) -> None:
        from fastapi.responses import StreamingResponse

        from llm_gateway.api.anthropic import _wrap_stream_with_breaker

        breaker = install_breaker(bypass=False)

        async def ok_iter() -> AsyncIterator[bytes]:
            yield b'data: {"type":"message_start"}\n\n'
            yield b'data: {"type":"message_stop"}\n\n'

        wrapped = _wrap_stream_with_breaker(StreamingResponse(ok_iter()), breaker)

        async def consume() -> list[bytes]:
            return cast(list[bytes], [chunk async for chunk in wrapped.body_iterator])

        chunks = asyncio.run(consume())
        assert len(chunks) == 2
        breaker.record_outcome.assert_awaited_with(success=True)

    def test_streaming_mid_stream_failure_records_failure(
        self,
        authenticated_client: TestClient,
        install_breaker,
    ) -> None:
        """Direct unit test of the stream wrapper — TestClient surfaces stream errors as
        connection-level failures which makes a true HTTP-level test brittle."""
        from fastapi.responses import StreamingResponse

        from llm_gateway.api.anthropic import _wrap_stream_with_breaker

        breaker = install_breaker(bypass=False)

        async def failing_iter() -> AsyncIterator[bytes]:
            yield b'data: {"type":"message_start"}\n\n'
            raise RuntimeError("upstream dropped")

        wrapped = _wrap_stream_with_breaker(StreamingResponse(failing_iter()), breaker)

        async def consume() -> None:
            try:
                async for _ in wrapped.body_iterator:
                    pass
            except RuntimeError:
                pass

        asyncio.run(consume())
        breaker.record_outcome.assert_awaited_with(success=False)


class TestAnthropicBillingBlockDetection:
    """`_is_anthropic_billing_block` must separate Anthropic's financial blocks (fail over to Bedrock)
    from genuinely malformed requests (don't) — both arrive as HTTP 400 invalid_request_error, so the
    only signal is the upstream message. Fixtures are real messages captured in production. Detection
    is gated on ProviderError so a gateway-local 400 that echoes caller input can't be misread."""

    @pytest.mark.parametrize(
        "case,status_code,message,expected",
        [
            (
                "workspace_usage_limit",
                400,
                '{"type":"error","error":{"type":"invalid_request_error","message":"You have reached your specified workspace API usage limits. You will regain access on 2026-07-01 at 00:00 UTC."}}',
                True,
            ),
            (
                "credit_balance_too_low",
                400,
                "Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits.",
                True,
            ),
            ("prompt_too_long", 400, "prompt is too long: 1010381 tokens > 1000000 maximum", False),
            (
                "image_dimensions",
                400,
                "messages.77.content.7.image.source.base64.data: At least one of the image dimensions exceed max allowed size for many-image requests: 2000 pixels",
                False,
            ),
            (
                "bad_role_order",
                400,
                "messages.2: role 'system' must follow a 'user' message or an 'assistant' message ending in a server tool result",
                False,
            ),
            ("could_not_process_image", 400, "Could not process image", False),
            ("billing_text_but_5xx", 500, "Your credit balance is too low to access the Anthropic API.", False),
        ],
    )
    def test_billing_block_detection(self, case: str, status_code: int, message: str, expected: bool) -> None:
        exc = ProviderError(
            status_code=status_code, detail={"error": {"message": message, "type": "invalid_request_error"}}
        )
        assert _is_anthropic_billing_block(exc) is expected

    def test_non_dict_detail_is_not_billing(self) -> None:
        assert _is_anthropic_billing_block(ProviderError(status_code=400, detail="opaque string")) is False

    def test_gateway_origin_billing_text_is_not_billing(self) -> None:
        """A gateway-local 400 (plain HTTPException, not ProviderError) that echoes a caller model
        name containing a billing phrase must not be treated as a provider billing block — otherwise
        a crafted model name could poison the shared circuit breaker."""
        exc = HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": "Model 'gemini/credit balance is too low' is not supported by this gateway",
                    "type": "invalid_request_error",
                    "code": "model_not_supported",
                }
            },
        )
        assert _is_anthropic_billing_block(exc) is False
