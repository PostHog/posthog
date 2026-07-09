import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SmailySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.smaily.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.smaily.smaily import SmailyResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.smaily.source import SmailySource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestSmailySource:
    def setup_method(self) -> None:
        self.source = SmailySource()
        self.team_id = 123
        self.config = SmailySourceConfig(subdomain="acme", username="user", password="pass")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.SMAILY

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Smaily"
        assert config.label == "Smaily"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/smaily"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["subdomain", "username", "password"]

    def test_password_field_is_secret(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "password")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_subdomain_is_a_connection_host_field(self) -> None:
        # The stored password is sent to `{subdomain}.sendsmaily.net`; retargeting the subdomain
        # without re-entering the password would let an editor replay the credential elsewhere.
        assert self.source.connection_host_fields == ["subdomain"]

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
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://acme.sendsmaily.net/api/campaign.php?page=0",
            ),
            ("forbidden", "403 Client Error: Forbidden for url: https://acme.sendsmaily.net/api/contact.php?list=1"),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://acme.sendsmaily.net/api/campaign.php",
            ),
            (
                "rate_limited",
                "429 Client Error: Too Many Requests for url: https://acme.sendsmaily.net/api/list.php",
            ),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, _name: str, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.smaily.source.validate_credentials")
    def test_validate_credentials_delegates_with_config_values(self, mock_validate: mock.MagicMock) -> None:
        # The status-to-message mapping lives in smaily.validate_credentials; here we only assert
        # the source probes with the configured credentials and returns the verdict unchanged.
        mock_validate.return_value = (False, "Invalid Smaily credentials")
        result = self.source.validate_credentials(self.config, self.team_id)
        mock_validate.assert_called_once_with("acme", "user", "pass")
        assert result == (False, "Invalid Smaily credentials")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is SmailyResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.smaily.source.smaily_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "campaigns"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["subdomain"] == "acme"
        assert kwargs["username"] == "user"
        assert kwargs["password"] == "pass"
        assert kwargs["endpoint"] == "campaigns"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Smaily schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
