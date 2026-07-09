import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import OncehubSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.oncehub.oncehub import OncehubResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.oncehub.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.oncehub.source import OncehubSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestOncehubSource:
    def setup_method(self) -> None:
        self.source = OncehubSource()
        self.team_id = 123
        self.config = OncehubSourceConfig(api_key="oncehub-key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.ONCEHUB

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Oncehub"
        assert config.label == "OnceHub"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/oncehub"

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
        # field an editor could retarget to reuse a preserved key against another host.
        assert self.source.connection_host_fields == []

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_covers_all_endpoints_as_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["bookings"])
        assert len(schemas) == 1
        assert schemas[0].name == "bookings"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.oncehub.com/v2/bookings?limit=100",
            ),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.oncehub.com/v2/contacts?limit=100"),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://api.oncehub.com/v2/bookings",
            ),
            (
                "rate_limited",
                "429 Client Error: Too Many Requests for url: https://api.oncehub.com/v2/contacts",
            ),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, _name: str, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.oncehub.source.validate_credentials")
    def test_validate_credentials_delegates_with_api_key(self, mock_validate: mock.MagicMock) -> None:
        # The status-to-message mapping lives in oncehub.validate_credentials; here we only assert the
        # source probes with the configured key and returns the delegate's verdict unchanged.
        mock_validate.return_value = (False, "Invalid OnceHub API key")
        result = self.source.validate_credentials(self.config, self.team_id)
        mock_validate.assert_called_once_with("oncehub-key")
        assert result == (False, "Invalid OnceHub API key")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is OncehubResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.oncehub.source.oncehub_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "bookings"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "oncehub-key"
        assert kwargs["endpoint"] == "bookings"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown OnceHub schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
