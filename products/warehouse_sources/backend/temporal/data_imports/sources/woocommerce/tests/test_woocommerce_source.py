from typing import Optional

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.woocommerce import (
    WooCommerceSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PARTITION_FIELDS,
    SCHEMA_TO_WEBHOOK_RESOURCE,
    WEBHOOK_SCHEMA_NAMES,
    WEBHOOK_TOPICS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.source import WooCommerceSource

INCREMENTAL_ENDPOINTS = set(INCREMENTAL_FIELDS.keys())


def _make_inputs(schema_name: str, should_use_incremental_field: bool = False, last_value: object = None):
    return mock.MagicMock(
        schema_name=schema_name,
        team_id=123,
        job_id="job-1",
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=last_value,
    )


@pytest.fixture(autouse=True)
def webhook_disabled():
    """Default every test to the polling path.

    `webhook_enabled` reads the schema row out of Postgres to decide whether the table has been
    switched to webhook sync; tests that care about that branch re-patch it themselves.
    """
    with mock.patch.object(WebhookSourceManager, "webhook_enabled", new=mock.AsyncMock(return_value=False)) as patched:
        yield patched


class TestWooCommerceSource:
    def setup_method(self):
        self.source = WooCommerceSource()
        self.team_id = 123
        self.config = WooCommerceSourceConfig(
            store_url="https://example.com",
            consumer_key="ck_test",
            consumer_secret="cs_test",
        )

    @pytest.mark.parametrize(
        "status, schema_name, expected_valid",
        [
            (200, None, True),
            (200, "orders", True),
            (401, None, False),
            (403, None, True),  # valid key without scope for the probe endpoint -> allowed at create
            (403, "orders", False),  # but rejected for a specific schema check
            (404, None, False),
            (None, None, False),  # connection error
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.source.validate_woocommerce_credentials"
    )
    def test_validate_credentials(self, mock_validate, status, schema_name, expected_valid):
        mock_validate.return_value = status

        is_valid, _ = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)

        assert is_valid is expected_valid
        mock_validate.assert_called_once_with("https://example.com", "ck_test", "cs_test", self.team_id)

    def test_validate_credentials_missing_fields(self):
        config = WooCommerceSourceConfig(store_url="", consumer_key="", consumer_secret="")
        is_valid, message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert message == "Missing WooCommerce credentials"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.source.woocommerce_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_source):
        mock_resource = mock.MagicMock(name="orders", column_hints=None)
        mock_source.return_value = mock_resource
        manager = mock.MagicMock(spec=ResumableSourceManager)
        inputs = _make_inputs("orders", should_use_incremental_field=True, last_value="2024-01-01T00:00:00")

        response = self.source.source_for_pipeline(self.config, manager, inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["store_url"] == "https://example.com"
        assert kwargs["consumer_key"] == "ck_test"
        assert kwargs["consumer_secret"] == "cs_test"
        assert kwargs["endpoint"] == "orders"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-01T00:00:00"
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "desc"

    def test_source_for_pipeline_full_refresh_drops_last_value(self):
        manager = mock.MagicMock(spec=ResumableSourceManager)
        inputs = _make_inputs("customers", should_use_incremental_field=False, last_value="2024-01-01T00:00:00")

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.source.woocommerce_source"
        ) as mock_source:
            mock_source.return_value = mock.MagicMock(name="customers", column_hints=None)
            response = self.source.source_for_pipeline(self.config, manager, inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["db_incremental_field_last_value"] is None
        assert response.sort_mode == "asc"

    def test_source_for_pipeline_ignores_incremental_for_non_incremental_endpoint(self):
        # A non-incremental endpoint must stay full refresh even if the flag is set, so it
        # doesn't advertise desc semantics or carry a cursor value it can't honor.
        manager = mock.MagicMock(spec=ResumableSourceManager)
        inputs = _make_inputs("customers", should_use_incremental_field=True, last_value="2024-01-01T00:00:00")

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.source.woocommerce_source"
        ) as mock_source:
            mock_source.return_value = mock.MagicMock(name="customers", column_hints=None)
            response = self.source.source_for_pipeline(self.config, manager, inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["should_use_incremental_field"] is False
        assert kwargs["db_incremental_field_last_value"] is None
        assert response.sort_mode == "asc"

    @pytest.mark.parametrize("endpoint", sorted(ENDPOINTS))
    def test_source_for_pipeline_partitioning(self, endpoint):
        manager = mock.MagicMock(spec=ResumableSourceManager)
        inputs = _make_inputs(endpoint)

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.source.woocommerce_source"
        ) as mock_source:
            mock_source.return_value = mock.MagicMock(name=endpoint, column_hints=None)
            response = self.source.source_for_pipeline(self.config, manager, inputs)

        expected_key: Optional[str] = PARTITION_FIELDS.get(endpoint)
        if expected_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [expected_key]
        else:
            assert response.partition_keys is None

    def test_get_schemas_marks_only_webhook_capable_tables(self):
        # WooCommerce only ships core webhook topics for four resources. Marking any other table
        # would let setup switch it to webhook sync, which stops polling it for rows that can
        # never arrive.
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        assert {name for name, s in schemas.items() if s.supports_webhooks} == set(WEBHOOK_SCHEMA_NAMES)

    def test_webhook_resource_map_covers_every_webhook_capable_schema(self):
        # The map is what routes an incoming delivery to a table; a schema missing from it is a
        # table that silently receives nothing.
        assert set(self.source.webhook_resource_map) == set(WEBHOOK_SCHEMA_NAMES)
        assert {f"{resource}.created" for resource in self.source.webhook_resource_map.values()} <= set(WEBHOOK_TOPICS)

    def test_webhook_template_verifies_the_woocommerce_signature_header(self):
        template = self.source.webhook_template

        assert template is not None
        assert template.type == "warehouse_source_webhook"
        assert "x-wc-webhook-signature" in template.code
        assert {field["key"] for field in template.inputs_schema} >= {"signing_secret", "schema_mapping", "source_id"}

    @pytest.mark.parametrize(
        "method_name, transport_name",
        [
            ("create_webhook", "create_woocommerce_webhook"),
            ("delete_webhook", "delete_woocommerce_webhook"),
            ("get_external_webhook_info", "get_woocommerce_webhook_info"),
        ],
    )
    def test_webhook_management_passes_the_store_credentials_through(self, method_name, transport_name):
        # The store URL and the key/secret pair are positional; swapping two of them would send
        # the consumer key as the secret and 401 on every store.
        with mock.patch(
            f"products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.source.{transport_name}"
        ) as mock_transport:
            getattr(self.source, method_name)(self.config, "https://ph.test/hook", self.team_id)

        mock_transport.assert_called_once_with(
            "https://example.com", "ck_test", "cs_test", self.team_id, "https://ph.test/hook"
        )

    def test_source_for_pipeline_keeps_polling_while_webhooks_are_not_active(self, webhook_disabled):
        manager = mock.MagicMock(spec=ResumableSourceManager)

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.source.woocommerce_source"
        ) as mock_source:
            resource = mock.MagicMock(name="orders", column_hints=None)
            mock_source.return_value = resource
            response = self.source.source_for_pipeline(self.config, manager, _make_inputs("orders"))

        assert response.items() is resource

    def test_source_for_pipeline_reads_pushed_rows_once_webhooks_are_active(self, webhook_disabled):
        # Once the schema is on webhook sync and its backfill has completed, the sync has to drain
        # the buffered deliveries instead of re-walking the REST API.
        webhook_disabled.return_value = True
        manager = mock.MagicMock(spec=ResumableSourceManager)

        with (
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.source.woocommerce_source"
            ) as mock_source,
            mock.patch.object(WebhookSourceManager, "get_items") as mock_get_items,
        ):
            mock_source.return_value = mock.MagicMock(name="orders", column_hints=None)
            response = self.source.source_for_pipeline(self.config, manager, _make_inputs("orders"))
            items = response.items()

        assert items is mock_get_items.return_value
        # Delta merge only dedupes across syncs, so the within-batch transformer must be wired up.
        assert mock_get_items.call_args.kwargs["table_transformer"] is not None

    def test_source_for_pipeline_never_consults_webhooks_for_a_polling_only_table(self, webhook_disabled):
        manager = mock.MagicMock(spec=ResumableSourceManager)

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.source.woocommerce_source"
        ) as mock_source:
            mock_source.return_value = mock.MagicMock(name="tax_rates", column_hints=None)
            self.source.source_for_pipeline(self.config, manager, _make_inputs("tax_rates"))

        webhook_disabled.assert_not_awaited()

    def test_webhook_resources_are_distinct(self):
        # Two schemas sharing a resource key would collide in `schema_mapping` and one table
        # would stop receiving deliveries entirely.
        assert len(set(SCHEMA_TO_WEBHOOK_RESOURCE.values())) == len(SCHEMA_TO_WEBHOOK_RESOURCE)
