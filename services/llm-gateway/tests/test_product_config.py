from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from llm_gateway.products.config import (
    ALLOWED_PRODUCTS,
    BEDROCK_MODELS,
    POSTHOG_CODE_EU_APP_ID,
    POSTHOG_CODE_US_APP_ID,
    PRODUCT_ALIASES,
    PRODUCTS,
    TWIG_EU_APP_ID,
    TWIG_US_APP_ID,
    WIZARD_EU_APP_ID,
    WIZARD_US_APP_ID,
    check_product_access,
    get_product_config,
    resolve_product_alias,
    validate_product,
)


class TestGetProductConfig:
    def test_returns_config_for_known_product(self):
        config = get_product_config("llm_gateway")
        assert config is not None
        assert config.allow_api_keys is True

    def test_returns_none_for_unknown_product(self):
        config = get_product_config("unknown_product")
        assert config is None


class TestCheckProductAccess:
    @pytest.mark.parametrize(
        "product,auth_method,application_id,model,expected_allowed,expected_error_contains",
        [
            # llm_gateway allows everything
            ("llm_gateway", "personal_api_key", None, "claude-3-opus", True, None),
            ("llm_gateway", "oauth_access_token", "any-app-id", "gpt-4o", True, None),
            ("llm_gateway", "personal_api_key", None, None, True, None),
            # posthog_code requires OAuth with valid app ID
            ("posthog_code", "personal_api_key", None, None, False, "requires OAuth"),
            ("posthog_code", "oauth_access_token", "invalid-app-id", None, False, "not authorized"),
            ("posthog_code", "oauth_access_token", POSTHOG_CODE_US_APP_ID, None, True, None),
            ("posthog_code", "oauth_access_token", POSTHOG_CODE_EU_APP_ID, None, True, None),
            # wizard allows API keys and OAuth with valid app ID
            ("wizard", "personal_api_key", None, "claude-3-opus", True, None),
            ("wizard", "oauth_access_token", "invalid-app-id", None, False, "not authorized"),
            ("wizard", "oauth_access_token", WIZARD_US_APP_ID, None, True, None),
            ("wizard", "oauth_access_token", WIZARD_EU_APP_ID, None, True, None),
            # django allows API keys with any model
            ("django", "personal_api_key", None, "gpt-4.1-mini", True, None),
            ("django", "personal_api_key", None, "claude-3-opus", True, None),
            ("django", "oauth_access_token", "any-app-id", "gpt-4.1-mini", True, None),
            # llma_translation allows API keys but only gpt-4.1-mini
            ("llma_translation", "personal_api_key", None, "gpt-4.1-mini", True, None),
            ("llma_translation", "personal_api_key", None, "claude-3-opus", False, "not allowed"),
            ("llma_translation", "oauth_access_token", "any-app-id", "gpt-4.1-mini", True, None),
            # unknown product
            ("unknown", "personal_api_key", None, None, False, "Unknown product"),
        ],
    )
    def test_access_combinations(
        self,
        product: str,
        auth_method: str,
        application_id: str | None,
        model: str | None,
        expected_allowed: bool,
        expected_error_contains: str | None,
    ):
        allowed, error = check_product_access(product, auth_method, application_id, model)
        assert allowed == expected_allowed
        if expected_error_contains:
            assert error is not None
            assert expected_error_contains in error

    @pytest.mark.parametrize(
        "model",
        [
            "claude-opus-4-5",
            "claude-opus-4-6",
            "claude-opus-4-7",
            "claude-sonnet-4-5",
            "claude-sonnet-4-6",
            "claude-haiku-4-5",
            "gpt-5.3-codex",
            "gpt-5.2",
            "gpt-5-mini",
        ],
    )
    def test_posthog_code_allows_restricted_models_with_valid_app_id(self, model: str):
        allowed, error = check_product_access("posthog_code", "oauth_access_token", POSTHOG_CODE_US_APP_ID, model)
        assert allowed is True
        assert error is None

    @pytest.mark.parametrize(
        "model",
        [
            "gpt-4o",
            "gpt-4o-mini",
            "claude-3-5-haiku-20241022",
            "claude-3-opus",
            "o1",
        ],
    )
    def test_posthog_code_rejects_non_allowed_models(self, model: str):
        allowed, error = check_product_access("posthog_code", "oauth_access_token", POSTHOG_CODE_US_APP_ID, model)
        assert allowed is False
        assert error is not None
        assert "not allowed" in error

    @pytest.mark.parametrize(
        "model",
        [
            "claude-opus-4-5",
            "claude-opus-4-6",
            "claude-opus-4-7",
            "claude-sonnet-4-5",
            "claude-sonnet-4-6",
            "claude-haiku-4-5",
            "gpt-5.3-codex",
            "gpt-5.2",
            "gpt-5-mini",
        ],
    )
    def test_posthog_code_allows_configured_models(self, model: str):
        allowed, error = check_product_access("posthog_code", "oauth_access_token", POSTHOG_CODE_US_APP_ID, model)
        assert allowed is True
        assert error is None

    @pytest.mark.parametrize(
        "model",
        [
            "claude-opus-4-5-20260101",
            "claude-sonnet-4-5-20250929",
            "claude-haiku-4-5-20251001-v2",
            "gpt-5.2-turbo",
        ],
    )
    def test_posthog_code_allows_dated_variants_via_prefix_matching(self, model: str):
        allowed, error = check_product_access("posthog_code", "oauth_access_token", POSTHOG_CODE_US_APP_ID, model)
        assert allowed is True
        assert error is None

    @pytest.mark.parametrize(
        "model",
        [
            "Claude-Opus-4-5",
            "CLAUDE-SONNET-4-5",
            "GPT-5.2",
            "Claude-Haiku-4-5",
        ],
    )
    def test_model_matching_is_case_insensitive(self, model: str):
        allowed, error = check_product_access("posthog_code", "oauth_access_token", POSTHOG_CODE_US_APP_ID, model)
        assert allowed is True
        assert error is None

    @pytest.mark.parametrize(
        "alias",
        ["twig", "array"],
    )
    def test_legacy_aliases_resolve_to_posthog_code(self, alias: str):
        allowed, error = check_product_access(alias, "oauth_access_token", POSTHOG_CODE_US_APP_ID, "claude-sonnet-4-5")
        assert allowed is True
        assert error is None

    @pytest.mark.parametrize(
        "alias",
        ["twig", "array"],
    )
    def test_legacy_aliases_reject_non_allowed_models(self, alias: str):
        allowed, error = check_product_access(alias, "oauth_access_token", POSTHOG_CODE_US_APP_ID, "gpt-4o")
        assert allowed is False
        assert error is not None
        assert "not allowed" in error

    @pytest.mark.parametrize("model", sorted(BEDROCK_MODELS))
    def test_posthog_code_allows_bedrock_models(self, model: str):
        allowed, error = check_product_access("posthog_code", "oauth_access_token", POSTHOG_CODE_US_APP_ID, model)
        assert allowed is True
        assert error is None

    @pytest.mark.parametrize(
        "model",
        [
            "claude-opus-4-5",
            "claude-opus-4-6",
            "claude-opus-4-7",
            "claude-sonnet-4-5",
            "claude-haiku-4-5",
            "gpt-5.3-codex",
            "gpt-5.2",
            "gpt-5-mini",
        ],
    )
    def test_background_agents_allows_configured_models(self, model: str):
        allowed, error = check_product_access("background_agents", "oauth_access_token", POSTHOG_CODE_US_APP_ID, model)
        assert allowed is True
        assert error is None

    def test_background_agents_rejects_api_keys(self):
        allowed, error = check_product_access("background_agents", "personal_api_key", None, None)
        assert allowed is False
        assert error is not None
        assert "requires OAuth" in error

    def test_background_agents_does_not_allow_claude_sonnet_4_6(self):
        allowed, error = check_product_access(
            "background_agents", "oauth_access_token", POSTHOG_CODE_US_APP_ID, "claude-sonnet-4-6"
        )
        assert allowed is False
        assert error is not None
        assert "not allowed" in error

    @patch(
        "llm_gateway.products.config.get_settings", return_value=MagicMock(debug=False, bedrock_region_name="us-east-1")
    )
    def test_background_agents_allows_claude_sonnet_4_6_via_bedrock_provider(self, mock_get_settings: MagicMock):
        allowed, error = check_product_access(
            "background_agents",
            "oauth_access_token",
            POSTHOG_CODE_US_APP_ID,
            "claude-sonnet-4-6",
            provider="bedrock",
        )
        assert allowed is True
        assert error is None

    @pytest.mark.parametrize("model", sorted(BEDROCK_MODELS))
    def test_background_agents_allows_bedrock_models(self, model: str):
        allowed, error = check_product_access("background_agents", "oauth_access_token", POSTHOG_CODE_US_APP_ID, model)
        assert allowed is True
        assert error is None

    def test_slack_twig_allows_claude_haiku(self):
        allowed, error = check_product_access("slack-twig", "personal_api_key", None, "claude-haiku-4-5")
        assert allowed is True
        assert error is None

    def test_slack_twig_rejects_non_haiku_models(self):
        allowed, error = check_product_access("slack-twig", "personal_api_key", None, "claude-sonnet-4-5")
        assert allowed is False
        assert error is not None
        assert "not allowed" in error


