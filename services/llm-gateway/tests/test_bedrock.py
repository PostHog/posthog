from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

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
        assert mock_litellm.call_args.kwargs["model"] == "us.anthropic.claude-sonnet-4-6"


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

    @patch("llm_gateway.api.anthropic.get_settings")
    @patch("llm_gateway.api.anthropic.count_tokens_with_bedrock")
    def test_returns_502_on_boto3_error(
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

        mock_count_tokens.side_effect = Exception("AWS error")

        response = authenticated_client.post(
            "/v1/messages/count_tokens",
            json=valid_request_body,
            headers=valid_request_headers,
        )

        assert response.status_code == 502
        assert "Failed to count tokens via Bedrock" in response.json()["error"]["message"]

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


class TestModelMapping:
    @pytest.mark.parametrize(
        "anthropic_model,expected_bedrock_model",
        [
            pytest.param("claude-opus-4-5", "us.anthropic.claude-opus-4-5-20251101-v1:0", id="opus_4_5"),
            pytest.param("claude-opus-4-6", "us.anthropic.claude-opus-4-6-v1", id="opus_4_6"),
            pytest.param("claude-sonnet-4-5", "us.anthropic.claude-sonnet-4-5-20250929-v1:0", id="sonnet_4_5"),
            pytest.param("claude-sonnet-4-6", "us.anthropic.claude-sonnet-4-6", id="sonnet_4_6"),
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
