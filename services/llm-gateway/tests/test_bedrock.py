import json
from typing import Any
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from fastapi import HTTPException
from fastapi.testclient import TestClient

from llm_gateway.metrics.prometheus import BEDROCK_COUNT_TOKENS_DROPPED_PROPERTIES, BEDROCK_COUNT_TOKENS_ERRORS

BEDROCK_SETTINGS_PATCH = patch(
    "llm_gateway.api.anthropic.get_settings",
    return_value=MagicMock(bedrock_region_name="us-east-1", request_timeout=300.0),
)


class TestBedrockSpecific:
    """Bedrock-specific integration tests for features not covered by the parametrized suite."""

    @pytest.fixture
    def mock_bedrock_response(self) -> dict[str, Any]:
        return {
            "id": "msg_123",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "Hello!"}],
            "model": "us.anthropic.claude-sonnet-4-6",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

    @patch("llm_gateway.api.anthropic.litellm.anthropic_messages")
    @BEDROCK_SETTINGS_PATCH
    def test_anthropic_beta_header_parsed_to_list(
        self,
        mock_get_settings: MagicMock,
        mock_litellm: MagicMock,
        authenticated_client: TestClient,
        mock_bedrock_response: dict,
    ) -> None:
        mock_response = MagicMock()
        mock_response.model_dump = MagicMock(return_value=mock_bedrock_response)
        mock_litellm.return_value = mock_response

        response = authenticated_client.post(
            "/v1/messages",
            json={
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "Hello"}],
            },
            headers={
                "Authorization": "Bearer phx_test_key",
                "X-PostHog-Provider": "bedrock",
                "anthropic-beta": "interleaved-thinking-2025-05-14, extended-thinking-2025-05-14",
            },
        )

        assert response.status_code == 200
        call_kwargs = mock_litellm.call_args.kwargs
        assert call_kwargs["anthropic_beta"] == [
            "interleaved-thinking-2025-05-14",
            "extended-thinking-2025-05-14",
        ]

    @patch("llm_gateway.api.anthropic.litellm.anthropic_messages")
    @BEDROCK_SETTINGS_PATCH
    def test_no_anthropic_beta_when_header_absent(
        self,
        mock_get_settings: MagicMock,
        mock_litellm: MagicMock,
        authenticated_client: TestClient,
        mock_bedrock_response: dict,
    ) -> None:
        mock_response = MagicMock()
        mock_response.model_dump = MagicMock(return_value=mock_bedrock_response)
        mock_litellm.return_value = mock_response

        response = authenticated_client.post(
            "/v1/messages",
            json={
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "Hello"}],
            },
            headers={"Authorization": "Bearer phx_test_key", "X-PostHog-Provider": "bedrock"},
        )

        assert response.status_code == 200
        call_kwargs = mock_litellm.call_args.kwargs
        assert "anthropic_beta" not in call_kwargs

    @patch.dict("os.environ", {"AWS_REGION": "us-east-1"}, clear=False)
    @patch("llm_gateway.api.anthropic.litellm.anthropic_messages")
    @patch("llm_gateway.api.anthropic.get_settings", return_value=MagicMock(bedrock_region_name=None))
    def test_uses_aws_region_when_gateway_region_setting_missing(
        self,
        mock_get_settings: MagicMock,
        mock_litellm: MagicMock,
        authenticated_client: TestClient,
        mock_bedrock_response: dict,
    ) -> None:
        mock_response = MagicMock()
        mock_response.model_dump = MagicMock(return_value=mock_bedrock_response)
        mock_litellm.return_value = mock_response

        response = authenticated_client.post(
            "/v1/messages",
            json={
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "Hello"}],
            },
            headers={"Authorization": "Bearer phx_test_key", "X-PostHog-Provider": "bedrock"},
        )

        assert response.status_code == 200
        assert mock_litellm.call_args.kwargs["model"] == "bedrock/us.anthropic.claude-sonnet-4-6"

    @pytest.mark.parametrize(
        "model,expected_litellm_model",
        [
            pytest.param("claude-sonnet-4-6", "bedrock/us.anthropic.claude-sonnet-4-6", id="anthropic_name_mapped"),
            pytest.param("claude-opus-4-7", "bedrock/us.anthropic.claude-opus-4-7", id="opus_4_7_inference_profile"),
            pytest.param("claude-opus-4-8", "bedrock/us.anthropic.claude-opus-4-8", id="opus_4_8_inference_profile"),
            pytest.param("claude-fable-5", "bedrock/us.anthropic.claude-fable-5", id="fable_5_inference_profile"),
            pytest.param("claude-sonnet-5", "bedrock/us.anthropic.claude-sonnet-5", id="sonnet_5_inference_profile"),
            pytest.param(
                "us.anthropic.claude-sonnet-4-6", "bedrock/us.anthropic.claude-sonnet-4-6", id="already_bedrock_id"
            ),
        ],
    )
    @patch("llm_gateway.api.anthropic.litellm.anthropic_messages")
    @BEDROCK_SETTINGS_PATCH
    def test_bedrock_model_passed_to_litellm_with_bedrock_prefix(
        self,
        mock_get_settings: MagicMock,
        mock_litellm: MagicMock,
        authenticated_client: TestClient,
        mock_bedrock_response: dict,
        model: str,
        expected_litellm_model: str,
    ) -> None:
        # Regression: litellm needs the "bedrock/" prefix to route requests; without
        # it, regional inference profile ids (e.g. "us.anthropic.claude-opus-4-7")
        # don't match litellm's pattern matchers and the request 400s with
        # "LLM Provider NOT provided" before leaving the gateway.
        mock_response = MagicMock()
        mock_response.model_dump = MagicMock(return_value=mock_bedrock_response)
        mock_litellm.return_value = mock_response

        response = authenticated_client.post(
            "/v1/messages",
            json={"model": model, "messages": [{"role": "user", "content": "Hello"}]},
            headers={"Authorization": "Bearer phx_test_key", "X-PostHog-Provider": "bedrock"},
        )

        assert response.status_code == 200
        assert mock_litellm.call_args.kwargs["model"] == expected_litellm_model


