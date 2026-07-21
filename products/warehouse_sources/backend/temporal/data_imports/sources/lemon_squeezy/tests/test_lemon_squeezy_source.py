import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lemonsqueezy import (
    LemonSqueezySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lemon_squeezy.lemon_squeezy import (
    LemonSqueezyResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lemon_squeezy.settings import (
    ENDPOINTS,
    INCREMENTAL_ENDPOINTS,
    INCREMENTAL_FIELDS,
    SCHEMA_TO_WEBHOOK_EVENTS,
    WEBHOOK_SCHEMA_NAMES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lemon_squeezy.source import LemonSqueezySource
from products.warehouse_sources.backend.types import ExternalDataSourceType

API_CLIENT_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.lemon_squeezy.source.api_client"


class TestLemonSqueezySource:
    def setup_method(self):
        self.source = LemonSqueezySource()
        self.team_id = 123
        self.config = LemonSqueezySourceConfig(api_key="test-api-key")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.LEMONSQUEEZY

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "LemonSqueezy"
        assert config.label == "Lemon Squeezy"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # The source must ship visible: unreleasedSource hides it from every user.
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/lemon-squeezy"

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_webhook_fields_include_signing_secret(self):
        config = self.source.get_source_config
        assert config.webhookFields is not None
        field = next(
            f for f in config.webhookFields if isinstance(f, SourceFieldInputConfig) and f.name == "signing_secret"
        )
        assert field.secret is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.lemonsqueezy.com/v1/orders?page%5Bsize%5D=100",
            "403 Client Error: Forbidden for url: https://api.lemonsqueezy.com/v1/stores",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.lemonsqueezy.com/v1/orders",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error):
        assert not any(key in other_error for key in self.source.get_non_retryable_errors())

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only append-mostly endpoints get the stop-early created_at cursor; mutable
        # resources stay full refresh so in-place updates aren't silently missed.
        assert incremental == set(INCREMENTAL_ENDPOINTS)

    def test_incremental_schemas_are_merge_only(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        for name in INCREMENTAL_ENDPOINTS:
            # The stop-early cursor re-yields watermark boundary rows, which only merge dedupes.
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == INCREMENTAL_FIELDS[name]

    def test_webhook_capable_schemas(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        webhook_capable = {name for name, schema in schemas.items() if schema.supports_webhooks}
        assert webhook_capable == set(WEBHOOK_SCHEMA_NAMES)
        assert all(not schema.webhook_only for schema in schemas.values())

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["orders"])
        assert [schema.name for schema in schemas] == ["orders"]

    @pytest.mark.parametrize("mock_return, expected_valid", [(True, True), (False, False)])
    @mock.patch(f"{API_CLIENT_PATCH}.validate_credentials")
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert (error_message is None) is expected_valid
        mock_validate.assert_called_once_with("test-api-key")

    def test_get_resumable_source_manager_binds_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is LemonSqueezyResumeConfig

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
