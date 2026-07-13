import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PersistIqSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.persistiq import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.persistiq.persistiq import PersistiqResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.persistiq.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.persistiq.source import PersistIqSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestPersistIqSource:
    def setup_method(self) -> None:
        self.source = PersistIqSource()
        self.team_id = 123
        self.config = PersistIqSourceConfig(api_key="pq-key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.PERSISTIQ

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.label == "PersistIq"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is visible — it must not carry the scaffolding flag.
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/persistiq"

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
        # field an editor could retarget to reuse a preserved key against another account.
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
        schemas = self.source.get_schemas(self.config, self.team_id, names=["campaigns"])
        assert len(schemas) == 1
        assert schemas[0].name == "campaigns"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.persistiq.com/v1/leads?page=1"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.persistiq.com/v1/users?page=1"),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.persistiq.com/v1/leads"),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.persistiq.com/v1/campaigns"),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, _name: str, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @parameterized.expand(
        [
            ("valid", (True, None)),
            ("invalid_key", (False, "Invalid PersistIQ API key")),
            ("connect_error", (False, "Could not connect to PersistIQ: boom")),
        ]
    )
    def test_validate_credentials_delegates_to_probe(self, _name: str, underlying: tuple[bool, str | None]) -> None:
        # The status → message mapping is covered by the persistiq.validate_credentials unit test; here
        # we only guard that the source extracts the API key and returns the probe result unchanged.
        with mock.patch.object(source_module, "validate_credentials", return_value=underlying) as mock_validate:
            result = self.source.validate_credentials(self.config, self.team_id)
        assert result == underlying
        mock_validate.assert_called_once_with("pq-key")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is PersistiqResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.persistiq.source.persistiq_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "leads"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "pq-key"
        assert kwargs["endpoint"] == "leads"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown PersistIQ schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
