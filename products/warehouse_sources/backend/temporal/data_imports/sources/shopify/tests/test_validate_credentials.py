from typing import Any

from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ShopifySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.source import ShopifySource

_TOKEN_PATH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify._get_shopify_access_token"
)
_SESSION_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify.make_tracked_session"


def _access_denied(message: str) -> dict[str, Any]:
    return {"errors": [{"message": message, "extensions": {"code": "ACCESS_DENIED"}}]}


def _post_returning(deny_if_query_contains: dict[str, dict[str, Any]]):
    """A fake `sess.post` that returns Shopify-shaped JSON keyed on the GraphQL query text.

    Each key is a substring of a probe query; when a request's query contains it, the mapped
    payload is returned (e.g. an access-denied or throttled body). Anything else — including the
    `{ shop { id } }` token check and the `id` probes — comes back clean.
    """

    def post(_url: str, json: dict[str, Any] | None = None, **_kwargs: Any) -> mock.MagicMock:
        query = (json or {}).get("query", "")
        payload: dict[str, Any] = {"data": {}}
        for needle, denied_payload in deny_if_query_contains.items():
            if needle in query:
                payload = denied_payload
                break
        response = mock.MagicMock()
        response.json.return_value = payload
        return response

    return post


def _config() -> ShopifySourceConfig:
    return ShopifySourceConfig(shopify_store_id="my-store", shopify_client_id="cid", shopify_client_secret="secret")


def _patches(post):
    return (
        mock.patch(_TOKEN_PATH, return_value="tok"),
        mock.patch(_SESSION_PATH, return_value=mock.MagicMock(post=mock.MagicMock(side_effect=post))),
    )


def _validate(post, schema_name: str | None = None) -> tuple[bool, str | None]:
    token_patch, session_patch = _patches(post)
    with token_patch, session_patch:
        return ShopifySource().validate_credentials(_config(), team_id=1, schema_name=schema_name)


def _endpoint_permissions(post, endpoints: list[str]) -> dict[str, str | None]:
    token_patch, session_patch = _patches(post)
    with token_patch, session_patch:
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
