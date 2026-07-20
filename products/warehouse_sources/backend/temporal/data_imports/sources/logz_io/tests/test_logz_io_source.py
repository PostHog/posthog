import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import LogzIOSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.logz_io.logz_io import LogzIOResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.logz_io.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.logz_io.source import LogzIOSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

SOURCE = "products.warehouse_sources.backend.temporal.data_imports.sources.logz_io.source"


class TestLogzIOSource:
    def setup_method(self):
        self.source = LogzIOSource()
        self.team_id = 123
        self.config = LogzIOSourceConfig(api_token="token", region="us")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.LOGZIO

    def test_connection_host_fields_includes_region(self):
        # region picks the host the stored token is sent to, so editing it must re-require the secret.
        assert self.source.connection_host_fields == ["region"]

    def test_get_source_config(self):
        config = self.source.get_source_config
        assert config.name.value == "LogzIO"
        assert config.label == "Logz.io"
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/logz-io"
        # A finished source must never keep the scaffold's unreleasedSource flag (it hides the source).
        assert config.unreleasedSource is None

    def test_source_config_fields(self):
        fields = self.source.get_source_config.fields
        assert [f.name for f in fields] == ["api_token", "region"]

        api_token = next(f for f in fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_token")
        assert api_token.type == SourceFieldInputConfigType.PASSWORD
        assert api_token.secret is True
        assert api_token.required is True

        region = next(f for f in fields if isinstance(f, SourceFieldSelectConfig) and f.name == "region")
        assert region.defaultValue == "us"
        assert {opt.value for opt in region.options} == {"us", "eu", "uk", "ca", "au", "wa"}

    def test_lists_tables_without_credentials(self):
        # get_schemas iterates a static endpoint catalog with no I/O, so the public docs catalog renders.
        assert self.source.lists_tables_without_credentials is True
        documented = {t["name"]: t for t in self.source.get_documented_tables()}
        assert set(documented) == set(ENDPOINTS)
        assert "Incremental" in documented["search_logs"]["sync_methods"]
        assert documented["alerts"]["sync_methods"] == ["Full refresh"]

    @pytest.mark.parametrize(
        "endpoint, expected_incremental",
        [
            # Only search_logs has a genuine server-side time filter (the ES @timestamp range query).
            ("search_logs", True),
            ("alerts", False),
            ("triggered_alerts", False),
            ("notification_endpoints", False),
            ("drop_filters", False),
        ],
    )
    def test_incremental_support_per_endpoint(self, endpoint: str, expected_incremental: bool):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert set(schemas) == set(ENDPOINTS)
        assert schemas[endpoint].supports_incremental is expected_incremental
        assert schemas[endpoint].incremental_fields == INCREMENTAL_FIELDS[endpoint]

    def test_get_schemas_filtered_by_names(self):
        assert [s.name for s in self.source.get_schemas(self.config, self.team_id, names=["alerts"])] == ["alerts"]
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.logz.io/v1/scroll",
            "403 Client Error: Forbidden for url: https://api-eu.logz.io/v2/alerts",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str):
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "other_error",
        [
            "500 Server Error: Internal Server Error for url: https://api.logz.io/v1/scroll",
            "429 Client Error: Too Many Requests for url: https://api.logz.io/v1/scroll",
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
        ],
    )
    def test_non_retryable_errors_ignore_transient_and_unrelated(self, other_error: str):
        assert not any(key in other_error for key in self.source.get_non_retryable_errors())

    @mock.patch(f"{SOURCE}.validate_logz_io_credentials")
    def test_validate_credentials_plumbs_arguments(self, mock_validate: mock.MagicMock):
        mock_validate.return_value = (True, None)
        assert self.source.validate_credentials(self.config, self.team_id, "alerts") == (True, None)
        mock_validate.assert_called_once_with("token", "us", "alerts")

    def test_get_resumable_source_manager_binds_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is LogzIOResumeConfig

    @mock.patch(f"{SOURCE}.logz_io_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock):
        inputs = mock.MagicMock()
        inputs.schema_name = "search_logs"
        inputs.should_use_incremental_field = True
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_token"] == "token"
        assert kwargs["region"] == "us"
        assert kwargs["endpoint"] == "search_logs"
        assert kwargs["resumable_source_manager"] is manager

    @mock.patch(f"{SOURCE}.logz_io_source")
    def test_source_for_pipeline_omits_watermark_when_not_incremental(self, mock_source: mock.MagicMock):
        inputs = mock.MagicMock()
        inputs.schema_name = "alerts"
        inputs.should_use_incremental_field = False

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_keyed_by_endpoint(self):
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions).issubset(set(ENDPOINTS))
        assert "search_logs" in descriptions