class TestBedrockFallback:
    """Tests for the Bedrock fallback behavior on Anthropic requests."""

    @pytest.fixture
    def mock_anthropic_response(self) -> dict[str, Any]:
        return {
            "id": "msg_123",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "Hello!"}],
            "model": "claude-sonnet-4-6",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

    @patch("llm_gateway.api.anthropic.handle_llm_request", new_callable=AsyncMock)
    @BEDROCK_SETTINGS_PATCH
    def test_fallback_triggered_on_5xx(
        self,
        mock_get_settings: MagicMock,
        mock_handle: AsyncMock,
        authenticated_client: TestClient,
        mock_anthropic_response: dict,
    ) -> None:
        # First call (Anthropic) fails with 500, second call (Bedrock) succeeds
        mock_handle.side_effect = [
            HTTPException(
                status_code=500,
                detail={"error": {"message": "Internal error", "type": "internal_error"}},
            ),
            mock_anthropic_response,
        ]

        response = authenticated_client.post(
            "/v1/messages",
            json={
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "Hello"}],
            },
            headers={
                "Authorization": "Bearer phx_test_key",
                "X-PostHog-Use-Bedrock-Fallback": "true",
            },
        )

        assert response.status_code == 200
        assert mock_handle.call_count == 2

        # Verify second call used Bedrock config
        from llm_gateway.api.handler import BEDROCK_CONFIG

        second_call = mock_handle.call_args_list[1].kwargs
        assert second_call["provider_config"] is BEDROCK_CONFIG

    @patch("llm_gateway.api.anthropic.handle_llm_request", new_callable=AsyncMock)
    def test_fallback_not_triggered_on_4xx(
        self,
        mock_handle: AsyncMock,
        authenticated_client: TestClient,
    ) -> None:
        mock_handle.side_effect = HTTPException(
            status_code=400,
            detail={"error": {"message": "Bad request", "type": "invalid_request_error"}},
        )

        response = authenticated_client.post(
            "/v1/messages",
            json={
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "Hello"}],
            },
            headers={
                "Authorization": "Bearer phx_test_key",
                "X-PostHog-Use-Bedrock-Fallback": "true",
            },
        )

        assert response.status_code == 400
        assert mock_handle.call_count == 1

    @patch("llm_gateway.api.anthropic.handle_llm_request", new_callable=AsyncMock)
    def test_no_fallback_when_disabled(
        self,
        mock_handle: AsyncMock,
        authenticated_client: TestClient,
    ) -> None:
        mock_handle.side_effect = HTTPException(
            status_code=500,
            detail={"error": {"message": "Internal error", "type": "internal_error"}},
        )

        response = authenticated_client.post(
            "/v1/messages",
            json={
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "Hello"}],
            },
            headers={
                "Authorization": "Bearer phx_test_key",
                "X-PostHog-Use-Bedrock-Fallback": "false",
            },
        )

        assert response.status_code == 500
        assert mock_handle.call_count == 1

    @patch("llm_gateway.api.anthropic.handle_llm_request", new_callable=AsyncMock)
    @BEDROCK_SETTINGS_PATCH
    def test_fallback_returns_original_error_when_bedrock_also_fails(
        self,
        mock_get_settings: MagicMock,
        mock_handle: AsyncMock,
        authenticated_client: TestClient,
    ) -> None:
        anthropic_error = HTTPException(
            status_code=500,
            detail={"error": {"message": "Anthropic is down", "type": "internal_error"}},
        )
        bedrock_error = HTTPException(
            status_code=503,
            detail={"error": {"message": "Bedrock is down", "type": "service_error"}},
        )
        mock_handle.side_effect = [anthropic_error, bedrock_error]

        response = authenticated_client.post(
            "/v1/messages",
            json={
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "Hello"}],
            },
            headers={
                "Authorization": "Bearer phx_test_key",
                "X-PostHog-Use-Bedrock-Fallback": "true",
            },
        )

        # Should return the original Anthropic error
        assert response.status_code == 500
        assert "Anthropic is down" in response.json()["error"]["message"]

    @patch("llm_gateway.api.anthropic.handle_llm_request", new_callable=AsyncMock)
    @BEDROCK_SETTINGS_PATCH
    def test_fallback_on_504_timeout(
        self,
        mock_get_settings: MagicMock,
        mock_handle: AsyncMock,
        authenticated_client: TestClient,
        mock_anthropic_response: dict,
    ) -> None:
        mock_handle.side_effect = [
            HTTPException(
                status_code=504,
                detail={"error": {"message": "Request timed out", "type": "timeout_error"}},
            ),
            mock_anthropic_response,
        ]

        response = authenticated_client.post(
            "/v1/messages",
            json={
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "Hello"}],
            },
            headers={
                "Authorization": "Bearer phx_test_key",
                "X-PostHog-Use-Bedrock-Fallback": "true",
            },
        )

        assert response.status_code == 200
        assert mock_handle.call_count == 2


