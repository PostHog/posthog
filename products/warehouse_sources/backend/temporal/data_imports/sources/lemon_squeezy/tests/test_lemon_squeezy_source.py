import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lemonsqueezy import (
    LemonSqueezySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lemon_squeezy.settings import (
    SCHEMA_TO_WEBHOOK_EVENTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lemon_squeezy.source import LemonSqueezySource

API_CLIENT_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.lemon_squeezy.source.api_client"


class TestLemonSqueezySource:
    def setup_method(self):
        self.source = LemonSqueezySource()
        self.team_id = 123
        self.config = LemonSqueezySourceConfig(api_key="test-api-key")

    @pytest.mark.parametrize("mock_return, expected_valid", [(True, True), (False, False)])
    @mock.patch(f"{API_CLIENT_PATCH}.validate_credentials")
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert (error_message is None) is expected_valid
        mock_validate.assert_called_once_with("test-api-key")

    @mock.patch(f"{API_CLIENT_PATCH}.lemon_squeezy_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "orders"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-05-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "test-api-key"
        assert kwargs["endpoint"] == "orders"
        assert kwargs["team_id"] is inputs.team_id
        assert kwargs["job_id"] is inputs.job_id
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["webhook_source_manager"] is not None
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-05-01T00:00:00Z"

    @mock.patch(f"{API_CLIENT_PATCH}.lemon_squeezy_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "stores"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-05-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

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
