import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MetorialSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.metorial.metorial import MetorialResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.metorial.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.metorial.source import MetorialSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

INCREMENTAL_ENDPOINTS = (
    "sessions",
    "session_messages",
    "session_errors",
    "tool_calls",
    "provider_runs",
    "provider_deployments",
)


class TestMetorialSource:
    def setup_method(self) -> None:
        self.source = MetorialSource()
        self.team_id = 123
        self.config = MetorialSourceConfig(api_key="metorial_sk_test")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.METORIAL

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Metorial"
        assert config.label == "Metorial"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/metorial"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    def test_api_key_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_no_connection_host_fields(self) -> None:
        # The only field is the secret API key; the base URL is hardcoded, so there is no non-secret
        # field an editor could retarget to reuse a preserved key against another project.
        assert self.source.connection_host_fields == []

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_covers_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @parameterized.expand([(e,) for e in INCREMENTAL_ENDPOINTS])
    def test_incremental_endpoints_advertise_incremental(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        assert schema.supports_incremental is True
        assert schema.supports_append is True
        assert {f["field"] for f in schema.incremental_fields} <= {"created_at", "updated_at"}

    def test_providers_is_full_refresh_only(self) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == "providers")
        assert schema.supports_incremental is False
        assert schema.supports_append is False
        assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["sessions"])
        assert len(schemas) == 1
        assert schemas[0].name == "sessions"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        sessions = next(t for t in tables if t["name"] == "sessions")
        assert "Incremental" in sessions["sync_methods"]

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.metorial.com/sessions",),
            ("403 Client Error: Forbidden for url: https://api.metorial.com/tool-calls",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("500 Server Error: Internal Server Error for url: https://api.metorial.com/sessions",),
            ("429 Client Error: Too Many Requests for url: https://api.metorial.com/sessions",),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.metorial.source.validate_metorial_credentials"
    )
    def test_validate_credentials_delegates_to_shared_helper(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (False, "Invalid Metorial API key")
        result = self.source.validate_credentials(self.config, self.team_id)
        assert result == (False, "Invalid Metorial API key")
        mock_validate.assert_called_once_with(api_key="metorial_sk_test")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is MetorialResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.metorial.source.metorial_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "sessions"
        inputs.should_use_incremental_field = True
        inputs.incremental_field = "updated_at"
        inputs.db_incremental_field_last_value = "2025-06-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "metorial_sk_test"
        assert kwargs["endpoint"] == "sessions"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["incremental_field"] == "updated_at"
        assert kwargs["db_incremental_field_last_value"] == "2025-06-01T00:00:00Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.metorial.source.metorial_source")
    def test_source_for_pipeline_drops_watermark_on_full_refresh(self, mock_source: mock.MagicMock) -> None:
        # A stale watermark left on the schema must not leak into a full-refresh sync as a filter.
        inputs = mock.MagicMock()
        inputs.schema_name = "sessions"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2025-06-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        inputs.should_use_incremental_field = False
        with pytest.raises(KeyError):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
