from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from llm_gateway.main import RequestLoggingMiddleware
from llm_gateway.request_context import get_posthog_properties
from tests.conftest import create_test_app

DANGEROUS_PARAMS: list[tuple[str, str]] = [
    ("api_key", "sk-stolen-key"),
    ("api_base", "https://attacker.example.com"),
    ("base_url", "https://attacker.example.com"),
    ("api_version", "2024-10-01"),
    ("organization", "org-attacker"),
]


class TestChatCompletionsEndpoint:
    @pytest.fixture
    def valid_request_body(self) -> dict[str, Any]:
        return {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
        }

    @pytest.fixture
    def mock_openai_response(self) -> dict[str, Any]:
        return {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

    def test_unauthenticated_request_returns_401(self, client: TestClient, valid_request_body: dict) -> None:
        response = client.post("/v1/chat/completions", json=valid_request_body)
        assert response.status_code == 401

    @pytest.mark.parametrize(
        "invalid_body,expected_field",
        [
            pytest.param({}, "model", id="missing_model"),
            pytest.param({"model": "gpt-4"}, "messages", id="missing_messages"),
        ],
    )
    def test_validation_errors(
        self,
        authenticated_client: TestClient,
        invalid_body: dict,
        expected_field: str,
    ) -> None:
        response = authenticated_client.post(
            "/v1/chat/completions",
            json=invalid_body,
            headers={"Authorization": "Bearer phx_test_key"},
        )
        assert response.status_code == 422
        assert expected_field in str(response.json())

    @patch("llm_gateway.api.openai.litellm.acompletion")
    def test_successful_request(
        self,
        mock_completion: MagicMock,
        authenticated_client: TestClient,
        valid_request_body: dict,
        mock_openai_response: dict,
    ) -> None:
        mock_response = MagicMock()
        mock_response.model_dump = MagicMock(return_value=mock_openai_response)
        mock_completion.return_value = mock_response

        response = authenticated_client.post(
            "/v1/chat/completions",
            json=valid_request_body,
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "chatcmpl-123"
        assert data["object"] == "chat.completion"
        assert data["usage"]["total_tokens"] == 15

    @patch("llm_gateway.api.openai.litellm.acompletion")
    def test_posthog_property_headers_reach_request_context(
        self,
        mock_completion: MagicMock,
        mock_db_pool: MagicMock,
        valid_request_body: dict,
        mock_openai_response: dict,
    ) -> None:
        # Build a prod-like app: RequestLoggingMiddleware establishes the base RequestContext
        # that apply_posthog_context_from_headers mutates. The shared conftest app omits it.
        app = create_test_app(mock_db_pool)
        app.add_middleware(RequestLoggingMiddleware)
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "id": "key_id",
                "user_id": 1,
                "scopes": ["llm_gateway:read"],
                "current_team_id": 1,
                "distinct_id": "test-distinct-id",
                "is_staff": False,
            }
        )
        mock_db_pool.acquire = AsyncMock(return_value=conn)

        mock_response = MagicMock()
        mock_response.model_dump = MagicMock(return_value=mock_openai_response)
        captured: dict[str, Any] = {}

        def _capture(*args: Any, **kwargs: Any) -> MagicMock:
            captured["properties"] = get_posthog_properties()
            return mock_response

        mock_completion.side_effect = _capture

        with TestClient(app) as client:
            response = client.post(
                "/v1/chat/completions",
                json=valid_request_body,
                headers={
                    "Authorization": "Bearer phx_test_key",
                    "x-posthog-property-team_id": "42",
                    "x-posthog-property-$ai_billable": "false",
                },
            )

        assert response.status_code == 200
        assert captured["properties"] == {"team_id": "42", "$ai_billable": "false"}

    @pytest.mark.parametrize(
        "error_status,error_message,error_type",
        [
            pytest.param(400, "Invalid request", "invalid_request_error", id="bad_request"),
            pytest.param(429, "Rate limit exceeded", "rate_limit_error", id="rate_limited"),
            pytest.param(500, "Internal error", "internal_error", id="server_error"),
            pytest.param(503, "Service unavailable", "service_unavailable", id="service_unavailable"),
        ],
    )
    @patch("llm_gateway.api.openai.litellm.acompletion")
    def test_provider_errors(
        self,
        mock_completion: MagicMock,
        authenticated_client: TestClient,
        valid_request_body: dict,
        error_status: int,
        error_message: str,
        error_type: str,
    ) -> None:
        error = Exception(error_message)
        error.status_code = error_status  # type: ignore[attr-defined]
        error.message = error_message  # type: ignore[attr-defined]
        error.type = error_type  # type: ignore[attr-defined]
        mock_completion.side_effect = error

        response = authenticated_client.post(
            "/v1/chat/completions",
            json=valid_request_body,
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == error_status
        data = response.json()
        assert data["error"]["message"] == error_message
        assert data["error"]["type"] == error_type

    @pytest.mark.parametrize(
        "param_name,param_value",
        [pytest.param(name, value, id=name) for name, value in DANGEROUS_PARAMS],
    )
    @patch("llm_gateway.api.openai.litellm.acompletion")
    def test_dangerous_params_not_forwarded_to_llm(
        self,
        mock_completion: MagicMock,
        authenticated_client: TestClient,
        valid_request_body: dict,
        mock_openai_response: dict,
        param_name: str,
        param_value: str,
    ) -> None:
        mock_response = MagicMock()
        mock_response.model_dump = MagicMock(return_value=mock_openai_response)
        mock_completion.return_value = mock_response

        body_with_injection = {**valid_request_body, param_name: param_value}
        response = authenticated_client.post(
            "/v1/chat/completions",
            json=body_with_injection,
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 200
        call_kwargs = mock_completion.call_args
        assert param_name not in call_kwargs.kwargs, (
            f"Dangerous parameter '{param_name}' was forwarded to litellm.acompletion"
        )

    @patch("llm_gateway.api.openai.litellm.acompletion")
    def test_model_list_not_forwarded_to_llm(
        self,
        mock_completion: MagicMock,
        authenticated_client: TestClient,
        valid_request_body: dict,
        mock_openai_response: dict,
    ) -> None:
        mock_response = MagicMock()
        mock_response.model_dump = MagicMock(return_value=mock_openai_response)
        mock_completion.return_value = mock_response

        body_with_model_list = {
            **valid_request_body,
            "model_list": [
                {
                    "model_name": "gpt-4",
                    "litellm_params": {
                        "model": "gpt-4",
                        "api_base": "https://attacker.example.com",
                        "api_key": "sk-stolen-key",
                    },
                }
            ],
        }
        response = authenticated_client.post(
            "/v1/chat/completions",
            json=body_with_model_list,
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 200
        call_kwargs = mock_completion.call_args
        assert "model_list" not in call_kwargs.kwargs

    @patch("llm_gateway.api.openai.litellm.acompletion")
    def test_nested_dangerous_params_sanitized(
        self,
        mock_completion: MagicMock,
        authenticated_client: TestClient,
        valid_request_body: dict,
        mock_openai_response: dict,
    ) -> None:
        mock_response = MagicMock()
        mock_response.model_dump = MagicMock(return_value=mock_openai_response)
        mock_completion.return_value = mock_response

        body_with_nested_injection = {
            **valid_request_body,
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
            "/v1/chat/completions",
            json=body_with_nested_injection,
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 200
        call_kwargs = mock_completion.call_args
        forwarded_metadata = call_kwargs.kwargs["metadata"]
        assert "api_key" not in forwarded_metadata
        assert "base_url" not in forwarded_metadata["nested"]
        assert forwarded_metadata["safe"] == "value"
        assert forwarded_metadata["nested"]["keep"] == "ok"

    @patch("llm_gateway.api.openai.litellm.acompletion")
    @patch("llm_gateway.api.openai.make_cloudflare_completion_call")
    @patch("llm_gateway.api.openai.ensure_cloudflare_configured")
    def test_cf_model_routes_through_cloudflare(
        self,
        mock_ensure_configured: MagicMock,
        mock_make_call: MagicMock,
        mock_acompletion: MagicMock,
        authenticated_client: TestClient,
        mock_openai_response: dict,
    ) -> None:
        mock_ensure_configured.return_value = ("https://api.cloudflare.com/ai/v1", "test-key")
        mock_response = MagicMock()
        mock_response.model_dump = MagicMock(return_value=mock_openai_response)
        mock_make_call.return_value = AsyncMock(return_value=mock_response)

        response = authenticated_client.post(
            "/v1/chat/completions",
            json={
                "model": "@cf/moonshotai/kimi-k2.6",
                "messages": [{"role": "user", "content": "Hello"}],
            },
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 200
        mock_make_call.assert_called_once_with("https://api.cloudflare.com/ai/v1", "test-key")
        mock_acompletion.assert_not_called()

    @patch("llm_gateway.api.openai.litellm.acompletion")
    @patch("llm_gateway.api.openai.make_cloudflare_completion_call")
    @patch("llm_gateway.api.openai.ensure_cloudflare_configured")
    def test_cf_model_streams_through_cloudflare(
        self,
        mock_ensure_configured: MagicMock,
        mock_make_call: MagicMock,
        mock_acompletion: MagicMock,
        authenticated_client: TestClient,
    ) -> None:
        """Exercises the streaming branch of the Cloudflare OpenAI route end to end:
        the routed llm_call returns an async iterator, format_sse_stream wraps it,
        and the gateway emits SSE chunks back to the client.
        """
        mock_ensure_configured.return_value = ("https://api.cloudflare.com/ai/v1", "test-key")

        async def fake_stream():
            for content in ("hello", "world"):
                chunk = MagicMock()
                chunk.model_dump = MagicMock(return_value={"choices": [{"delta": {"content": content}, "index": 0}]})
                yield chunk

        mock_make_call.return_value = AsyncMock(return_value=fake_stream())

        with authenticated_client.stream(
            "POST",
            "/v1/chat/completions",
            json={
                "model": "@cf/moonshotai/kimi-k2.6",
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": True,
            },
            headers={"Authorization": "Bearer phx_test_key"},
        ) as response:
            assert response.status_code == 200
            body = "".join(response.iter_text())

        assert '"hello"' in body
        assert '"world"' in body
        assert "[DONE]" in body
        mock_make_call.assert_called_once_with("https://api.cloudflare.com/ai/v1", "test-key")
        mock_acompletion.assert_not_called()

    @patch("llm_gateway.api.openai.make_cloudflare_completion_call")
    @patch("llm_gateway.api.openai.ensure_cloudflare_configured")
    def test_unpriced_cf_model_rejected_before_routing(
        self,
        mock_ensure_configured: MagicMock,
        mock_make_call: MagicMock,
        authenticated_client: TestClient,
    ) -> None:
        response = authenticated_client.post(
            "/v1/chat/completions",
            json={
                "model": "@cf/meta/llama-3.3-70b-instruct",
                "messages": [{"role": "user", "content": "Hello"}],
            },
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 400
        assert response.json()["error"]["type"] == "invalid_request_error"
        assert "@cf/meta/llama-3.3-70b-instruct" in response.json()["error"]["message"]
        # Critical: rejection must happen before we hand the model off to CF, otherwise the
        # gateway eats the real CF bill while billing the user $0.01 fallback.
        mock_ensure_configured.assert_not_called()
        mock_make_call.assert_not_called()


# CF-served models (@cf/...) on the Responses endpoint must route through the CF responses adapter,
# not litellm.aresponses (which prefixes openai/ and hits the real OpenAI Responses API ->
# model_not_supported). This is the codex/Responses gap that left every GLM-routed scout run making
# zero generations.
class TestResponsesCloudflareRouting:
    @patch("llm_gateway.api.openai.litellm.aresponses")
    @patch("llm_gateway.api.openai.make_cloudflare_responses_call")
    @patch("llm_gateway.api.openai.ensure_cloudflare_configured")
    def test_cf_model_routes_through_cloudflare(
        self,
        mock_ensure_configured: MagicMock,
        mock_make_call: MagicMock,
        mock_aresponses: MagicMock,
        authenticated_client: TestClient,
    ) -> None:
        mock_ensure_configured.return_value = ("https://api.cloudflare.com/ai/v1", "test-key")
        mock_response = MagicMock()
        mock_response.model_dump = MagicMock(return_value={"id": "resp_1", "output": []})
        mock_make_call.return_value = AsyncMock(return_value=mock_response)

        response = authenticated_client.post(
            "/v1/responses",
            json={
                "model": "@cf/zai-org/glm-5.2",
                "input": "Hello",
            },
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 200
        mock_make_call.assert_called_once_with("https://api.cloudflare.com/ai/v1", "test-key")
        # Native OpenAI Responses path must not be touched for a CF model.
        mock_aresponses.assert_not_called()

    @patch("llm_gateway.api.openai.litellm.aresponses")
    @patch("llm_gateway.api.openai.make_cloudflare_responses_call")
    @patch("llm_gateway.api.openai.ensure_cloudflare_configured")
    def test_cf_model_streams_through_cloudflare(
        self,
        mock_ensure_configured: MagicMock,
        mock_make_call: MagicMock,
        mock_aresponses: MagicMock,
        authenticated_client: TestClient,
    ) -> None:
        # Streaming branch of the CF Responses route: the routed llm_call returns an async iterator,
        # format_sse_stream wraps it, and the gateway emits SSE chunks back.
        mock_ensure_configured.return_value = ("https://api.cloudflare.com/ai/v1", "test-key")

        async def fake_stream():
            for content in ("hello", "world"):
                chunk = MagicMock()
                chunk.model_dump = MagicMock(return_value={"choices": [{"delta": {"content": content}, "index": 0}]})
                yield chunk

        mock_make_call.return_value = AsyncMock(return_value=fake_stream())

        with authenticated_client.stream(
            "POST",
            "/v1/responses",
            json={
                "model": "@cf/zai-org/glm-5.2",
                "input": "Hello",
                "stream": True,
            },
            headers={"Authorization": "Bearer phx_test_key"},
        ) as response:
            assert response.status_code == 200
            body = "".join(response.iter_text())

        assert '"hello"' in body
        assert '"world"' in body
        assert "[DONE]" in body
        mock_make_call.assert_called_once_with("https://api.cloudflare.com/ai/v1", "test-key")
        mock_aresponses.assert_not_called()

    @patch("llm_gateway.api.openai.make_cloudflare_responses_call")
    @patch("llm_gateway.api.openai.ensure_cloudflare_configured")
    def test_unpriced_cf_model_rejected_before_routing(
        self,
        mock_ensure_configured: MagicMock,
        mock_make_call: MagicMock,
        authenticated_client: TestClient,
    ) -> None:
        response = authenticated_client.post(
            "/v1/responses",
            json={
                "model": "@cf/meta/llama-3.3-70b-instruct",
                "input": "Hello",
            },
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 400
        assert response.json()["error"]["type"] == "invalid_request_error"
        assert "@cf/meta/llama-3.3-70b-instruct" in response.json()["error"]["message"]
        # Rejection must happen before we hand the model off to CF, or the gateway eats the
        # real CF bill while billing the user the flat fallback.
        mock_ensure_configured.assert_not_called()
        mock_make_call.assert_not_called()

    @patch("llm_gateway.api.openai.make_cloudflare_responses_call")
    @patch("llm_gateway.api.openai.ensure_cloudflare_configured")
    def test_previous_response_id_rejected_for_cf_model(
        self,
        mock_ensure_configured: MagicMock,
        mock_make_call: MagicMock,
        authenticated_client: TestClient,
    ) -> None:
        # The Responses->chat/completions bridge rebuilds prior turns from litellm proxy spend logs,
        # which this SDK-mode gateway doesn't have — so previous_response_id would silently drop
        # conversation context. Reject it explicitly rather than answer with lost history.
        response = authenticated_client.post(
            "/v1/responses",
            json={
                "model": "@cf/zai-org/glm-5.2",
                "input": "Hello",
                "previous_response_id": "resp_abc123",
            },
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 400
        assert response.json()["error"]["type"] == "invalid_request_error"
        assert "previous_response_id" in response.json()["error"]["message"]
        # Rejected before any CF hand-off.
        mock_ensure_configured.assert_not_called()
        mock_make_call.assert_not_called()

    @patch("llm_gateway.api.openai.make_cloudflare_responses_call")
    @patch("llm_gateway.api.openai.ensure_cloudflare_configured")
    def test_tools_rejected_for_cf_model(
        self,
        mock_ensure_configured: MagicMock,
        mock_make_call: MagicMock,
        authenticated_client: TestClient,
    ) -> None:
        # The Responses->chat/completions bridge doesn't faithfully translate Responses-shaped
        # tools, so CF's chat/completions endpoint would reject them. Reject up front instead of
        # handing CF a request that fails the moment tools are advertised.
        response = authenticated_client.post(
            "/v1/responses",
            json={
                "model": "@cf/zai-org/glm-5.2",
                "input": "Hello",
                "tools": [{"type": "function", "function": {"name": "get_weather", "parameters": {}}}],
            },
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 400
        assert response.json()["error"]["type"] == "invalid_request_error"
        assert "tools" in response.json()["error"]["message"]
        # Rejected before any CF hand-off.
        mock_ensure_configured.assert_not_called()
        mock_make_call.assert_not_called()


class TestUnsupportedModelRejection:
    """Gemini/Vertex models must be rejected before reaching litellm, which would
    otherwise raise ImportError from vertex_llm_base because we don't install
    litellm[google]."""

    @pytest.mark.parametrize(
        "model",
        [
            "gemini/gemini-3-pro-preview",
            "gemini/gemini-1.5-pro",
            "vertex_ai/gemini-1.5-pro",
            "vertex_ai-language-models/text-bison",
            "GEMINI/gemini-pro",  # case-insensitive prefix match
            # Bare gemini-* names (most commonly seen in the pod crash logs).
            # These may not be in the litellm cost registry yet, so we match
            # them by name prefix rather than relying on registry lookup.
            "gemini-3-pro-preview",
            "gemini-1.5-pro",
            "gemini-2.0-flash",
            "Gemini-3-Pro-Preview",  # case-insensitive
            # The `cloudflare/...` prefix would route to litellm's native CF
            # provider and bypass CLOUDFLARE_ALLOWED_MODELS. Block at the edge.
            "cloudflare/@cf/meta/llama-3.3-70b-instruct",
            "cloudflare/@cf/moonshotai/kimi-k2.6",
            "CLOUDFLARE/@cf/foo",
        ],
    )
    @patch("llm_gateway.api.openai.litellm.acompletion")
    def test_unsupported_model_prefix_returns_400(
        self,
        mock_completion: MagicMock,
        authenticated_client: TestClient,
        model: str,
    ) -> None:
        response = authenticated_client.post(
            "/v1/chat/completions",
            json={"model": model, "messages": [{"role": "user", "content": "Hi"}]},
            headers={"Authorization": "Bearer phx_test_key"},
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "model_not_supported"
        mock_completion.assert_not_called()

    @patch("llm_gateway.api.openai.litellm.acompletion")
    def test_unsupported_provider_via_registry_returns_400(
        self,
        mock_completion: MagicMock,
        authenticated_client: TestClient,
    ) -> None:
        # Bare model name (no prefix) where litellm's registry identifies the
        # provider as vertex_ai — we still need to catch this.
        from llm_gateway.rate_limiting.model_cost_service import ModelCostService
        from llm_gateway.services.model_registry import ModelRegistryService

        fake_costs = {
            "gemini-pro-bare": {
                "litellm_provider": "vertex_ai",
                "max_input_tokens": 1000,
                "supports_vision": False,
                "mode": "chat",
            },
        }

        def fake_get_costs(self: ModelCostService, model: str):
            return fake_costs.get(model)

        ModelRegistryService.reset_instance()
        ModelCostService.reset_instance()
        try:
            with patch.object(ModelCostService, "get_costs", fake_get_costs):
                response = authenticated_client.post(
                    "/v1/chat/completions",
                    json={"model": "gemini-pro-bare", "messages": [{"role": "user", "content": "Hi"}]},
                    headers={"Authorization": "Bearer phx_test_key"},
                )
        finally:
            ModelRegistryService.reset_instance()
            ModelCostService.reset_instance()

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "model_not_supported"
        mock_completion.assert_not_called()
