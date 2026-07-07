import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GoCardlessSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gocardless.gocardless import (
    GoCardlessResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gocardless.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gocardless.source import GoCardlessSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestGoCardlessSource:
    def setup_method(self):
        self.source = GoCardlessSource()
        self.team_id = 123
        self.config = GoCardlessSourceConfig(environment="live", access_token="access-token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.GOCARDLESS

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "GoCardless"
        assert config.label == "GoCardless"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/gocardless.png"

        field_names = [f.name for f in config.fields]
        assert field_names == ["environment", "access_token"]

    def test_environment_field_is_a_select_with_default(self):
        config = self.source.get_source_config
        env_field = next(f for f in config.fields if f.name == "environment")
        assert isinstance(env_field, SourceFieldSelectConfig)
        assert env_field.defaultValue == "live"
        assert {option.value for option in env_field.options} == {"live", "sandbox"}

    def test_access_token_field_is_secret_password(self):
        config = self.source.get_source_config
        token_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "access_token"
        )
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.gocardless.com/customers?limit=500",
            "401 Client Error: Unauthorized for url: https://api-sandbox.gocardless.com/payments",
            "403 Client Error: Forbidden for url: https://api.gocardless.com/events",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.gocardless.com/payments",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only the append-only events change log has an honest incremental;
        # mutable tables (payments, mandates) change status after creation.
        assert incremental == {"events"}

    def test_incremental_schemas_advertise_their_fields(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["events"].incremental_fields == INCREMENTAL_FIELDS["events"]
        assert schemas["payments"].incremental_fields == []
        assert schemas["payments"].supports_append is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["events"])
        assert len(schemas) == 1
        assert schemas[0].name == "events"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid GoCardless access token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.gocardless.source.validate_gocardless_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("live", "access-token")

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is GoCardlessResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.gocardless.source.gocardless_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_gc_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "events"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05.000Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_gc_source.assert_called_once()
        kwargs = mock_gc_source.call_args.kwargs
        assert kwargs["environment"] == "live"
        assert kwargs["access_token"] == "access-token"
        assert kwargs["endpoint"] == "events"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-02T03:04:05.000Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.gocardless.source.gocardless_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_gc_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "payments"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05.000Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_gc_source.call_args.kwargs["db_incremental_field_last_value"] is None
