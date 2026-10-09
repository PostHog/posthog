from typing import Any

import pytest
from unittest import mock

import graphql
import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.queries.orders import (
    ORDERS_PROTECTED_FIELDS,
    ORDERS_QUERY,
    build_orders_query,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify import shopify_source
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.source import ShopifySource

_TOKEN_PATH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify._get_shopify_access_token"
)
_SESSION_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify.make_tracked_session"

_ALL_SCOPES = {scope for scopes in ORDERS_PROTECTED_FIELDS.values() for scope in scopes}


def _order_field_paths(query: str) -> set[str]:
    document = graphql.parse(query)
    paths: set[str] = set()

    def walk(selection_set: Any, prefix: str) -> None:
        for selection in selection_set.selections:
            if not isinstance(selection, graphql.FieldNode):
                continue
            name = selection.name.value
            # Connection wrappers add no meaning to the path, so `lineItems.nodes.product` reads as `lineItems.product`.
            path = prefix if name == "nodes" else f"{prefix}.{name}".lstrip(".")
            paths.add(path)
            if selection.selection_set is not None:
                walk(selection.selection_set, path)

    operation = document.definitions[0]
    assert isinstance(operation, graphql.OperationDefinitionNode)
    orders = operation.selection_set.selections[0]
    assert isinstance(orders, graphql.FieldNode) and orders.selection_set is not None
    walk(orders.selection_set, "")
    return paths


@parameterized.expand(
    [
        ("read_orders_only", {"read_orders"}, set()),
        ("read_customers", {"read_orders", "read_customers"}, {"customer"}),
        ("write_customers_implies_read", {"write_orders", "write_customers"}, {"customer"}),
        ("read_products", {"read_orders", "read_products"}, {"lineItems.product", "fulfillments.service"}),
        ("read_fulfillments", {"read_orders", "read_fulfillments"}, {"fulfillments.service"}),
        ("read_payment_terms", {"read_orders", "read_payment_terms"}, {"paymentTerms"}),
        *[
            (f"fulfillment_orders_{scope}", {"read_orders", scope}, {"fulfillmentOrders"})
            for scope in sorted(ORDERS_PROTECTED_FIELDS["fulfillmentOrders"])
        ],
    ]
)
def test_orders_query_selects_only_fields_the_scopes_can_read(
    _name: str, granted_scopes: set[str], expected_protected: set[str]
):
    # A selection the token can't read fails the whole page with "Access denied for <field>",
    # so a read_orders-only token must get none of them while the core order fields stay.
    paths = _order_field_paths(build_orders_query(granted_scopes))

    assert {field for field in ORDERS_PROTECTED_FIELDS if field in paths} == expected_protected
    assert {"id", "name", "lineItems.id", "lineItems.sku", "fulfillments.id", "totalPriceSet"} <= paths
    assert ("lineItems.variant" in paths) == ("lineItems.product" in paths)


def test_orders_query_includes_all_protected_fields_with_full_scopes():
    paths = _order_field_paths(ORDERS_QUERY)

    assert set(ORDERS_PROTECTED_FIELDS) <= paths
    assert {"lineItems.variant", "customer.defaultEmailAddress"} <= paths
    assert ORDERS_QUERY == build_orders_query(_ALL_SCOPES)


def _sync_orders(sess: mock.MagicMock) -> None:
    resumable = mock.MagicMock(can_resume=mock.MagicMock(return_value=False))
    with mock.patch(_TOKEN_PATH, return_value="tok"), mock.patch(_SESSION_PATH, return_value=sess):
        response = shopify_source(
            shopify_store_id="my-store",
            shopify_client_id="cid",
            shopify_client_secret="secret",
            graphql_object_name="orders",
            db_incremental_field_last_value=None,
            db_incremental_field_earliest_value=None,
            logger=mock.MagicMock(),
            resumable_source_manager=resumable,
            should_use_incremental_field=False,
        )
        list(response.items())


def test_scope_detection_failure_falls_back_to_minimal_query():
    # If the access-scopes lookup fails we must degrade to the minimal query, not attempt the full
    # one — otherwise a transient blip reintroduces the "Access denied" hard-fail this fix removes.
    captured: dict[str, str] = {}

    def post(_url: str, json: dict[str, Any] | None = None, **_kwargs: Any) -> mock.MagicMock:
        captured["query"] = (json or {}).get("query", "")
        response = mock.MagicMock(status_code=200)
        response.json.return_value = {"data": {"orders": {"nodes": [], "pageInfo": {"hasNextPage": False}}}}
        return response

    def get(_url: str, **_kwargs: Any) -> mock.MagicMock:
        raise requests.ConnectionError("scopes endpoint unreachable")

    _sync_orders(mock.MagicMock(post=mock.MagicMock(side_effect=post), get=mock.MagicMock(side_effect=get)))

    assert not set(ORDERS_PROTECTED_FIELDS) & _order_field_paths(captured["query"])


def test_access_denied_error_keeps_the_missing_scope_for_the_user():
    # The job error replaces matched non-retryable errors with fixed copy, so fixed copy here
    # would hide which scope the merchant has to grant.
    denial = "Access denied for customer field. Required access: `read_customers` access scope."
    response = mock.MagicMock(status_code=200)
    response.json.return_value = {"errors": [{"message": denial, "extensions": {"code": "ACCESS_DENIED"}}]}
    scopes = mock.MagicMock(status_code=200)
    scopes.json.return_value = {"access_scopes": [{"handle": "read_orders"}]}
    sess = mock.MagicMock(post=mock.MagicMock(return_value=response), get=mock.MagicMock(return_value=scopes))

    with pytest.raises(Exception) as exc_info:
        _sync_orders(sess)

    non_retryable = ShopifySource().get_non_retryable_errors()
    matched = [pattern for pattern in non_retryable if pattern in str(exc_info.value)]
    assert matched
    assert all(non_retryable[pattern] is None for pattern in matched)
    assert "`read_customers`" in str(exc_info.value)
