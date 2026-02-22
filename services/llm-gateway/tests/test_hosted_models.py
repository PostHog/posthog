import os
from unittest.mock import MagicMock, patch

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


def _mock_settings(us_url: str | None = None, eu_url: str | None = None) -> MagicMock:
    settings = MagicMock()
    settings.glm5_api_base_url_us = us_url
    settings.glm5_api_base_url_eu = eu_url
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
            return_value=_mock_settings(us_url="https://us.modal.run/glm5"),
        ):
            registry = HostedModelRegistry.get_instance()
            assert registry.is_hosted("glm-5")
            assert not registry.is_hosted("gpt-4o")

    def test_no_models_when_nothing_configured(self):
        with patch("llm_gateway.services.hosted_models.get_settings", return_value=_mock_settings()):
            registry = HostedModelRegistry.get_instance()
            assert len(registry.get_all()) == 0

    @pytest.mark.parametrize(
        "us_url,eu_url,region,expected_url",
        [
            ("https://us.modal.run", None, "us", "https://us.modal.run"),
            (None, "https://eu.modal.run", "eu", "https://eu.modal.run"),
            ("https://us.modal.run", "https://eu.modal.run", "us", "https://us.modal.run"),
            ("https://us.modal.run", "https://eu.modal.run", "eu", "https://eu.modal.run"),
            ("https://us.modal.run", None, "eu", "https://us.modal.run"),
            (None, "https://eu.modal.run", "us", "https://eu.modal.run"),
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
    def test_resolves_configured_model(self):
        with (
            patch(
                "llm_gateway.services.hosted_models.get_settings",
                return_value=_mock_settings(us_url="https://us.modal.run/glm5"),
            ),
            patch.dict(os.environ, {"POSTHOG_REGION": "us"}),
        ):
            result = resolve_hosted_model("glm-5")
            assert result is not None
            model_id, api_base = result
            assert model_id == "hosted_vllm/glm-5"
            assert api_base == "https://us.modal.run/glm5"

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
                return_value=_mock_settings(us_url="https://us.modal.run/glm5", eu_url="https://eu.modal.run/glm5"),
            ),
            patch.dict(os.environ, {"POSTHOG_REGION": "eu"}),
        ):
            result = resolve_hosted_model("glm-5")
            assert result is not None
            _, api_base = result
            assert api_base == "https://eu.modal.run/glm5"
