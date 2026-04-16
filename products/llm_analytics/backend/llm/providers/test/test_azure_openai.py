import pytest
from unittest.mock import MagicMock, patch

import httpx

from products.llm_analytics.backend.llm.providers.azure_openai import DEFAULT_API_VERSION, AzureOpenAIAdapter

MOCK_ENDPOINT = "https://my-resource.openai.azure.com/"


def _mock_http_response(*, status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = json_data or {"data": []}
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError("error", request=MagicMock(), response=response)
    else:
        response.raise_for_status.return_value = None
    return response


class TestAzureOpenAIValidateKey:
    @patch("products.llm_analytics.backend.llm.providers.azure_openai.httpx.get")
    def test_validate_key_valid_returns_ok(self, mock_get):
        mock_get.return_value = _mock_http_response(json_data={"data": []})

        state, message = AzureOpenAIAdapter.validate_key("hex-api-key-123", azure_endpoint=MOCK_ENDPOINT)

        assert state == "ok"
        assert message is None
        mock_get.assert_called_once()
        assert mock_get.call_args.args[0] == f"{MOCK_ENDPOINT.rstrip('/')}/openai/deployments"
        assert mock_get.call_args.kwargs["params"]["api-version"] == DEFAULT_API_VERSION
        assert mock_get.call_args.kwargs["headers"]["api-key"] == "hex-api-key-123"

    @patch("products.llm_analytics.backend.llm.providers.azure_openai.httpx.get")
    def test_validate_key_auth_error_returns_invalid(self, mock_get):
        mock_get.return_value = _mock_http_response(status_code=401)

        state, message = AzureOpenAIAdapter.validate_key("bad-key", azure_endpoint=MOCK_ENDPOINT)

        assert state == "invalid"
        assert message == "Invalid API key"

    @patch("products.llm_analytics.backend.llm.providers.azure_openai.httpx.get")
    def test_validate_key_not_found_returns_invalid(self, mock_get):
        mock_get.return_value = _mock_http_response(status_code=404)

        state, message = AzureOpenAIAdapter.validate_key("key", azure_endpoint=MOCK_ENDPOINT)

        assert state == "invalid"
        assert "endpoint not found" in (message or "")

    @patch("products.llm_analytics.backend.llm.providers.azure_openai.httpx.get")
    def test_validate_key_connection_error_returns_error(self, mock_get):
        mock_get.side_effect = httpx.ConnectError("boom")

        state, message = AzureOpenAIAdapter.validate_key("key", azure_endpoint=MOCK_ENDPOINT)

        assert state == "error"
        assert message == "Could not connect to Azure OpenAI endpoint"

    @patch("products.llm_analytics.backend.llm.providers.azure_openai.httpx.get")
    def test_validate_key_rate_limit_returns_error(self, mock_get):
        mock_get.return_value = _mock_http_response(status_code=429)

        state, message = AzureOpenAIAdapter.validate_key("key", azure_endpoint=MOCK_ENDPOINT)

        assert state == "error"
        assert message == "Rate limited, please try again later"

    def test_validate_key_missing_endpoint_returns_invalid(self):
        state, message = AzureOpenAIAdapter.validate_key("key")

        assert state == "invalid"
        assert message == "Azure endpoint is required"

    @patch("products.llm_analytics.backend.llm.providers.azure_openai.httpx.get")
    def test_validate_key_custom_api_version(self, mock_get):
        mock_get.return_value = _mock_http_response(json_data={"data": []})

        AzureOpenAIAdapter.validate_key("key", azure_endpoint=MOCK_ENDPOINT, api_version="2025-01-01")

        assert mock_get.call_args.kwargs["params"]["api-version"] == "2025-01-01"


class TestAzureOpenAIListModels:
    def test_list_models_without_key_returns_empty(self):
        assert AzureOpenAIAdapter.list_models(None) == []

    def test_list_models_without_endpoint_returns_empty(self):
        assert AzureOpenAIAdapter.list_models("key") == []

    @patch("products.llm_analytics.backend.llm.providers.azure_openai.httpx.get")
    def test_list_models_returns_deployment_names_sorted_by_created_at_desc(self, mock_get):
        mock_get.return_value = _mock_http_response(
            json_data={
                "data": [
                    {"id": "my-gpt4-deployment", "created_at": 1700000000},
                    {"id": "my-gpt4o-deployment", "created_at": 1710000000},
                ]
            }
        )

        models = AzureOpenAIAdapter.list_models("key", azure_endpoint=MOCK_ENDPOINT)

        assert models == ["my-gpt4o-deployment", "my-gpt4-deployment"]

    @patch(
        "products.llm_analytics.backend.llm.providers.azure_openai.httpx.get",
        side_effect=Exception("API error"),
    )
    def test_list_models_error_returns_empty(self, _mock_get):
        assert AzureOpenAIAdapter.list_models("key", azure_endpoint=MOCK_ENDPOINT) == []

    @patch("products.llm_analytics.backend.llm.providers.azure_openai.httpx.get")
    def test_list_models_uses_deployments_endpoint(self, mock_get):
        mock_get.return_value = _mock_http_response(json_data={"data": []})

        AzureOpenAIAdapter.list_models("key", azure_endpoint=MOCK_ENDPOINT)

        mock_get.assert_called_once()
        assert mock_get.call_args.args[0] == f"{MOCK_ENDPOINT.rstrip('/')}/openai/deployments"

    @patch("products.llm_analytics.backend.llm.providers.azure_openai.httpx.get")
    def test_list_models_handles_missing_created_at(self, mock_get):
        mock_get.return_value = _mock_http_response(
            json_data={
                "data": [
                    {"id": "a-deployment"},
                    {"id": "b-deployment", "created_at": 1710000000},
                ]
            }
        )

        models = AzureOpenAIAdapter.list_models("key", azure_endpoint=MOCK_ENDPOINT)

        # b has created_at, a doesn't (treated as 0) — b sorts first
        assert models == ["b-deployment", "a-deployment"]

    @patch("products.llm_analytics.backend.llm.providers.azure_openai.httpx.get")
    def test_list_models_skips_entries_without_id(self, mock_get):
        mock_get.return_value = _mock_http_response(
            json_data={"data": [{"created_at": 1700000000}, {"id": "valid-deployment", "created_at": 1700000001}]}
        )

        models = AzureOpenAIAdapter.list_models("key", azure_endpoint=MOCK_ENDPOINT)

        assert models == ["valid-deployment"]

    @patch("products.llm_analytics.backend.llm.providers.azure_openai.httpx.get")
    def test_list_models_malformed_json_returns_empty(self, mock_get):
        response = MagicMock(spec=httpx.Response)
        response.status_code = 200
        response.json.side_effect = ValueError("not JSON")
        response.raise_for_status.return_value = None
        mock_get.return_value = response

        assert AzureOpenAIAdapter.list_models("key", azure_endpoint=MOCK_ENDPOINT) == []


class TestAzureOpenAIRecommendedModels:
    def test_recommended_models_returns_empty(self):
        assert AzureOpenAIAdapter.recommended_models() == set()


class TestAzureOpenAIDefaultKey:
    def test_get_api_key_raises(self):
        with pytest.raises(ValueError, match="BYOKEY-only"):
            AzureOpenAIAdapter.get_api_key()

    def test_get_default_api_key_raises(self):
        adapter = AzureOpenAIAdapter()

        with pytest.raises(ValueError, match="BYOKEY-only"):
            adapter._get_default_api_key()


class TestAzureOpenAICreateClient:
    @patch("products.llm_analytics.backend.llm.providers.azure_openai.openai.AzureOpenAI")
    def test_create_client_uses_azure_config(self, mock_azure):
        from products.llm_analytics.backend.llm.types import AnalyticsContext

        adapter = AzureOpenAIAdapter(azure_endpoint=MOCK_ENDPOINT, api_version="2025-01-01")
        analytics = AnalyticsContext(distinct_id="test", capture=False)

        adapter._create_client("test-key", None, analytics)

        mock_azure.assert_called_once()
        assert mock_azure.call_args.kwargs["api_key"] == "test-key"
        assert mock_azure.call_args.kwargs["azure_endpoint"] == MOCK_ENDPOINT
        assert mock_azure.call_args.kwargs["api_version"] == "2025-01-01"

    @patch("products.llm_analytics.backend.llm.providers.azure_openai.openai.AzureOpenAI")
    def test_create_client_ignores_base_url(self, mock_azure):
        from products.llm_analytics.backend.llm.types import AnalyticsContext

        adapter = AzureOpenAIAdapter(azure_endpoint=MOCK_ENDPOINT)
        analytics = AnalyticsContext(distinct_id="test", capture=False)

        adapter._create_client("test-key", "https://ignored.example.com", analytics)

        mock_azure.assert_called_once()
        assert mock_azure.call_args.kwargs["azure_endpoint"] == MOCK_ENDPOINT
        assert "base_url" not in mock_azure.call_args.kwargs

    @patch("products.llm_analytics.backend.llm.providers.azure_openai.posthoganalytics.default_client", new=MagicMock())
    @patch("products.llm_analytics.backend.llm.providers.azure_openai.WrappedAzureOpenAI")
    def test_create_client_uses_wrapped_client_when_analytics_enabled(self, mock_wrapped):
        from products.llm_analytics.backend.llm.types import AnalyticsContext

        adapter = AzureOpenAIAdapter(azure_endpoint=MOCK_ENDPOINT)
        analytics = AnalyticsContext(distinct_id="test", capture=True)

        adapter._create_client("test-key", None, analytics)

        mock_wrapped.assert_called_once()
        assert mock_wrapped.call_args.kwargs["api_key"] == "test-key"
        assert mock_wrapped.call_args.kwargs["azure_endpoint"] == MOCK_ENDPOINT