class TestBedrockCountTokensViaProvider:
    @pytest.fixture
    def valid_request_body(self) -> dict[str, Any]:
        return {
            "model": "us.anthropic.claude-sonnet-4-6",
            "messages": [{"role": "user", "content": "Hello"}],
        }

    @pytest.fixture
    def valid_request_headers(self) -> dict[str, str]:
        return {
            "Authorization": "Bearer phx_test_key",
            "X-PostHog-Provider": "bedrock",
        }

    @patch("llm_gateway.api.anthropic.get_settings")
    @patch("llm_gateway.api.anthropic.count_tokens_with_bedrock")
    def test_calls_bedrock_count_tokens_api(
        self,
        mock_count_tokens: MagicMock,
        mock_get_settings: MagicMock,
        authenticated_client: TestClient,
        valid_request_body: dict,
        valid_request_headers: dict[str, str],
    ) -> None:
        mock_settings = MagicMock()
        mock_settings.bedrock_region_name = "us-east-1"
        mock_settings.request_timeout = 300.0
        mock_get_settings.return_value = mock_settings

        mock_count_tokens.return_value = 42

        response = authenticated_client.post(
            "/v1/messages/count_tokens",
            json=valid_request_body,
            headers=valid_request_headers,
        )

        assert response.status_code == 200
        assert response.json()["input_tokens"] == 42

    @pytest.mark.parametrize(
        "model,expected_model_id",
        [
            pytest.param("us.anthropic.claude-sonnet-4-6", "us.anthropic.claude-sonnet-4-6", id="already_bedrock"),
            pytest.param("claude-sonnet-4-6", "us.anthropic.claude-sonnet-4-6", id="anthropic_name_mapped"),
        ],
    )
    @patch("llm_gateway.api.anthropic.get_settings")
    @patch("llm_gateway.api.anthropic.count_tokens_with_bedrock")
    def test_maps_model_name_for_bedrock(
        self,
        mock_count_tokens: MagicMock,
        mock_get_settings: MagicMock,
        authenticated_client: TestClient,
        model: str,
        expected_model_id: str,
    ) -> None:
        mock_settings = MagicMock()
        mock_settings.bedrock_region_name = "us-east-1"
        mock_settings.request_timeout = 300.0
        mock_get_settings.return_value = mock_settings

        mock_count_tokens.return_value = 10

        authenticated_client.post(
            "/v1/messages/count_tokens",
            json={"model": model, "messages": [{"role": "user", "content": "Hello"}]},
            headers={"Authorization": "Bearer phx_test_key", "X-PostHog-Provider": "bedrock"},
        )

        call_args = mock_count_tokens.call_args
        assert call_args[0][1] == expected_model_id  # second positional arg is model

    @patch.dict("os.environ", {"AWS_REGION": "", "AWS_DEFAULT_REGION": ""}, clear=False)
    @patch("llm_gateway.api.anthropic.get_settings")
    def test_requires_bedrock_region(
        self,
        mock_get_settings: MagicMock,
        authenticated_client: TestClient,
        valid_request_body: dict,
        valid_request_headers: dict[str, str],
    ) -> None:
        mock_settings = MagicMock()
        mock_settings.bedrock_region_name = None
        mock_get_settings.return_value = mock_settings

        response = authenticated_client.post(
            "/v1/messages/count_tokens",
            json=valid_request_body,
            headers=valid_request_headers,
        )

        assert response.status_code == 503
        assert "Bedrock region not configured" in response.json()["error"]["message"]

    @patch("llm_gateway.api.anthropic.REQUEST_COUNT")
    @patch("llm_gateway.api.anthropic.get_settings")
    @patch("llm_gateway.api.anthropic.count_tokens_with_bedrock_mantle", new_callable=AsyncMock)
    @patch("llm_gateway.api.anthropic.count_tokens_with_bedrock")
    def test_returns_502_when_runtime_and_mantle_both_fail(
        self,
        mock_count_tokens: MagicMock,
        mock_mantle_count_tokens: AsyncMock,
        mock_get_settings: MagicMock,
        mock_request_count: MagicMock,
        authenticated_client: TestClient,
        valid_request_body: dict,
        valid_request_headers: dict[str, str],
    ) -> None:
        mock_settings = MagicMock()
        mock_settings.bedrock_region_name = "us-east-1"
        mock_settings.request_timeout = 300.0
        mock_get_settings.return_value = mock_settings

        mock_count_tokens.side_effect = Exception("AWS error")
        mock_mantle_count_tokens.side_effect = HTTPException(
            status_code=403,
            detail={"error": {"message": "Access denied", "type": "permission_error"}},
        )

        runtime_errors_before = BEDROCK_COUNT_TOKENS_ERRORS.labels(
            transport="runtime",
            error_type="Exception",
            product="llm_gateway",
        )._value.get()
        mantle_errors_before = BEDROCK_COUNT_TOKENS_ERRORS.labels(
            transport="mantle",
            error_type="HTTPException",
            product="llm_gateway",
        )._value.get()

        response = authenticated_client.post(
            "/v1/messages/count_tokens",
            json=valid_request_body,
            headers=valid_request_headers,
        )

        assert response.status_code == 502
        assert "Failed to count tokens via Bedrock" in response.json()["error"]["message"]
        assert mock_request_count.labels.call_args.kwargs["status_code"] == "502"
        assert (
            BEDROCK_COUNT_TOKENS_ERRORS.labels(
                transport="runtime",
                error_type="Exception",
                product="llm_gateway",
            )._value.get()
            == runtime_errors_before + 1
        )
        assert (
            BEDROCK_COUNT_TOKENS_ERRORS.labels(
                transport="mantle",
                error_type="HTTPException",
                product="llm_gateway",
            )._value.get()
            == mantle_errors_before + 1
        )

    @patch("llm_gateway.api.anthropic.get_settings")
    @patch("llm_gateway.api.anthropic.count_tokens_with_bedrock_mantle", new_callable=AsyncMock)
    @patch("llm_gateway.api.anthropic.count_tokens_with_bedrock")
    def test_falls_back_to_mantle_when_runtime_unsupported(
        self,
        mock_count_tokens: MagicMock,
        mock_mantle_count_tokens: AsyncMock,
        mock_get_settings: MagicMock,
        authenticated_client: TestClient,
        valid_request_body: dict,
        valid_request_headers: dict[str, str],
    ) -> None:
        mock_settings = MagicMock()
        mock_settings.bedrock_region_name = "us-east-1"
        mock_settings.request_timeout = 300.0
        mock_get_settings.return_value = mock_settings

        # Mirrors bedrock-runtime rejecting CountTokens for a CRIS-only model like claude-opus-4-8.
        mock_count_tokens.side_effect = ClientError(
            {
                "Error": {
                    "Code": "ValidationException",
                    "Message": "The provided model doesn't support counting tokens.",
                },
                "ResponseMetadata": {
                    "HTTPHeaders": {},
                    "HTTPStatusCode": 400,
                    "HostId": "",
                    "RequestId": "test-request-id",
                    "RetryAttempts": 0,
                },
            },
            "CountTokens",
        )
        mock_mantle_count_tokens.return_value = 77

        runtime_errors_before = BEDROCK_COUNT_TOKENS_ERRORS.labels(
            transport="runtime",
            error_type="ClientError",
            product="llm_gateway",
        )._value.get()

        with patch("llm_gateway.api.anthropic.logger") as mock_logger:
            response = authenticated_client.post(
                "/v1/messages/count_tokens",
                json=valid_request_body,
                headers=valid_request_headers,
            )

        assert response.status_code == 200
        assert response.json()["input_tokens"] == 77
        assert (
            BEDROCK_COUNT_TOKENS_ERRORS.labels(
                transport="runtime",
                error_type="ClientError",
                product="llm_gateway",
            )._value.get()
            == runtime_errors_before + 1
        )
        assert mock_mantle_count_tokens.await_count == 1
        mantle_count_tokens_call = mock_mantle_count_tokens.await_args
        assert mantle_count_tokens_call is not None
        assert mantle_count_tokens_call.kwargs["product"] == "llm_gateway"
        mock_logger.exception.assert_called_once_with(
            "Bedrock CountTokens failed",
            model="us.anthropic.claude-sonnet-4-6",
            product="llm_gateway",
            runtime_status=400,
            runtime_error_type="ClientError",
            runtime_error_message="The provided model doesn't support counting tokens.",
            runtime_error_code="ValidationException",
        )
        mock_logger.info.assert_any_call(
            "Attempting bedrock-mantle count_tokens fallback",
            model="us.anthropic.claude-sonnet-4-6",
            product="llm_gateway",
        )

    @patch("llm_gateway.api.anthropic.get_settings")
    @patch("llm_gateway.api.anthropic.count_tokens_with_bedrock")
    def test_product_route_supported(
        self,
        mock_count_tokens: MagicMock,
        mock_get_settings: MagicMock,
        authenticated_client: TestClient,
        valid_request_body: dict,
        valid_request_headers: dict[str, str],
    ) -> None:
        mock_settings = MagicMock()
        mock_settings.bedrock_region_name = "us-east-1"
        mock_settings.request_timeout = 300.0
        mock_get_settings.return_value = mock_settings

        mock_count_tokens.return_value = 42

        response = authenticated_client.post(
            "/wizard/v1/messages/count_tokens",
            json=valid_request_body,
            headers=valid_request_headers,
        )

        assert response.status_code == 200
        assert response.json()["input_tokens"] == 42

    @patch("llm_gateway.api.anthropic.get_settings")
    @patch("llm_gateway.api.anthropic.count_tokens_with_bedrock")
    def test_forwards_full_request_payload_to_bedrock_count_tokens(
        self,
        mock_count_tokens: MagicMock,
        mock_get_settings: MagicMock,
        authenticated_client: TestClient,
    ) -> None:
        mock_settings = MagicMock()
        mock_settings.bedrock_region_name = "us-east-1"
        mock_settings.request_timeout = 123.0
        mock_get_settings.return_value = mock_settings

        mock_count_tokens.return_value = 42
        body = {
            "model": "claude-sonnet-4-6",
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 2048,
            "system": "Be brief.",
            "tools": [
                {
                    "name": "get_weather",
                    "description": "Get weather by city",
                    "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}},
                }
            ],
            "tool_choice": {"type": "tool", "name": "get_weather"},
        }

        response = authenticated_client.post(
            "/v1/messages/count_tokens",
            json=body,
            headers={"Authorization": "Bearer phx_test_key", "X-PostHog-Provider": "bedrock"},
        )

        assert response.status_code == 200
        request_data = mock_count_tokens.call_args.args[0]
        assert request_data["model"] == "claude-sonnet-4-6"
        assert request_data["messages"] == body["messages"]
        assert request_data["system"] == body["system"]
        assert request_data["tools"] == body["tools"]
        assert request_data["tool_choice"] == body["tool_choice"]
        assert request_data["max_tokens"] == 2048

    @patch("llm_gateway.bedrock.asyncio.to_thread", new_callable=AsyncMock)
    @patch("llm_gateway.api.anthropic.get_settings")
    def test_count_tokens_runs_in_worker_thread(
        self,
        mock_get_settings: MagicMock,
        mock_to_thread: AsyncMock,
        authenticated_client: TestClient,
        valid_request_body: dict,
        valid_request_headers: dict[str, str],
    ) -> None:
        mock_settings = MagicMock()
        mock_settings.bedrock_region_name = "us-east-1"
        mock_settings.request_timeout = 123.0
        mock_get_settings.return_value = mock_settings
        mock_to_thread.return_value = 42

        response = authenticated_client.post(
            "/v1/messages/count_tokens",
            json=valid_request_body,
            headers=valid_request_headers,
        )

        assert response.status_code == 200
        assert mock_to_thread.called
        assert callable(mock_to_thread.call_args.args[0])

    @pytest.mark.asyncio
    @patch("llm_gateway.bedrock.get_bedrock_runtime_client")
    async def test_count_tokens_strips_unsigned_thinking_blocks(self, mock_get_client: MagicMock) -> None:
        from llm_gateway.bedrock import count_tokens_with_bedrock

        mock_client = MagicMock()
        mock_client.count_tokens.return_value = {"inputTokens": 42}
        mock_get_client.return_value = mock_client

        unsigned_thinking = {"type": "thinking", "thinking": "cannot be replayed", "index": 0}
        signed_thinking = {"type": "thinking", "thinking": "can be replayed", "signature": "sig", "index": 0}
        request_data: dict[str, Any] = {
            "max_tokens": 2048,
            "system": "Be brief.",
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": [unsigned_thinking, {"type": "text", "text": "Answer"}]},
                {"role": "assistant", "content": [unsigned_thinking]},
                {"role": "assistant", "content": [signed_thinking, {"type": "text", "text": "Signed answer"}]},
            ],
            "tools": [{"name": "x", "description": "", "input_schema": {"type": "object"}}],
            "tool_choice": {"type": "tool", "name": "x"},
        }
        unsigned_thinking_drops_before = BEDROCK_COUNT_TOKENS_DROPPED_PROPERTIES.labels(
            transport="runtime",
            property="messages.content.thinking_without_signature",
            product="llm_gateway",
        )._value.get()
        empty_message_drops_before = BEDROCK_COUNT_TOKENS_DROPPED_PROPERTIES.labels(
            transport="runtime",
            property="messages.empty_after_sanitization",
            product="llm_gateway",
        )._value.get()
        top_level_system_drops_before = BEDROCK_COUNT_TOKENS_DROPPED_PROPERTIES.labels(
            transport="runtime",
            property="top_level.system",
            product="llm_gateway",
        )._value.get()

        with patch("llm_gateway.bedrock.logger") as mock_logger:
            result = await count_tokens_with_bedrock(
                request_data,
                "us.anthropic.claude-sonnet-4-6",
                "us-east-1",
                123.0,
                product="llm_gateway",
            )

        assert result == 42
        call_kwargs = mock_client.count_tokens.call_args.kwargs
        assert call_kwargs["modelId"] == "anthropic.claude-sonnet-4-6"

        body = json.loads(call_kwargs["input"]["invokeModel"]["body"])
        assert "system" not in body
        assert "tools" not in body
        assert "tool_choice" not in body
        assert body["messages"] == [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": [{"type": "text", "text": "Answer"}]},
            {"role": "assistant", "content": [signed_thinking, {"type": "text", "text": "Signed answer"}]},
        ]
        assert request_data["messages"][1]["content"][0] == unsigned_thinking
        assert (
            BEDROCK_COUNT_TOKENS_DROPPED_PROPERTIES.labels(
                transport="runtime",
                property="messages.content.thinking_without_signature",
                product="llm_gateway",
            )._value.get()
            == unsigned_thinking_drops_before + 2
        )
        assert (
            BEDROCK_COUNT_TOKENS_DROPPED_PROPERTIES.labels(
                transport="runtime",
                property="messages.empty_after_sanitization",
                product="llm_gateway",
            )._value.get()
            == empty_message_drops_before + 1
        )
        assert (
            BEDROCK_COUNT_TOKENS_DROPPED_PROPERTIES.labels(
                transport="runtime",
                property="top_level.system",
                product="llm_gateway",
            )._value.get()
            == top_level_system_drops_before + 1
        )
        mock_logger.warning.assert_called_once_with(
            "Bedrock CountTokens request sanitized",
            model="us.anthropic.claude-sonnet-4-6",
            product="llm_gateway",
            transport="runtime",
            dropped_properties=[
                "messages.content.thinking_without_signature",
                "messages.empty_after_sanitization",
                "top_level.system",
                "top_level.tool_choice",
                "top_level.tools",
            ],
            dropped_property_counts={
                "messages.content.thinking_without_signature": 2,
                "messages.empty_after_sanitization": 1,
                "top_level.system": 1,
                "top_level.tool_choice": 1,
                "top_level.tools": 1,
            },
            dropped_paths=[
                "messages[1].content[0]",
                "messages[2].content[0]",
                "messages[2]",
                "system",
                "tool_choice",
                "tools",
            ],
            dropped_items_total=6,
            dropped_paths_truncated=False,
        )


