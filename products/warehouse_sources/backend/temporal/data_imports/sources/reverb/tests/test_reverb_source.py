import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.reverb import ReverbSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.reverb.reverb import ReverbResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.reverb.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.reverb.source import ReverbSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

_INCREMENTAL_ENDPOINTS = {"Orders", "Payouts"}
_FULL_REFRESH_ENDPOINTS = {"Listings"}


class TestReverbSource:
    def setup_method(self):
        self.source = ReverbSource()
        self.team_id = 123
        self.config = ReverbSourceConfig(api_token="token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.REVERB

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Reverb"
        assert config.category == DataWarehouseSourceCategory.E_COMMERCE
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/reverb.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/reverb"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_token"]

    def test_api_token_field_is_secret_password(self):
        config = self.source.get_source_config
        token_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_token")
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    def test_supported_api_version_is_declared_and_not_deprecated(self):
        assert self.source.default_version in self.source.supported_versions
        assert self.source.get_version_deprecation(self.source.default_version) is None

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.reverb.com/api/my/orders/selling/all",
            "403 Client Error: Forbidden for url: https://api.reverb.com/api/my/payouts",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.reverb.com/api/my/orders/selling/all",
            "500 Server Error: Internal Server Error for url: https://api.reverb.com/api/my/listings",
            "HTTPSConnectionPool(host='api.reverb.com', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_match_endpoints_with_correct_sync_modes(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for name in _INCREMENTAL_ENDPOINTS:
            assert schemas[name].supports_incremental is True
            assert schemas[name].supports_append is True
        for name in _FULL_REFRESH_ENDPOINTS:
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Orders"])
        assert len(schemas) == 1
        assert schemas[0].name == "Orders"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_lists_tables_without_credentials_publishes_catalog(self):
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    def test_canonical_descriptions_cover_every_endpoint(self):
        canonical = self.source.get_canonical_descriptions()
        assert set(canonical) == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid Reverb personal access token"),
            ((False, 403), False, "Could not connect to Reverb with the provided personal access token"),
            ((False, None), False, "Could not connect to Reverb with the provided personal access token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.reverb.source.validate_reverb_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("token", "3.0")

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is ReverbResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.reverb.source.reverb_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_reverb_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "Orders"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.api_version = None
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_reverb_source.assert_called_once()
        kwargs = mock_reverb_source.call_args.kwargs
        assert kwargs["api_token"] == "token"
        assert kwargs["endpoint"] == "Orders"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"
        assert kwargs["api_version"] == "3.0"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.reverb.source.reverb_source")
    def test_source_for_pipeline_omits_cursor_when_not_incremental(self, mock_reverb_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "Listings"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.api_version = None

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_reverb_source.call_args.kwargs["db_incremental_field_last_value"] is None
