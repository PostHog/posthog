import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

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
        assert call_kwargs["model"] == "claude-sonnet-4-6"
        assert "provider" not in call_kwargs
        assert "use_bedrock_fallback" not in call_kwargs

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
        assert "Expected one of: anthropic, bedrock" in response.json()["error"]["message"]

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
        assert "Expected one of: anthropic, bedrock" in response.json()["error"]["message"]

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
