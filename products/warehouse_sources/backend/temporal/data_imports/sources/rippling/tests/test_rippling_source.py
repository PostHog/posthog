import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RipplingSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.rippling.rippling import RipplingResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.rippling.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rippling.source import RipplingSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestRipplingSource:
    def setup_method(self):
        self.source = RipplingSource()
        self.team_id = 123
        self.config = RipplingSourceConfig(api_token="api-token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.RIPPLING

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Rippling"
        assert config.label == "Rippling"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/rippling.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_token"]

    def test_api_token_field_is_secret_password(self):
        config = self.source.get_source_config
        token_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_token")
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://rest.ripplingapis.com/workers?limit=100",
            "403 Client Error: Forbidden for url: https://rest.ripplingapis.com/compensations",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://rest.ripplingapis.com/workers",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # Every Rippling list endpoint supports the standard OData-style filter.
        assert all(schema.supports_incremental for schema in schemas)
        assert all(schema.supports_append for schema in schemas)

    def test_schemas_advertise_their_fields(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["workers"].incremental_fields == INCREMENTAL_FIELDS["workers"]
        assert {f["field"] for f in schemas["workers"].incremental_fields} == {"updated_at", "created_at"}

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["workers"])
        assert len(schemas) == 1
        assert schemas[0].name == "workers"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Rippling API token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.rippling.source.validate_rippling_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_token)

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is RipplingResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.rippling.source.rippling_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_rippling_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "workers"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-10-01T00:00:00"
        inputs.incremental_field = "updated_at"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_rippling_source.assert_called_once()
        kwargs = mock_rippling_source.call_args.kwargs
        assert kwargs["api_token"] == "api-token"
        assert kwargs["endpoint"] == "workers"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-10-01T00:00:00"
        assert kwargs["incremental_field"] == "updated_at"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.rippling.source.rippling_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_rippling_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "companies"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-10-01T00:00:00"
        inputs.incremental_field = None

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_rippling_source.call_args.kwargs["db_incremental_field_last_value"] is None
