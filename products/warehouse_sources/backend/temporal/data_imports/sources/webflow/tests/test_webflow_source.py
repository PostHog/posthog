from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.webflow import (
    WebflowSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.webflow.settings import STATIC_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.webflow.source import WebflowSource

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.webflow.source"


def _config() -> WebflowSourceConfig:
    return WebflowSource().parse_config({"api_token": "token", "site_id": "site-1"})


class TestWebflowSource:
    def test_409_conflict_message_is_recognised_as_non_retryable(self) -> None:
        # Webflow returns 409 on /products when the site has no ecommerce; the raised
        # HTTPError message embeds a volatile site id and URL, so we must match on a
        # stable substring that excludes them.
        errors = WebflowSource().get_non_retryable_errors()
        raised_message = (
            "409 Client Error: Conflict for url: "
            "https://api.webflow.com/v2/sites/691afa9e7404e1259a4d0802/products?limit=100&offset=0"
        )
        matches = [pattern for pattern in errors if pattern in raised_message]
        assert matches == ["409 Client Error: Conflict"]

    def test_deleted_collection_message_is_recognised_as_non_retryable(self) -> None:
        # _resolve_collection_id raises this when a collection's slug no longer resolves at sync
        # time; the message embeds a volatile schema name and site id, so we must match on a stable
        # substring that excludes them.
        errors = WebflowSource().get_non_retryable_errors()
        raised_message = "Webflow collection for schema 'collection_blog' was not found on site 'abc123'"
        matches = [pattern for pattern in errors if pattern in raised_message]
        assert matches == ["Webflow collection for schema"]

    def test_get_schemas_includes_static_and_dynamic_collections(self) -> None:
        with patch(
            f"{SOURCE_MODULE}.list_collections",
            return_value=[{"id": "c1", "slug": "blog", "displayName": "Blog"}, {"id": "c2", "slug": "authors"}],
        ):
            schemas = WebflowSource().get_schemas(_config(), team_id=1)

        names = {s.name for s in schemas}
        assert set(STATIC_ENDPOINTS).issubset(names)
        assert "collection_blog" in names
        assert "collection_authors" in names
        # No verified server-side range filter -> everything is full refresh.
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)

    def test_get_schemas_falls_back_to_static_when_discovery_fails(self) -> None:
        with patch(f"{SOURCE_MODULE}.list_collections", side_effect=Exception("no scope")):
            schemas = WebflowSource().get_schemas(_config(), team_id=1)

        assert {s.name for s in schemas} == set(STATIC_ENDPOINTS)

    def test_get_schemas_filters_by_names(self) -> None:
        with patch(
            f"{SOURCE_MODULE}.list_collections", return_value=[{"id": "c1", "slug": "blog", "displayName": "Blog"}]
        ):
            schemas = WebflowSource().get_schemas(_config(), team_id=1, names=["sites", "collection_blog"])

        assert {s.name for s in schemas} == {"sites", "collection_blog"}


class TestWebflowWebhookSupport:
    def test_only_orders_is_offered_as_a_webhook_table(self) -> None:
        # Every other Webflow trigger either describes a resource we don't sync (form_submission
        # carries a submission, our forms table carries form definitions) or renames the object's
        # fields (page_created sends pageId/pageTitle where the Pages API sends id/title), so
        # marking one webhook-capable would merge mismatched rows into the polled table.
        with patch(f"{SOURCE_MODULE}.list_collections", return_value=[{"id": "c1", "slug": "blog"}]):
            schemas = WebflowSource().get_schemas(_config(), team_id=1)

        assert {s.name for s in schemas if s.supports_webhooks} == {"orders"}

    def test_webhook_resource_map_keys_are_real_schema_names(self) -> None:
        # The resource map is what builds schema_mapping; a key that isn't a schema name means
        # deliveries route to nothing and are dropped with a 200.
        source = WebflowSource()
        with patch(f"{SOURCE_MODULE}.list_collections", return_value=[]):
            schema_names = {s.name for s in source.get_schemas(_config(), team_id=1)}

        assert set(source.webhook_resource_map) <= schema_names
        # The Hog template collapses trigger types down to the schema name before the lookup.
        assert source.webhook_resource_map == {"orders": "orders"}
        assert source.webhook_mapping_key("orders") == "orders"

    def test_webhook_template_is_wired_for_this_source(self) -> None:
        template = WebflowSource().webhook_template
        assert template is not None
        assert template.id == "template-warehouse-source-webflow"
        assert template.type == "warehouse_source_webhook"

    @parameterized.expand(
        [
            ("eligible", ["orders"], ["ecomm_new_order", "ecomm_order_changed"]),
            ("not_eligible", ["pages", "forms"], []),
            ("mixed", ["orders", "pages"], ["ecomm_new_order", "ecomm_order_changed"]),
        ]
    )
    def test_desired_events_follow_the_enabled_tables(
        self, _name: str, enabled: list[str], expected: list[str]
    ) -> None:
        assert WebflowSource().get_desired_webhook_events(_config(), enabled) == expected

    @parameterized.expand(
        [
            ("create", "create_webflow_webhook", "create_webhook"),
            ("delete", "delete_webflow_webhook", "delete_webhook"),
            ("info", "get_webflow_webhook_info", "get_external_webhook_info"),
        ]
    )
    def test_webhook_management_uses_the_configured_site_and_token(self, _name: str, patched: str, method: str) -> None:
        # Webflow webhooks are site-scoped; calling with the wrong site would register or delete
        # a webhook on a different site the token can reach.
        with patch(f"{SOURCE_MODULE}.{patched}") as mock_call:
            getattr(WebflowSource(), method)(_config(), "https://webhooks.example/dwh/1", team_id=1)

        mock_call.assert_called_once_with("token", "site-1", "https://webhooks.example/dwh/1")
