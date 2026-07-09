import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SmartwaiverSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.smartwaiver.settings import (
    ENDPOINTS,
    SMARTWAIVER_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartwaiver.smartwaiver import (
    SmartwaiverResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartwaiver.source import SmartwaiverSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Endpoints exposing Smartwaiver's server-side `fromDts` timestamp filter.
_INCREMENTAL_ENDPOINTS = {"waivers": "createdOn", "checkins": "date"}
_FULL_REFRESH_ENDPOINTS = {"templates"}


class TestSmartwaiverSource:
    def setup_method(self):
        self.source = SmartwaiverSource()
        self.team_id = 123
        self.config = SmartwaiverSourceConfig(api_key="key")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.SMARTWAIVER

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Smartwaiver"
        assert config.label == "Smartwaiver"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.iconPath == "/static/services/smartwaiver.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/smartwaiver"

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
            "401 Client Error: Unauthorized for url: https://api.smartwaiver.com/v4/waivers?limit=100&offset=0",
            "403 Client Error: Forbidden for url: https://api.smartwaiver.com/v4/checkins?fromDts=2000-01-01T00%3A00%3A00",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.smartwaiver.com/v4/waivers",
            "500 Server Error: Internal Server Error for url: https://api.smartwaiver.com/v4/waivers",
            "HTTPSConnectionPool(host='api.smartwaiver.com', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_match_endpoints_with_correct_sync_modes(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for name, cursor_field in _INCREMENTAL_ENDPOINTS.items():
            assert schemas[name].supports_incremental is True
            assert schemas[name].supports_append is True
            assert [f["field"] for f in schemas[name].incremental_fields] == [cursor_field]
        for name in _FULL_REFRESH_ENDPOINTS:
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["waivers"])
        assert len(schemas) == 1
        assert schemas[0].name == "waivers"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_lists_tables_without_credentials_publishes_catalog(self):
        # Static endpoint catalog (no I/O) — the public docs table list should render.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    def test_canonical_descriptions_cover_every_endpoint(self):
        canonical = self.source.get_canonical_descriptions()
        assert set(canonical) == set(SMARTWAIVER_ENDPOINTS)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, None), True, None),
            ((False, "Invalid Smartwaiver API key"), False, "Invalid Smartwaiver API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.smartwaiver.source.validate_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("key")

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is SmartwaiverResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.smartwaiver.source.smartwaiver_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_smartwaiver_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "waivers"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01 00:00:00"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_smartwaiver_source.assert_called_once()
        kwargs = mock_smartwaiver_source.call_args.kwargs
        assert kwargs["api_key"] == "key"
        assert kwargs["endpoint"] == "waivers"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01 00:00:00"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.smartwaiver.source.smartwaiver_source"
    )
    def test_source_for_pipeline_omits_cursor_when_not_incremental(self, mock_smartwaiver_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "templates"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01 00:00:00"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_smartwaiver_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self):
        inputs = mock.MagicMock()
        inputs.schema_name = "nope"
        with pytest.raises(ValueError, match="Unknown Smartwaiver schema"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