class TestModelMapping:
    @pytest.mark.parametrize(
        "anthropic_model,expected_bedrock_model",
        [
            pytest.param("claude-opus-4-5", "us.anthropic.claude-opus-4-5-20251101-v1:0", id="opus_4_5"),
            pytest.param("claude-opus-4-6", "us.anthropic.claude-opus-4-6-v1", id="opus_4_6"),
            pytest.param("claude-sonnet-4-5", "us.anthropic.claude-sonnet-4-5-20250929-v1:0", id="sonnet_4_5"),
            pytest.param("claude-sonnet-4-6", "us.anthropic.claude-sonnet-4-6", id="sonnet_4_6"),
            pytest.param("claude-sonnet-5", "us.anthropic.claude-sonnet-5", id="sonnet_5"),
            pytest.param("claude-haiku-4-5", "us.anthropic.claude-haiku-4-5-20251001-v1:0", id="haiku_4_5"),
        ],
    )
    def test_maps_anthropic_to_bedrock(self, anthropic_model: str, expected_bedrock_model: str) -> None:
        from llm_gateway.api.anthropic import map_to_bedrock_model

        assert map_to_bedrock_model(anthropic_model) == expected_bedrock_model

    def test_passes_through_bedrock_model(self) -> None:
        from llm_gateway.api.anthropic import map_to_bedrock_model

        assert map_to_bedrock_model("us.anthropic.claude-sonnet-4-6") == "us.anthropic.claude-sonnet-4-6"

    def test_maps_to_eu_profile_for_eu_regions(self) -> None:
        from llm_gateway.api.anthropic import map_to_bedrock_model

        assert map_to_bedrock_model("claude-opus-4-6", region_name="eu-west-1") == "eu.anthropic.claude-opus-4-6-v1"

    def test_raises_for_unknown_model(self) -> None:
        from llm_gateway.api.anthropic import map_to_bedrock_model

        with pytest.raises(HTTPException) as exc_info:
            map_to_bedrock_model("unknown-model")
        assert exc_info.value.status_code == 400

    def test_standalone_bedrock_routes_removed(self, authenticated_client: TestClient) -> None:
        response = authenticated_client.post(
            "/bedrock/v1/messages",
            json={"model": "us.anthropic.claude-sonnet-4-6", "messages": [{"role": "user", "content": "Hello"}]},
            headers={"Authorization": "Bearer phx_test_key"},
        )
        # "/bedrock/v1/messages" now matches "/{product}/v1/messages" with product="bedrock",
        # which is not a valid product, so returns 400
        assert response.status_code == 400
        assert "Invalid product" in response.json()["detail"]


