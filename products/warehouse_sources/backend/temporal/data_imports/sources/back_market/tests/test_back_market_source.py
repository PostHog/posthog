import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.back_market.back_market import (
    BackMarketResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.back_market.settings import (
    BACK_MARKET_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.back_market.source import BackMarketSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.backmarket import (
    BackMarketSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_INCREMENTAL_ENDPOINTS = {"orders"}
_FULL_REFRESH_ENDPOINTS = {"listings"}


class TestBackMarketSource:
    def setup_method(self):
        self.source = BackMarketSource()
        self.team_id = 123
        self.config = BackMarketSourceConfig(api_token="token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.BACKMARKET

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "BackMarket"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/back_market.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_token"]

    def test_api_token_field_is_secret_password(self):
        config = self.source.get_source_config
        api_token_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_token"
        )
        assert api_token_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_token_field.secret is True
        assert api_token_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://www.backmarket.com/ws/orders?page=1",
            "403 Client Error: Forbidden for url: https://www.backmarket.com/ws/listings?page=1",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://www.backmarket.com/ws/orders",
            "500 Server Error: Internal Server Error for url: https://www.backmarket.com/ws/orders",
            "HTTPSConnectionPool(host='www.backmarket.com', port=443): Read timed out.",
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
            assert {f["field"] for f in schemas[name].incremental_fields} == {"date_modification", "date_creation"}
        for name in _FULL_REFRESH_ENDPOINTS:
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["orders"])
        assert len(schemas) == 1
        assert schemas[0].name == "orders"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_lists_tables_without_credentials_publishes_catalog(self):
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    def test_canonical_descriptions_cover_every_endpoint(self):
        canonical = self.source.get_canonical_descriptions()
        assert set(canonical) == set(BACK_MARKET_ENDPOINTS)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid Back Market API token"),
            ((False, 403), False, "Could not connect to Back Market with the provided API token"),
            ((False, None), False, "Could not connect to Back Market with the provided API token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.back_market.source.validate_back_market_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("token")

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is BackMarketResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.back_market.source.back_market_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_back_market_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "orders"
        inputs.should_use_incremental_field = True
        inputs.incremental_field = "date_modification"
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_back_market_source.assert_called_once()
        kwargs = mock_back_market_source.call_args.kwargs
        assert kwargs["api_token"] == "token"
        assert kwargs["endpoint"] == "orders"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["incremental_field"] == "date_modification"
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.back_market.source.back_market_source"
    )
    def test_source_for_pipeline_omits_cursor_when_not_incremental(self, mock_back_market_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "listings"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_back_market_source.call_args.kwargs["db_incremental_field_last_value"] is None
