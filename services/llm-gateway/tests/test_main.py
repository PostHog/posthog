import os

import pytest

from llm_gateway.config import Settings, get_settings
from llm_gateway.main import export_provider_credentials

_EXPORTED_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "AWS_REGION",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_ORG_ID",
    "OPENROUTER_API_KEY",
    "FIREWORKS_API_KEY",
)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Start each test from a clean slate so leakage from the surrounding shell
    # (or earlier tests) can't make a missing export look like a passing one.
    for var in _EXPORTED_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    get_settings.cache_clear()


class TestExportProviderCredentials:
    @pytest.mark.parametrize(
        "setting_name,setting_value,expected_env,expected_value",
        [
            pytest.param(
                "openai_organization",
                "org-test-fixture",
                "OPENAI_ORG_ID",
                "org-test-fixture",
                id="openai_organization_to_OPENAI_ORG_ID",
            ),
            pytest.param(
                "openai_api_base_url",
                "https://eu.api.openai.com/v1",
                "OPENAI_BASE_URL",
                "https://eu.api.openai.com/v1",
                id="openai_api_base_url_to_OPENAI_BASE_URL",
            ),
            pytest.param(
                "openai_api_key",
                "sk-test",
                "OPENAI_API_KEY",
                "sk-test",
                id="openai_api_key_to_OPENAI_API_KEY",
            ),
            pytest.param(
                "anthropic_api_key",
                "sk-ant-test",
                "ANTHROPIC_API_KEY",
                "sk-ant-test",
                id="anthropic_api_key_to_ANTHROPIC_API_KEY",
            ),
            pytest.param(
                "bedrock_region_name",
                "eu-central-1",
                "AWS_REGION",
                "eu-central-1",
                id="bedrock_region_name_to_AWS_REGION",
            ),
            pytest.param(
                "openrouter_api_key",
                "sk-or-test",
                "OPENROUTER_API_KEY",
                "sk-or-test",
                id="openrouter_api_key_to_OPENROUTER_API_KEY",
            ),
            pytest.param(
                "fireworks_api_key",
                "fw-test",
                "FIREWORKS_API_KEY",
                "fw-test",
                id="fireworks_api_key_to_FIREWORKS_API_KEY",
            ),
        ],
    )
    def test_exports_setting_to_env_var(
        self,
        setting_name: str,
        setting_value: str,
        expected_env: str,
        expected_value: str,
    ) -> None:
        # model_validate lets us construct from a parametrized dict without
        # tripping mypy on the kwargs spread (Settings has per-field types,
        # so dict[str, str] is rejected by **kwargs typing).
        settings = Settings.model_validate({setting_name: setting_value})

        export_provider_credentials(settings)

        assert os.environ.get(expected_env) == expected_value

    @pytest.mark.parametrize(
        "env_var",
        _EXPORTED_ENV_VARS,
    )
    def test_unset_settings_do_not_touch_env(self, env_var: str) -> None:
        # When the setting is unset, the corresponding env var must remain unset —
        # otherwise an empty default could shadow ambient credentials (e.g. AWS_REGION
        # from IRSA) or attribute traffic to the wrong OpenAI org.
        settings = Settings()

        export_provider_credentials(settings)

        assert env_var not in os.environ

    def test_does_not_overwrite_existing_env_when_setting_is_unset(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # If LLM_GATEWAY_OPENAI_ORGANIZATION is not set, an org id that was
        # already present in the environment (e.g. set by the runtime) must
        # survive untouched.
        monkeypatch.setenv("OPENAI_ORG_ID", "org-preset-by-runtime")
        settings = Settings()

        export_provider_credentials(settings)

        assert os.environ["OPENAI_ORG_ID"] == "org-preset-by-runtime"

    def test_settings_picks_up_env_prefixed_organization(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # End-to-end: LLM_GATEWAY_OPENAI_ORGANIZATION → Settings.openai_organization
        # → OPENAI_ORG_ID, which is what litellm / the OpenAI SDK read.
        monkeypatch.setenv("LLM_GATEWAY_OPENAI_ORGANIZATION", "org-test-fixture")
        get_settings.cache_clear()

        settings = get_settings()
        assert settings.openai_organization == "org-test-fixture"

        export_provider_credentials(settings)
        assert os.environ["OPENAI_ORG_ID"] == "org-test-fixture"

    def test_settings_picks_up_env_prefixed_base_url(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("LLM_GATEWAY_OPENAI_API_BASE_URL", "https://eu.api.openai.com/v1")
        get_settings.cache_clear()

        settings = get_settings()
        assert settings.openai_api_base_url == "https://eu.api.openai.com/v1"

        export_provider_credentials(settings)
        assert os.environ["OPENAI_BASE_URL"] == "https://eu.api.openai.com/v1"