class TestBedrockMantleCountTokens:
    """Unit tests for the bedrock-mantle count_tokens fallback transport."""

    @patch("llm_gateway.bedrock.SigV4Auth")
    @patch("llm_gateway.bedrock.boto3.Session")
    def test_reuses_cached_session_when_signing_mantle_requests(
        self,
        mock_session_cls: MagicMock,
        mock_sigv4_auth_cls: MagicMock,
    ) -> None:
        from llm_gateway.bedrock import _sign_bedrock_mantle_request, get_bedrock_session

        get_bedrock_session.cache_clear()
        try:
            frozen_credentials = MagicMock()
            credentials = MagicMock()
            credentials.get_frozen_credentials.return_value = frozen_credentials
            session = MagicMock()
            session.get_credentials.return_value = credentials
            mock_session_cls.return_value = session

            def add_auth(request: Any) -> None:
                request.headers["Authorization"] = "signed"

            mock_sigv4_auth = MagicMock()
            mock_sigv4_auth.add_auth.side_effect = add_auth
            mock_sigv4_auth_cls.return_value = mock_sigv4_auth

            first_headers = _sign_bedrock_mantle_request(
                "https://bedrock-mantle.us-east-1.api.aws/anthropic/v1/messages/count_tokens",
                b'{"messages":[]}',
                "us-east-1",
            )
            second_headers = _sign_bedrock_mantle_request(
                "https://bedrock-mantle.us-east-1.api.aws/anthropic/v1/messages/count_tokens",
                b'{"messages":[]}',
                "us-east-1",
            )

            assert first_headers["Authorization"] == "signed"
            assert second_headers["Authorization"] == "signed"
            assert mock_session_cls.call_count == 1
            assert session.get_credentials.call_count == 2
            assert credentials.get_frozen_credentials.call_count == 2
            assert mock_sigv4_auth_cls.call_count == 2
        finally:
            get_bedrock_session.cache_clear()

    @pytest.mark.asyncio
    @patch("llm_gateway.bedrock._sign_bedrock_mantle_request")
    @patch("llm_gateway.bedrock.httpx.AsyncClient")
    async def test_builds_request_for_mantle_endpoint(
        self,
        mock_async_client_cls: MagicMock,
        mock_sign: MagicMock,
    ) -> None:
        import httpx

        from llm_gateway.bedrock import count_tokens_with_bedrock_mantle

        mock_sign.return_value = {"Authorization": "AWS4-HMAC-SHA256 ...", "anthropic-version": "2023-06-01"}
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=httpx.Response(status_code=200, json={"input_tokens": 99}))
        mock_async_client_cls.return_value.__aenter__.return_value = mock_client

        request_data = {
            "messages": [
                {"role": "assistant", "content": [{"type": "thinking", "thinking": "bad"}]},
                {"role": "user", "content": "Hello"},
            ],
            "system": "Be brief.",
            "tools": [{"name": "x", "description": "", "input_schema": {"type": "object"}}],
        }

        with patch("llm_gateway.bedrock.logger") as mock_logger:
            result = await count_tokens_with_bedrock_mantle(
                request_data,
                "us.anthropic.claude-opus-4-8",
                "us-east-1",
                300.0,
                product="llm_gateway",
            )

        assert result == 99
        mock_logger.info.assert_called_once_with(
            "bedrock-mantle count_tokens request succeeded",
            model="us.anthropic.claude-opus-4-8",
            mantle_model="anthropic.claude-opus-4-8",
            product="llm_gateway",
            region_name="us-east-1",
            status_code=200,
            duration_ms=ANY,
        )
        # URL targets the regional mantle endpoint and the native count_tokens path.
        signed_url = mock_sign.call_args.args[0]
        assert signed_url == "https://bedrock-mantle.us-east-1.api.aws/anthropic/v1/messages/count_tokens"
        # The signed payload carries the native Anthropic shape with the prefix-stripped model id.
        signed_body = json.loads(mock_sign.call_args.args[1])
        assert signed_body["model"] == "anthropic.claude-opus-4-8"
        assert signed_body["messages"] == [{"role": "user", "content": "Hello"}]
        assert signed_body["system"] == request_data["system"]
        assert signed_body["tools"] == request_data["tools"]
        # The same signed payload bytes are what gets POSTed.
        assert mock_client.post.call_args.kwargs["content"] == mock_sign.call_args.args[1]
        mock_logger.warning.assert_called_once_with(
            "Bedrock CountTokens request sanitized",
            model="us.anthropic.claude-opus-4-8",
            product="llm_gateway",
            transport="mantle",
            dropped_properties=[
                "messages.content.thinking_without_signature",
                "messages.empty_after_sanitization",
            ],
            dropped_property_counts={
                "messages.content.thinking_without_signature": 1,
                "messages.empty_after_sanitization": 1,
            },
            dropped_paths=["messages[0].content[0]", "messages[0]"],
            dropped_items_total=2,
            dropped_paths_truncated=False,
        )

    @pytest.mark.asyncio
    @patch("llm_gateway.bedrock._sign_bedrock_mantle_request")
    @patch("llm_gateway.bedrock.httpx.AsyncClient")
    async def test_raises_http_exception_on_mantle_error(
        self,
        mock_async_client_cls: MagicMock,
        mock_sign: MagicMock,
    ) -> None:
        import httpx

        from llm_gateway.bedrock import count_tokens_with_bedrock_mantle

        mock_sign.return_value = {"anthropic-version": "2023-06-01"}
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            return_value=httpx.Response(
                status_code=400,
                json={"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}},
            )
        )
        mock_async_client_cls.return_value.__aenter__.return_value = mock_client

        with pytest.raises(HTTPException) as exc_info:
            await count_tokens_with_bedrock_mantle(
                {"messages": [{"role": "user", "content": "Hi"}]},
                "us.anthropic.claude-opus-4-8",
                "us-east-1",
                300.0,
                product="llm_gateway",
            )

        assert exc_info.value.status_code == 400
