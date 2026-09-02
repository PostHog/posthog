from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.webflow import (
    WebflowSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.webflow.settings import STATIC_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.webflow.source import WebflowSource

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.webflow.source"


def _config() -> WebflowSourceConfig:
    return WebflowSource().parse_config({"api_token": "token", "site_id": "site-1"})


def _inputs(schema_name: str = "pages") -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-1",
        source_id="source-1",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-1",
        logger=MagicMock(),
        reset_pipeline=False,
    )


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

    def test_406_not_acceptable_message_is_recognised_as_non_retryable(self) -> None:
        # Webflow returns 406 deterministically for a given site/token when listing CMS
        # collections; the raised HTTPError message embeds a volatile site id and URL, so we
        # must match on a stable substring that excludes them.
        errors = WebflowSource().get_non_retryable_errors()
        raised_message = (
            "406 Client Error: Not Acceptable for url: "
            "https://api.webflow.com/v2/sites/64cd40ea6c8cca864c510895/collections"
        )
        matches = [pattern for pattern in errors if pattern in raised_message]
        assert matches == ["406 Client Error"]

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

    def test_source_for_pipeline_plumbs_through(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        inputs = _inputs(schema_name="collection_blog")
        with patch(f"{SOURCE_MODULE}.webflow_source") as mock_source:
            WebflowSource().source_for_pipeline(_config(), manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_token"] == "token"
        assert kwargs["site_id"] == "site-1"
        assert kwargs["schema_name"] == "collection_blog"
        assert kwargs["team_id"] == inputs.team_id
        assert kwargs["job_id"] == inputs.job_id
        assert kwargs["resumable_source_manager"] is manager
        # Backfill and pushed rows have to reach the same sync, so the webhook manager is
        # always handed over; the transport decides whether the schema can use it.
        assert isinstance(kwargs["webhook_source_manager"], WebhookSourceManager)


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
