import pytest
from fastapi import HTTPException

from llm_gateway.products.config import (
    ALLOWED_PRODUCTS,
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
            # twig requires OAuth with valid app ID
            ("twig", "personal_api_key", None, None, False, "requires OAuth"),
            ("twig", "oauth_access_token", "invalid-app-id", None, False, "not authorized"),
            ("twig", "oauth_access_token", TWIG_US_APP_ID, None, True, None),
            ("twig", "oauth_access_token", TWIG_EU_APP_ID, None, True, None),
            # wizard allows API keys and OAuth with valid app ID
            ("wizard", "personal_api_key", None, "claude-3-opus", True, None),
            ("wizard", "oauth_access_token", "invalid-app-id", None, False, "not authorized"),
            ("wizard", "oauth_access_token", WIZARD_US_APP_ID, None, True, None),
            ("wizard", "oauth_access_token", WIZARD_EU_APP_ID, None, True, None),
            # django allows API keys with any model
            ("django", "personal_api_key", None, "gpt-4.1-mini", True, None),
            ("django", "personal_api_key", None, "claude-3-opus", True, None),
            ("django", "oauth_access_token", "any-app-id", "gpt-4.1-mini", True, None),
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
            "claude-sonnet-4-5",
            "claude-haiku-4-5",
            "gpt-5.2",
            "gpt-5-mini",
        ],
    )
    def test_array_allows_restricted_models_with_valid_app_id(self, model: str):
        allowed, error = check_product_access("array", "oauth_access_token", TWIG_US_APP_ID, model)
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
    def test_array_rejects_non_allowed_models(self, model: str):
        allowed, error = check_product_access("array", "oauth_access_token", TWIG_US_APP_ID, model)
        assert allowed is False
        assert error is not None
        assert "not allowed" in error

    @pytest.mark.parametrize(
        "model",
        [
            "claude-opus-4-5",
            "claude-sonnet-4-5",
            "claude-haiku-4-5",
            "gpt-5.2",
            "gpt-5-mini",
            "claude-opus-4-5-20260101",
        ],
    )
    def test_twig_allows_configured_models_with_valid_app_id(self, model: str):
        allowed, error = check_product_access("twig", "oauth_access_token", TWIG_US_APP_ID, model)
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
    def test_twig_rejects_unconfigured_models(self, model: str):
        allowed, error = check_product_access("twig", "oauth_access_token", TWIG_US_APP_ID, model)
        assert allowed is False
        assert error is not None
        assert "not allowed" in error


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
        assert resolve_product_alias("array") == "twig"

    def test_resolve_product_alias_returns_input_if_not_aliased(self):
        assert resolve_product_alias("wizard") == "wizard"
