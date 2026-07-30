import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.dbt.dbt import DbtResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.dbt.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.dbt.source import DbtSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DbtSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestDbtSource:
    def setup_method(self):
        self.source = DbtSource()
        self.team_id = 123
        self.config = DbtSourceConfig(account_id="12345", api_token="dbtc_token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.DBT

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Dbt"
        assert config.label == "dbt"
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/dbt"

        field_names = [f.name for f in config.fields]
        assert field_names == ["account_id", "api_token", "region", "custom_base_url"]

        account_field, token_field, region_field, custom_url_field = config.fields
        assert isinstance(account_field, SourceFieldInputConfig)
        assert account_field.required is True
        assert account_field.secret is False

        assert isinstance(token_field, SourceFieldInputConfig)
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

        assert isinstance(region_field, SourceFieldSelectConfig)
        assert [option.value for option in region_field.options] == ["us", "emea", "au"]
        assert region_field.defaultValue == "us"

        assert isinstance(custom_url_field, SourceFieldInputConfig)
        assert custom_url_field.required is False

    def test_connection_host_fields_cover_host_determining_fields(self):
        # These fields retarget where the stored token is sent (host and account path); missing one
        # lets an editor point the preserved credential at their own server or another account.
        assert self.source.connection_host_fields == ["region", "custom_base_url", "account_id"]

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors(self, expected_key):
        assert any(expected_key in key for key in self.source.get_non_retryable_errors())

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "endpoint, incremental",
        [
            ("accounts", False),
            ("projects", False),
            ("environments", False),
            ("jobs", False),
            ("users", False),
            ("runs", True),
        ],
    )
    def test_schema_incremental_support(self, endpoint, incremental):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas[endpoint].supports_incremental is incremental
        # The lookback re-pulls a window of rows each run, so merge is the only safe mode.
        assert schemas[endpoint].supports_append is False

    def test_users_not_synced_by_default(self):
        # Listing users needs permissions many read-only tokens lack; a default connection
        # must not enable a table whose first sync would 403.
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["users"].should_sync_default is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["runs"])
        assert len(schemas) == 1
        assert schemas[0].name == "runs"

    def test_get_schemas_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return",
        [
            (True, None),
            (False, "Invalid dbt API token"),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dbt.source.validate_dbt_credentials")
    def test_validate_credentials(self, mock_validate, mock_return):
        mock_validate.return_value = mock_return

        result = self.source.validate_credentials(self.config, self.team_id, schema_name="runs")

        assert result == mock_return
        mock_validate.assert_called_once_with(
            api_token="dbtc_token",
            account_id="12345",
            region="us",
            custom_base_url=None,
            team_id=self.team_id,
            schema_name="runs",
        )

    def test_get_resumable_source_manager(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is DbtResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dbt.source.dbt_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_dbt_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "runs"
        inputs.team_id = 42
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = "created_at"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_dbt_source.assert_called_once()
        kwargs = mock_dbt_source.call_args.kwargs
        assert kwargs["api_token"] == "dbtc_token"
        assert kwargs["account_id"] == "12345"
        assert kwargs["region"] == "us"
        assert kwargs["custom_base_url"] is None
        assert kwargs["endpoint"] == "runs"
        assert kwargs["team_id"] == 42
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"
        assert kwargs["incremental_field"] == "created_at"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dbt.source.dbt_source")
    def test_source_for_pipeline_omits_last_value_when_not_incremental(self, mock_dbt_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "projects"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "ignored"
        inputs.incremental_field = None

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_dbt_source.call_args.kwargs["db_incremental_field_last_value"] is None
