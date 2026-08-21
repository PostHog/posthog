import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lemonsqueezy import (
    LemonSqueezySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lemon_squeezy.settings import (
    SCHEMA_TO_WEBHOOK_EVENTS,
    WEBHOOK_SCHEMA_NAMES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lemon_squeezy.source import LemonSqueezySource

API_CLIENT_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.lemon_squeezy.source.api_client"


class TestLemonSqueezySource:
    def setup_method(self):
        self.source = LemonSqueezySource()
        self.team_id = 123
        self.config = LemonSqueezySourceConfig(api_key="test-api-key")

    def test_webhook_capable_schemas(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        webhook_capable = {name for name, schema in schemas.items() if schema.supports_webhooks}
        assert webhook_capable == set(WEBHOOK_SCHEMA_NAMES)
        assert all(not schema.webhook_only for schema in schemas.values())

    @pytest.mark.parametrize("mock_return, expected_valid", [(True, True), (False, False)])
    @mock.patch(f"{API_CLIENT_PATCH}.validate_credentials")
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert (error_message is None) is expected_valid
        mock_validate.assert_called_once_with("test-api-key")

    def test_webhook_resource_map_routes_by_json_api_type(self):
        assert self.source.webhook_resource_map == {
            "orders": "orders",
            "subscriptions": "subscriptions",
            "subscription_invoices": "subscription-invoices",
            "license_keys": "license-keys",
        }

    def test_webhook_template_routes_on_schema_mapping(self):
        template = self.source.webhook_template
        assert template is not None
        assert template.type == "warehouse_source_webhook"
        input_keys = {input_schema["key"] for input_schema in template.inputs_schema}
        assert {"signing_secret", "schema_mapping", "source_id"} <= input_keys

    def test_get_desired_webhook_events_covers_eligible_schemas_only(self):
        events = self.source.get_desired_webhook_events(self.config, ["orders", "license_keys"])
        assert events == sorted(SCHEMA_TO_WEBHOOK_EVENTS["orders"] + SCHEMA_TO_WEBHOOK_EVENTS["license_keys"])

    @mock.patch(f"{API_CLIENT_PATCH}.create_webhook")
    def test_create_webhook_delegates(self, mock_create):
        self.source.create_webhook(self.config, "https://us.posthog.com/webhooks/abc", self.team_id)
        mock_create.assert_called_once_with("test-api-key", "https://us.posthog.com/webhooks/abc")

    @mock.patch(f"{API_CLIENT_PATCH}.delete_webhook")
    def test_delete_webhook_delegates(self, mock_delete):
        self.source.delete_webhook(self.config, "https://us.posthog.com/webhooks/abc", self.team_id)
        mock_delete.assert_called_once_with("test-api-key", "https://us.posthog.com/webhooks/abc")

    @mock.patch(f"{API_CLIENT_PATCH}.sync_webhook_events")
    def test_sync_webhook_events_passes_desired_events(self, mock_sync):
        self.source.sync_webhook_events(self.config, "https://us.posthog.com/webhooks/abc", self.team_id, ["orders"])
        mock_sync.assert_called_once_with(
            "test-api-key", "https://us.posthog.com/webhooks/abc", sorted(SCHEMA_TO_WEBHOOK_EVENTS["orders"])
        )
