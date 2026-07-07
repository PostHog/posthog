from typing import Any

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

_TOKEN_PATH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify._get_shopify_access_token"
)
_SESSION_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.shopify.shopify.make_tracked_session"

_ALL_SCOPES = {scope for scopes in ORDERS_PROTECTED_FIELDS.values() for scope in scopes}


def test_orders_query_omits_protected_fields_without_their_scopes():
    # The original bug: a read_orders-only token gets the full query, which reaches for
    # fulfillmentOrders/paymentTerms and hard-fails with "Access denied for <field>".
    query = build_orders_query({"read_orders"})

    assert "fulfillmentOrders" not in query
    assert "paymentTerms" not in query
    assert graphql.parse(query) is not None


@parameterized.expand(sorted(ORDERS_PROTECTED_FIELDS["fulfillmentOrders"]))
def test_any_fulfillment_scope_alone_includes_fulfillment_orders(scope: str):
    # Shopify exposes fulfillmentOrders under any of three scopes; granting just one must unlock it.
    query = build_orders_query({scope})

    assert "fulfillmentOrders" in query
    assert "paymentTerms" not in query


def test_orders_query_includes_all_protected_fields_with_full_scopes():
    assert "fulfillmentOrders" in ORDERS_QUERY
    assert "paymentTerms" in ORDERS_QUERY
    assert ORDERS_QUERY == build_orders_query(_ALL_SCOPES)


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

    sess = mock.MagicMock(post=mock.MagicMock(side_effect=post), get=mock.MagicMock(side_effect=get))
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

    assert "fulfillmentOrders" not in captured["query"]
    assert "paymentTerms" not in captured["query"]
