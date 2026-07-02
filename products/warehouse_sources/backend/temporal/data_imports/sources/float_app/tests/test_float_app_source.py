import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.float_app.float_app import FloatAppResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.float_app.settings import (
    ENDPOINTS,
    FLOAT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.float_app.source import FloatAppSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FloatAppSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

_CURSOR_ENDPOINTS = {"deleted_tasks", "deleted_timeoffs", "deleted_logged_time"}


class TestFloatAppSource:
    def setup_method(self):
        self.source = FloatAppSource()
        self.team_id = 123
        self.config = FloatAppSourceConfig(api_key="key")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.FLOATAPP

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "FloatApp"
        assert config.label == "Float"
        assert config.category == DataWarehouseSourceCategory.PRODUCTIVITY
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/float-app"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        api_key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True
        assert api_key_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.float.com/v3/people?per-page=200&page=1",
            "403 Client Error: Forbidden for url: https://api.float.com/v3/logged-time?per-page=200&page=1",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.float.com/v3/people",
            "500 Server Error: Internal Server Error for url: https://api.float.com/v3/people",
            "HTTPSConnectionPool(host='api.float.com', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        assert not any(key in other_error for key in self.source.get_non_retryable_errors())

    def test_get_schemas_are_all_full_refresh_with_mapped_primary_keys(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for name, schema in schemas.items():
            # Float exposes no server-side incremental filter, so every stream is full refresh.
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []
            assert schema.detected_primary_keys == FLOAT_ENDPOINTS[name].primary_keys

    def test_delete_log_endpoints_are_off_by_default(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        for name in _CURSOR_ENDPOINTS:
            assert schemas[name].should_sync_default is False
        assert schemas["people"].should_sync_default is True

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["people"])
        assert [s.name for s in schemas] == ["people"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_lists_tables_without_credentials_publishes_catalog(self):
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)
        # Full refresh is the only advertised sync method.
        assert all(table["sync_methods"] == ["Full refresh"] for table in documented)

    def test_canonical_descriptions_cover_every_endpoint(self):
        canonical = self.source.get_canonical_descriptions()
        assert set(canonical) == set(FLOAT_ENDPOINTS)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid Float access token"),
            ((False, 403), False, "Could not connect to Float with the provided access token"),
            ((False, None), False, "Could not connect to Float with the provided access token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.float_app.source.validate_float_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("key")

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert manager._data_class is FloatAppResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.float_app.source.float_app_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_float_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "people"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_float_source.assert_called_once()
        kwargs = mock_float_source.call_args.kwargs
        assert kwargs["api_key"] == "key"
        assert kwargs["endpoint"] == "people"
        assert kwargs["resumable_source_manager"] is manager
