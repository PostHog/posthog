import pytest
from unittest import mock

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import LeverSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.lever.lever import LeverResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.lever.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.lever.source import LeverSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

INCREMENTAL_ENDPOINTS = {"opportunities"}


class TestLeverSource:
    def setup_method(self):
        self.source = LeverSource()
        self.team_id = 123
        self.config = LeverSourceConfig(api_key="test_api_key")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.LEVER

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Lever"
        assert config.label == "Lever"
        assert config.releaseStatus == "alpha"
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/lever.png"
        assert len(config.fields) == 1

        api_key_field = config.fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True
        assert api_key_field.secret is True

    @pytest.mark.parametrize(
        "expected_key",
        [
            "401 Client Error: Unauthorized for url: https://api.lever.co",
            "403 Client Error: Forbidden for url: https://api.lever.co",
        ],
    )
    def test_non_retryable_errors_includes_lever_key(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_non_retryable_errors_matches_observed_error_message(self):
        observed_error = "401 Client Error: Unauthorized for url: https://api.lever.co/v1/opportunities?limit=100"
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "401 Client Error: Unauthorized for url: https://api.clerk.com/v1/users",
        ],
    )
    def test_non_retryable_errors_does_not_match_other_vendors(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_get_schemas_only_opportunities_is_incremental(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        appendable = {schema.name for schema in schemas if schema.supports_append}

        assert incremental == INCREMENTAL_ENDPOINTS
        assert appendable == INCREMENTAL_ENDPOINTS

    def test_opportunities_advertises_created_and_updated_cursors(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["opportunities"])
        assert len(schemas) == 1

        fields = {field["field"] for field in schemas[0].incremental_fields}
        assert fields == {"createdAt", "updatedAt"}

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["users"])
        assert len(schemas) == 1
        assert schemas[0].name == "users"
        assert schemas[0].supports_incremental is False

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_error",
        [
            ((True, None), True, None),
            (
                (False, "Invalid Lever API key. Please check your key and try again."),
                False,
                "Invalid Lever API key. Please check your key and try again.",
            ),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.lever.source.validate_lever_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_error):
        mock_validate.return_value = mock_return

        is_valid, error = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error == expected_error
        mock_validate.assert_called_once_with(self.config.api_key)

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is LeverResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.lever.source.lever_source")
    def test_source_for_pipeline_passes_incremental_inputs(self, mock_lever_source):
        manager = mock.MagicMock()
        inputs = mock.MagicMock()
        inputs.schema_name = "opportunities"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1700000000
        inputs.incremental_field = "updatedAt"

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_lever_source.assert_called_once()
        kwargs = mock_lever_source.call_args.kwargs
        assert kwargs["api_key"] == "test_api_key"
        assert kwargs["endpoint"] == "opportunities"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1700000000
        assert kwargs["incremental_field"] == "updatedAt"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.lever.source.lever_source")
    def test_source_for_pipeline_drops_last_value_when_not_incremental(self, mock_lever_source):
        manager = mock.MagicMock()
        inputs = mock.MagicMock()
        inputs.schema_name = "users"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = 1700000000
        inputs.incremental_field = None

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_lever_source.call_args.kwargs
        assert kwargs["should_use_incremental_field"] is False
        assert kwargs["db_incremental_field_last_value"] is None
