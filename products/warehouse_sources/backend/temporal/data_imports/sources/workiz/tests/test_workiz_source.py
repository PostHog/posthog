import datetime

from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.workiz import WorkizSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.workiz.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.workiz.source import WorkizSource
from products.warehouse_sources.backend.temporal.data_imports.sources.workiz.workiz import WorkizResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestWorkizSource:
    def setup_method(self) -> None:
        self.source = WorkizSource()
        self.team_id = 123
        self.config = WorkizSourceConfig(api_token="tok")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.WORKIZ

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Workiz"
        assert config.label == "Workiz"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is visible -- it must not carry the scaffolding flag.
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/workiz"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_token"]

    def test_api_token_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_token")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_no_connection_host_fields(self) -> None:
        # The only field is the secret API token; the base URL is hardcoded, so there is no
        # non-secret field an editor could retarget to reuse a preserved token against another host.
        assert self.source.connection_host_fields == []

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_covers_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @parameterized.expand([("Jobs",), ("Leads",)])
    def test_get_schemas_marks_date_windowed_endpoints_incremental(self, name: str) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas[name].supports_incremental is True
        assert schemas[name].incremental_fields != []

    @parameterized.expand([("Team",), ("TimeOff",)])
    def test_get_schemas_marks_full_list_endpoints_full_refresh(self, name: str) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas[name].supports_incremental is False
        assert schemas[name].incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Team"])
        assert [s.name for s in schemas] == ["Team"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.workiz.com/api/v1/tok/job/all/",),
            ("403 Client Error: Forbidden for url: https://api.workiz.com/api/v1/tok/lead/all/",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("500 Server Error: Internal Server Error for url: https://api.workiz.com/api/v1/tok/job/all/",),
            ("429 Client Error: Too Many Requests for url: https://api.workiz.com/api/v1/tok/lead/all/",),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @parameterized.expand(
        [
            (True, None),
            (False, "Invalid API token. Check Settings > Integrations > Developer in Workiz and try again."),
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.workiz.source.validate_workiz_credentials"
    )
    def test_validate_credentials_delegates(
        self,
        expected_valid: bool,
        expected_message: str | None,
        mock_validate: mock.MagicMock,
    ) -> None:
        mock_validate.return_value = (expected_valid, expected_message)
        is_valid, returned = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        assert returned == expected_message
        mock_validate.assert_called_once_with("tok")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is WorkizResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.workiz.source.workiz_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        mock_source.return_value.name = "Leads"
        mock_source.return_value.column_hints = None
        inputs = mock.MagicMock()
        inputs.schema_name = "Leads"
        inputs.team_id = 123
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = datetime.datetime(2024, 1, 1)
        inputs.incremental_field = "LeadDateTime"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_token"] == "tok"
        assert kwargs["endpoint"] == "Leads"
        assert kwargs["team_id"] == 123
        assert kwargs["job_id"] == "job-1"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == datetime.datetime(2024, 1, 1)
        assert kwargs["incremental_field"] == "LeadDateTime"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.workiz.source.workiz_source")
    def test_source_for_pipeline_full_refresh_drops_last_value(self, mock_source: mock.MagicMock) -> None:
        # should_use_incremental_field=False means the schema is fully replaced each sync, so any
        # stale last_value must not leak into the request.
        mock_source.return_value.name = "Leads"
        mock_source.return_value.column_hints = None
        inputs = mock.MagicMock()
        inputs.schema_name = "Leads"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = datetime.datetime(2024, 1, 1)

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    @parameterized.expand(
        [
            ("Jobs", ["UUID"], "desc"),
            ("Leads", ["UUID"], "desc"),
            ("Team", ["id"], "asc"),
            ("TimeOff", ["userName", "start"], "asc"),
        ]
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.workiz.source.workiz_source")
    def test_source_for_pipeline_response_shape(
        self,
        schema_name: str,
        expected_primary_keys: list[str],
        expected_sort_mode: str,
        mock_source: mock.MagicMock,
    ) -> None:
        mock_source.return_value.name = schema_name
        mock_source.return_value.column_hints = None
        inputs = mock.MagicMock()
        inputs.schema_name = schema_name
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = None

        response = self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert response.primary_keys == expected_primary_keys
        assert response.sort_mode == expected_sort_mode
        if schema_name in ("Jobs", "Leads"):
            assert response.partition_mode == "datetime"
            assert response.partition_keys == ["CreatedDate"]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
