import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.instantly import (
    InstantlySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.instantly.settings import WEBHOOK_EVENTS_ENDPOINT
from products.warehouse_sources.backend.temporal.data_imports.sources.instantly.source import InstantlySource


class TestInstantlySource:
    def setup_method(self):
        self.source = InstantlySource()
        self.team_id = 123
        self.config = InstantlySourceConfig(api_key="test-key")

    def test_get_schemas_webhook_events_is_webhook_only(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        webhook_schema = next(schema for schema in schemas if schema.name == WEBHOOK_EVENTS_ENDPOINT)

        assert webhook_schema.webhook_only is True
        assert webhook_schema.supports_webhooks is True
        assert not any(schema.supports_webhooks for schema in schemas if schema.name != WEBHOOK_EVENTS_ENDPOINT)

    def test_webhook_resource_map_routes_all_events_to_webhook_events(self):
        assert self.source.webhook_resource_map == {WEBHOOK_EVENTS_ENDPOINT: "event"}

    def test_webhook_template_present_with_required_inputs(self):
        template = self.source.webhook_template

        assert template is not None
        assert template.type == "warehouse_source_webhook"
        input_keys = {schema_input["key"] for schema_input in template.inputs_schema or []}
        assert {"signing_secret", "bypass_secret_check", "schema_mapping", "source_id"} <= input_keys

    def test_source_for_pipeline_rejects_unknown_schema(self):
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_real_table"

        with pytest.raises(ValueError, match="Unknown Instantly schema"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
