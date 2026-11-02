from collections.abc import Callable
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.shopify import (
    ShopifyAuthMethodConfig,
    ShopifySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify import (
    SHOPIFY_ACCESS_TOKEN_REJECTED_ERROR,
    SHOPIFY_CREDENTIALS_CHECK_ERROR,
    SHOPIFY_STORE_FROZEN_ERROR,
    SHOPIFY_STORE_NOT_FOUND_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.source import ShopifySource

_SHOPIFY_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify"
TOKEN_PATH = "/admin/oauth/access_token"
TOKEN_RESPONSE = ScriptedResponse(json={"access_token": "tok"})

Script = Callable[[RecordedRequest], ScriptedResponse]


def _access_denied(message: str) -> dict[str, Any]:
    return {"errors": [{"message": message, "extensions": {"code": "ACCESS_DENIED"}}]}


def _post_returning(deny_if_query_contains: dict[str, dict[str, Any]]) -> Script:
    """A fake Shopify that returns JSON keyed on the GraphQL query text, and mints a token.

    Each key is a substring of a probe query; when a request's query contains it, the mapped
    payload is returned (e.g. an access-denied or throttled body). Anything else — including the
    `{ shop { id } }` token check and the `id` probes — comes back clean.
    """

    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path == TOKEN_PATH:
            return TOKEN_RESPONSE
        query = request.json().get("query", "")
        payload: dict[str, Any] = {"data": {}}
        for needle, denied_payload in deny_if_query_contains.items():
            if needle in query:
                payload = denied_payload
                break
        return ScriptedResponse(json=payload)

    return respond


def _config() -> ShopifySourceConfig:
    return ShopifySourceConfig(
        shopify_store_id="my-store",
        auth_method=ShopifyAuthMethodConfig(
            selection="client_credentials", shopify_client_id="cid", shopify_client_secret="secret"
        ),
    )


def _validate(script: Script, schema_name: str | None = None) -> tuple[bool, str | None]:
    with scripted_network(script):
        return ShopifySource().validate_credentials(_config(), team_id=1, schema_name=schema_name)


def _endpoint_permissions(script: Script, endpoints: list[str]) -> dict[str, str | None]:
    with scripted_network(script):
        return ShopifySource().get_endpoint_permissions(_config(), team_id=1, endpoints=endpoints)


def test_validating_a_schema_names_the_missing_scope():
    # Validating one schema surfaces our own message naming the scope to grant, parsed from
    # Shopify's error — not the raw GraphQL text.
    denied = _access_denied("Access denied for orders field. Required access: `read_orders` access scope.")
    valid, error = _validate(_post_returning({"orders": denied}), schema_name="orders")

    assert valid is False
    assert error is not None
    assert "orders" in error
    assert "read_orders" in error
    assert "Access denied for orders field" not in error


def test_throttle_is_not_reported_as_a_permission_error():
    # A throttle arrives as a 200 with an `errors` payload too; it must surface as the real
    # (retryable) rate-limit error, not be mislabeled as a missing permission.
    throttled = {"errors": [{"message": "Throttled", "extensions": {"code": "THROTTLED"}}]}
    valid, error = _validate(_post_returning({"orders": throttled}), schema_name="orders")

    assert valid is False
    assert error is not None
    assert "lacks permissions" not in error
    assert "rate limit" in error


def test_connect_is_not_blocked_by_a_missing_table_scope():
    # Connecting (no schema_name) only probes the token, so a missing scope on a table the user
    # may not sync — collections needing read_product_listings — must not block the whole source.
    denied = _access_denied(
        "Access denied for availablePublicationsCount field. Required access: `read_product_listings` access scope."
    )
    valid, error = _validate(_post_returning({"collections": denied}), schema_name=None)

    assert valid is True
    assert error is None


def test_endpoint_permissions_reports_each_table_without_blocking():
    # The schema picker probes each table independently: readable tables come back None and a
    # table missing a scope reports it, without failing the others.
    denied = _access_denied(
        "Access denied for availablePublicationsCount field. Required access: `read_product_listings` access scope."
    )
    result = _endpoint_permissions(_post_returning({"collections": denied}), ["orders", "products", "collections"])

    assert result["orders"] is None
    assert result["products"] is None
    assert result["collections"] is not None
    assert "read_product_listings" in result["collections"]


def test_endpoint_permissions_survive_a_throttle_on_one_table():
    # A throttle on one endpoint must not abort the batch — otherwise it raises out of the whole
    # probe and the view blanks every table's status. The genuine denial on another table must
    # still come through.
    throttled = {"errors": [{"message": "Throttled"}]}
    denied = _access_denied(
        "Access denied for availablePublicationsCount field. Required access: `read_product_listings` access scope."
    )
    result = _endpoint_permissions(
        _post_returning({"products": throttled, "collections": denied}),
        ["orders", "products", "collections"],
    )

    assert result["orders"] is None
    assert result["products"] is None
    assert "read_product_listings" in (result["collections"] or "")


def test_a_configured_access_token_authenticates_without_minting_one():
    # The store id and the access token reach `shopify.py` from different config fields, so a
    # token that is never threaded through would silently fall back to the minting path and fail
    # for the stores this option exists to serve.
    config = ShopifySourceConfig(
        shopify_store_id="my-store",
        auth_method=ShopifyAuthMethodConfig(selection="access_token", shopify_access_token="shpat_supplied"),
    )

    with scripted_network(_post_returning({})) as network:
        valid, error = ShopifySource().validate_credentials(config, team_id=1)

    assert (valid, error) == (True, None)
    assert all(request.path != TOKEN_PATH for request in network.requests_log)
    assert network.requests_log[0].headers["x-shopify-access-token"] == "shpat_supplied"


def _token_config() -> ShopifySourceConfig:
    return ShopifySourceConfig(
        shopify_store_id="my-store",
        auth_method=ShopifyAuthMethodConfig(selection="access_token", shopify_access_token="shpat_supplied"),
    )


@pytest.mark.parametrize(
    "config,response,expected_error",
    [
        (_token_config(), ScriptedResponse(status=401), SHOPIFY_ACCESS_TOKEN_REJECTED_ERROR),
        (_config(), ScriptedResponse(status=401), SHOPIFY_CREDENTIALS_CHECK_ERROR),
        (_token_config(), ScriptedResponse(status=402), SHOPIFY_STORE_FROZEN_ERROR),
        (_token_config(), ScriptedResponse(status=404), SHOPIFY_STORE_NOT_FOUND_ERROR),
        (_token_config(), ScriptedResponse(status=500), SHOPIFY_CREDENTIALS_CHECK_ERROR),
        (_token_config(), ScriptedResponse(json={"errors": "boom"}), SHOPIFY_CREDENTIALS_CHECK_ERROR),
    ],
)
def test_a_failed_token_check_shows_guidance_instead_of_the_raw_error(
    config: ShopifySourceConfig, response: ScriptedResponse, expected_error: str
):
    def script(request: RecordedRequest) -> ScriptedResponse:
        return TOKEN_RESPONSE if request.path == TOKEN_PATH else response

    with (
        scripted_network(script),
        mock.patch(f"{_SHOPIFY_MODULE}.capture_exception"),
    ):
        valid, error = ShopifySource().validate_credentials(config, team_id=1)

    assert (valid, error) == (False, expected_error)