class TestBackwardsCompatibility:
    def test_twig_app_id_constants_are_aliases(self):
        assert TWIG_US_APP_ID == POSTHOG_CODE_US_APP_ID
        assert TWIG_EU_APP_ID == POSTHOG_CODE_EU_APP_ID

    @pytest.mark.parametrize(
        "alias,target",
        [
            ("twig", "posthog_code"),
            ("array", "posthog_code"),
            ("slack-twig", "slack-posthog-code"),
        ],
    )
    def test_aliases_resolve_to_posthog_code(self, alias: str, target: str):
        assert resolve_product_alias(alias) == target

    def test_twig_alias_returns_same_config_as_posthog_code(self):
        assert get_product_config("twig") is get_product_config("posthog_code")

    def test_array_alias_returns_same_config_as_posthog_code(self):
        assert get_product_config("array") is get_product_config("posthog_code")

    def test_twig_alias_validates_to_posthog_code(self):
        assert validate_product("twig") == "posthog_code"

    def test_array_alias_validates_to_posthog_code(self):
        assert validate_product("array") == "posthog_code"

    def test_slack_twig_alias_resolves_to_slack_posthog_code(self):
        assert get_product_config("slack-twig") is get_product_config("slack-posthog-code")
        assert validate_product("slack-twig") == "slack-posthog-code"


class TestValidateProduct:
    def test_allowed_products_derived_from_products_dict(self):
        assert ALLOWED_PRODUCTS == frozenset(PRODUCTS.keys())

    @pytest.mark.parametrize("product", list(PRODUCTS.keys()))
    def test_valid_product_returns_product(self, product: str):
        assert validate_product(product) == product

    def test_invalid_product_raises_http_exception(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_product("invalid_product")
        assert exc_info.value.status_code == 400
        assert "Invalid product" in exc_info.value.detail

    @pytest.mark.parametrize("alias,target", list(PRODUCT_ALIASES.items()))
    def test_alias_resolves_to_target_product(self, alias: str, target: str):
        assert validate_product(alias) == target

    def test_resolve_product_alias_returns_alias_target(self):
        assert resolve_product_alias("array") == "posthog_code"
        assert resolve_product_alias("twig") == "posthog_code"
        assert resolve_product_alias("slack-twig") == "slack-posthog-code"

    def test_resolve_product_alias_returns_input_if_not_aliased(self):
        assert resolve_product_alias("wizard") == "wizard"
