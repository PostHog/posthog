import graphql

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.shopify import (
    ShopifyAuthMethodConfig,
    ShopifySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.queries.orders import (
    ORDERS_PROTECTED_FIELDS,
    ORDERS_QUERY,
    build_orders_query,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shopify.source import ShopifySource

_ALL_SCOPES = {scope for scopes in ORDERS_PROTECTED_FIELDS.values() for scope in scopes}


def test_orders_query_omits_protected_fields_without_their_scopes():
    # The original bug: a read_orders-only token gets the full query, which reaches for
    # paymentTerms and hard-fails with "Access denied for <field>".
    query = build_orders_query({"read_orders"})

    assert "paymentTerms" not in query
    assert graphql.parse(query) is not None


def test_orders_query_includes_all_protected_fields_with_full_scopes():
    assert "paymentTerms" in ORDERS_QUERY
    assert ORDERS_QUERY == build_orders_query(_ALL_SCOPES)


def test_scope_detection_failure_falls_back_to_minimal_query():
    # If the access-scopes lookup fails we must degrade to the minimal query, not attempt the full
    # one — otherwise a transient blip reintroduces the "Access denied" hard-fail this fix removes.
    def script(request: RecordedRequest) -> ScriptedResponse:
        if request.path == "/admin/oauth/access_token":
            return ScriptedResponse(json={"access_token": "tok"})
        if request.method == "GET":
            raise ConnectionError("scopes endpoint unreachable")
        return ScriptedResponse(json={"data": {"orders": {"nodes": [], "pageInfo": {"hasNextPage": False}}}})

    config = ShopifySourceConfig(
        shopify_store_id="my-store",
        auth_method=ShopifyAuthMethodConfig(
            selection="client_credentials", shopify_client_id="cid", shopify_client_secret="secret"
        ),
    )

    result = SourceDriver(ShopifySource(), config).run("orders", script)

    assert result.raised is None
    queries = [request.json()["query"] for request in result.requests if request.path.endswith("/graphql.json")]
    assert queries
    assert "paymentTerms" not in queries[-1]
