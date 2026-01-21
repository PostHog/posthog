import pytest

from llm_gateway.products.config import (
    ARRAY_EU_APP_ID,
    ARRAY_US_APP_ID,
    WIZARD_EU_APP_ID,
    WIZARD_US_APP_ID,
    check_product_access,
    get_product_config,
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
            # array requires OAuth with valid app ID
            ("array", "personal_api_key", None, None, False, "requires OAuth"),
            ("array", "oauth_access_token", "invalid-app-id", None, False, "not authorized"),
            ("array", "oauth_access_token", ARRAY_US_APP_ID, None, True, None),
            ("array", "oauth_access_token", ARRAY_EU_APP_ID, None, True, None),
            # wizard allows API keys and OAuth with valid app ID
            ("wizard", "personal_api_key", None, "claude-3-opus", True, None),
            ("wizard", "oauth_access_token", "invalid-app-id", None, False, "not authorized"),
            ("wizard", "oauth_access_token", WIZARD_US_APP_ID, None, True, None),
            ("wizard", "oauth_access_token", WIZARD_EU_APP_ID, None, True, None),
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
            "claude-3-5-haiku-20241022",
            "gpt-4o-mini",
            "claude-3-opus",
            "gpt-4o",
        ],
    )
    def test_array_allows_all_models_with_valid_app_id(self, model: str):
        allowed, error = check_product_access("array", "oauth_access_token", ARRAY_US_APP_ID, model)
        assert allowed is True
        assert error is None
