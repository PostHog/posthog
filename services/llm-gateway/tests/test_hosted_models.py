import os
from unittest.mock import MagicMock, patch

import litellm
import pytest

from llm_gateway.services.hosted_models import (
    HostedModelRegistry,
    resolve_hosted_model,
)


@pytest.fixture(autouse=True)
def reset_registry():
    HostedModelRegistry.reset_instance()
    yield
    HostedModelRegistry.reset_instance()


def _mock_settings(
    us_url: str | None = None,
    eu_url: str | None = None,
    api_key: str | None = None,
) -> MagicMock:
    settings = MagicMock()
    settings.glm5_api_base_url_us = us_url
    settings.glm5_api_base_url_eu = eu_url
    settings.glm5_api_key = api_key
    return settings


class TestHostedModelRegistry:
    def test_singleton(self):
        with patch("llm_gateway.services.hosted_models.get_settings", return_value=_mock_settings()):
            a = HostedModelRegistry.get_instance()
            b = HostedModelRegistry.get_instance()
            assert a is b

    def test_registers_glm5_when_url_configured(self):
        with patch(
            "llm_gateway.services.hosted_models.get_settings",
            return_value=_mock_settings(us_url="https://us.modal.run/v1"),
        ):
            registry = HostedModelRegistry.get_instance()
            assert registry.is_hosted("glm-5")
            assert not registry.is_hosted("gpt-4o")

    def test_no_models_when_nothing_configured(self):
        with patch("llm_gateway.services.hosted_models.get_settings", return_value=_mock_settings()):
            registry = HostedModelRegistry.get_instance()
            assert len(registry.get_all()) == 0

    def test_rejects_non_http_url(self):
        with (
            patch(
                "llm_gateway.services.hosted_models.get_settings",
                return_value=_mock_settings(us_url="ftp://bad.example.com/v1"),
            ),
            pytest.raises(ValueError, match="must be an HTTP"),
        ):
            HostedModelRegistry.get_instance()

    def test_rejects_url_without_host(self):
        with (
            patch(
                "llm_gateway.services.hosted_models.get_settings",
                return_value=_mock_settings(us_url="https:///v1"),
            ),
            pytest.raises(ValueError, match="missing host"),
        ):
            HostedModelRegistry.get_instance()

    def test_registers_litellm_cost_data(self):
        with patch(
            "llm_gateway.services.hosted_models.get_settings",
            return_value=_mock_settings(us_url="https://us.modal.run/v1"),
        ):
            HostedModelRegistry.get_instance()
            cost = litellm.model_cost.get("hosted_vllm/glm-5")
            assert cost is not None
            assert cost["input_cost_per_token"] > 0
            assert cost["output_cost_per_token"] > 0
            assert cost["mode"] == "chat"

    @pytest.mark.parametrize(
        "us_url,eu_url,region,expected_url",
        [
            ("https://us.modal.run/v1", None, "us", "https://us.modal.run/v1"),
            (None, "https://eu.modal.run/v1", "eu", "https://eu.modal.run/v1"),
            ("https://us.modal.run/v1", "https://eu.modal.run/v1", "us", "https://us.modal.run/v1"),
            ("https://us.modal.run/v1", "https://eu.modal.run/v1", "eu", "https://eu.modal.run/v1"),
            ("https://us.modal.run/v1", None, "eu", "https://us.modal.run/v1"),
            (None, "https://eu.modal.run/v1", "us", "https://eu.modal.run/v1"),
        ],
    )
    def test_region_routing(self, us_url: str | None, eu_url: str | None, region: str, expected_url: str):
        with patch(
            "llm_gateway.services.hosted_models.get_settings",
            return_value=_mock_settings(us_url=us_url, eu_url=eu_url),
        ):
            registry = HostedModelRegistry.get_instance()
            model = registry._models["glm-5"]
            assert model.api_base_for_region(region) == expected_url


class TestResolveHostedModel:
    def test_resolves_with_api_key(self):
        with (
            patch(
                "llm_gateway.services.hosted_models.get_settings",
                return_value=_mock_settings(us_url="https://us.modal.run/v1", api_key="sk-test-key"),
            ),
            patch.dict(os.environ, {"POSTHOG_REGION": "us"}),
        ):
            result = resolve_hosted_model("glm-5")
            assert result is not None
            model_id, api_base, api_key = result
            assert model_id == "hosted_vllm/glm-5"
            assert api_base == "https://us.modal.run/v1"
            assert api_key == "sk-test-key"

    def test_resolves_without_api_key(self):
        with (
            patch(
                "llm_gateway.services.hosted_models.get_settings",
                return_value=_mock_settings(us_url="https://us.modal.run/v1"),
            ),
            patch.dict(os.environ, {"POSTHOG_REGION": "us"}),
        ):
            result = resolve_hosted_model("glm-5")
            assert result is not None
            _, _, api_key = result
            assert api_key is None

    def test_returns_none_for_non_hosted(self):
        with patch("llm_gateway.services.hosted_models.get_settings", return_value=_mock_settings()):
            assert resolve_hosted_model("gpt-4o") is None

    def test_returns_none_when_unconfigured(self):
        with patch("llm_gateway.services.hosted_models.get_settings", return_value=_mock_settings()):
            assert resolve_hosted_model("glm-5") is None

    def test_eu_region_routing(self):
        with (
            patch(
                "llm_gateway.services.hosted_models.get_settings",
                return_value=_mock_settings(us_url="https://us.modal.run/v1", eu_url="https://eu.modal.run/v1"),
            ),
            patch.dict(os.environ, {"POSTHOG_REGION": "eu"}),
        ):
            result = resolve_hosted_model("glm-5")
            assert result is not None
            _, api_base, _ = result
            assert api_base == "https://eu.modal.run/v1"
