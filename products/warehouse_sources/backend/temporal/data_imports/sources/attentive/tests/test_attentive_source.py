from collections.abc import Iterable
from typing import Any, cast

from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.attentive.constants import (
    ATTENTIVE_WEBHOOK_SCHEMA_NAMES,
    RESOURCE_TO_ATTENTIVE_EVENT_TYPE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.attentive.source import (
    AttentiveSource,
    _webhook_table_transformer,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.attentive import (
    AttentiveSourceConfig,
)


class TestWebhookTableTransformer:
    def test_adds_stable_event_id_and_created_at(self):
        row = {"type": "sms.sent", "timestamp": 1632945178104, "subscriber": {"phone": "+15555555555"}}
        table = table_from_py_list([row])

        result = _webhook_table_transformer(table).to_pylist()

        assert len(result) == 1
        assert result[0]["created_at"] == 1632945178
        assert result[0]["event_id"]
        # Identical retried deliveries hash to the same event_id.
        rerun = _webhook_table_transformer(table_from_py_list([row])).to_pylist()
        assert rerun[0]["event_id"] == result[0]["event_id"]

    def test_different_payloads_get_different_event_ids(self):
        rows = [
            {"type": "sms.sent", "timestamp": 1632945178104},
            {"type": "sms.sent", "timestamp": 1632945178105},
        ]
        result = _webhook_table_transformer(table_from_py_list(rows)).to_pylist()
        assert result[0]["event_id"] != result[1]["event_id"]

    def test_missing_timestamp_omits_created_at(self):
        result = _webhook_table_transformer(table_from_py_list([{"type": "sms.sent"}])).to_pylist()
        assert result[0].get("created_at") is None


class TestAttentiveSource:
    def setup_method(self):
        self.source = AttentiveSource()
        self.team_id = 123
        self.config = AttentiveSourceConfig(api_key="key")

    def test_webhook_template_registered(self):
        template = self.source.webhook_template
        assert template is not None
        assert template.id == "template-warehouse-source-attentive"
        assert template.type == "warehouse_source_webhook"

    def test_webhook_resource_map(self):
        assert self.source.webhook_resource_map == RESOURCE_TO_ATTENTIVE_EVENT_TYPE

    def test_get_schemas_are_webhook_only(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ATTENTIVE_WEBHOOK_SCHEMA_NAMES)
        assert all(schema.supports_webhooks for schema in schemas)
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["sms_sent"])
        assert len(schemas) == 1
        assert schemas[0].name == "sms_sent"

    def test_get_desired_webhook_events_maps_eligible_schemas(self):
        events = self.source.get_desired_webhook_events(self.config, ["sms_sent", "email_opened", "not_a_schema"])
        assert events == ["sms.sent", "email.opened"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.attentive.source.api_client.create_webhook"
    )
    def test_create_webhook_subscribes_all_event_types(self, mock_create):
        self.source.create_webhook(self.config, "https://ph.example/webhook", self.team_id)

        mock_create.assert_called_once_with(
            api_key="key",
            webhook_url="https://ph.example/webhook",
            resource_names=list(RESOURCE_TO_ATTENTIVE_EVENT_TYPE.keys()),
        )

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.attentive.source.api_client.enable_webhook"
    )
    def test_webhook_inputs_updated_enables_once_secret_provided(self, mock_enable):
        mock_enable.return_value = (True, None)

        ok, _ = self.source.webhook_inputs_updated(
            self.config, "https://ph.example/webhook", self.team_id, {"signing_secret": "sek"}
        )

        assert ok is True
        mock_enable.assert_called_once_with("key", "https://ph.example/webhook")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.attentive.source.api_client.enable_webhook"
    )
    def test_webhook_inputs_updated_noop_without_secret(self, mock_enable):
        ok, _ = self.source.webhook_inputs_updated(self.config, "https://ph.example/webhook", self.team_id, {})

        assert ok is True
        mock_enable.assert_not_called()

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.attentive.source.async_to_sync")
    def test_source_for_pipeline_metadata(self, mock_async_to_sync):
        mock_async_to_sync.return_value = mock.MagicMock(return_value=False)
        inputs = mock.MagicMock()
        inputs.schema_name = "sms_sent"

        response = self.source.source_for_pipeline(self.config, inputs)

        assert response.name == "sms_sent"
        assert response.primary_keys == ["event_id"]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "week"
        assert response.partition_keys == ["created_at"]
        # Webhook disabled -> empty iterator.
        assert list(cast(Iterable[Any], response.items())) == []
