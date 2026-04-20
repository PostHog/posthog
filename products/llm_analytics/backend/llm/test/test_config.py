from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from products.llm_analytics.backend.llm.config import ProviderConfig, get_eval_config


class TestProviderConfig(SimpleTestCase):
    def test_provider_config_immutable(self):
        config = ProviderConfig(api_key="test-key", base_url="https://example.com")
        assert config.api_key == "test-key"
        assert config.base_url == "https://example.com"

    def test_provider_config_default_base_url(self):
        config = ProviderConfig(api_key="test-key")
        assert config.base_url is None


class TestGetEvalConfig(SimpleTestCase):
    @parameterized.expand(
        [
            ("openai", "LLMA_EVAL_OPENAI_API_KEY", "OPENAI_API_KEY", "LLMA_EVAL_OPENAI_BASE_URL", "OPENAI_BASE_URL"),
            ("anthropic", "LLMA_EVAL_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY", None, None),
            ("gemini", "LLMA_EVAL_GEMINI_API_KEY", "GEMINI_API_KEY", None, None),
        ]
    )
    def test_eval_specific_key_takes_precedence(
        self, provider, eval_key_setting, fallback_key_setting, eval_url_setting, fallback_url_setting
    ):
        settings_dict = {
            eval_key_setting: "eval-specific-key",
            fallback_key_setting: "fallback-key",
        }
        if eval_url_setting:
            settings_dict[eval_url_setting] = "https://eval.example.com"
            settings_dict[fallback_url_setting] = "https://fallback.example.com"

        with override_settings(**settings_dict):
            config = get_eval_config(provider)

        assert config is not None
        assert config.api_key == "eval-specific-key"
        if eval_url_setting:
            assert config.base_url == "https://eval.example.com"

    @parameterized.expand(
        [
            ("openai", "LLMA_EVAL_OPENAI_API_KEY", "OPENAI_API_KEY"),
            ("anthropic", "LLMA_EVAL_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
            ("gemini", "LLMA_EVAL_GEMINI_API_KEY", "GEMINI_API_KEY"),
        ]
    )
    def test_falls_back_to_general_key_when_eval_empty(self, provider, eval_key_setting, fallback_key_setting):
        settings_dict = {
            eval_key_setting: "",
            fallback_key_setting: "fallback-key",
        }
        if provider == "openai":
            settings_dict["LLMA_EVAL_OPENAI_BASE_URL"] = ""
            settings_dict["OPENAI_BASE_URL"] = "https://fallback.example.com"

        with override_settings(**settings_dict):
            config = get_eval_config(provider)

        assert config is not None
        assert config.api_key == "fallback-key"
        if provider == "openai":
            assert config.base_url == "https://fallback.example.com"

    @parameterized.expand(
        [
            ("openai", "LLMA_EVAL_OPENAI_API_KEY", "OPENAI_API_KEY"),
            ("anthropic", "LLMA_EVAL_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
            ("gemini", "LLMA_EVAL_GEMINI_API_KEY", "GEMINI_API_KEY"),
        ]
    )
    def test_returns_none_when_no_key_available(self, provider, eval_key_setting, fallback_key_setting):
        settings_dict = {
            eval_key_setting: "",
            fallback_key_setting: "",
        }
        if provider == "openai":
            settings_dict["LLMA_EVAL_OPENAI_BASE_URL"] = ""
            settings_dict["OPENAI_BASE_URL"] = "https://example.com"

        with override_settings(**settings_dict):
            config = get_eval_config(provider)

        assert config is None

    def test_returns_none_for_unsupported_provider(self):
        config = get_eval_config("unsupported")
        assert config is None

    def test_openai_base_url_fallback(self):
        with override_settings(
            LLMA_EVAL_OPENAI_API_KEY="eval-key",
            LLMA_EVAL_OPENAI_BASE_URL="",
            OPENAI_BASE_URL="https://api.openai.com/v1",
        ):
            config = get_eval_config("openai")

        assert config is not None
        assert config.base_url == "https://api.openai.com/v1"

    def test_anthropic_and_gemini_have_no_base_url(self):
        with override_settings(
            LLMA_EVAL_ANTHROPIC_API_KEY="anthropic-key",
            LLMA_EVAL_GEMINI_API_KEY="gemini-key",
        ):
            anthropic_config = get_eval_config("anthropic")
            gemini_config = get_eval_config("gemini")

        assert anthropic_config is not None
        assert anthropic_config.base_url is None

        assert gemini_config is not None
        assert gemini_config.base_url is None
