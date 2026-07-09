import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.flexmail.flexmail import FlexmailResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.flexmail.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.flexmail.source import FlexmailSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FlexmailSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestFlexmailSource:
    def setup_method(self) -> None:
        self.source = FlexmailSource()
        self.team_id = 123
        self.config = FlexmailSourceConfig(account_id="12345", personal_access_token="flexmail-token")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.FLEXMAIL

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Flexmail"
        assert config.label == "Flexmail"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/flexmail"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["account_id", "personal_access_token"]

    def test_personal_access_token_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "personal_access_token"
        )
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_no_connection_host_fields(self) -> None:
        # The base URL is hardcoded and the account ID only selects the Flexmail account the token
        # already belongs to, so there is no non-secret field an editor could retarget to exfiltrate
        # a preserved token to another host.
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
        schemas = self.source.get_schemas(self.config, self.team_id, names=["contacts"])
        assert len(schemas) == 1
        assert schemas[0].name == "contacts"

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
                "401 Client Error: Unauthorized for url: https://api.flexmail.eu/contacts?limit=500&offset=0",
            ),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.flexmail.eu/sources?limit=500&offset=0"),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://api.flexmail.eu/contacts",
            ),
            (
                "rate_limited",
                "429 Client Error: Too Many Requests for url: https://api.flexmail.eu/segments",
            ),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, _name: str, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.flexmail.source.validate_credentials")
    def test_validate_credentials_delegates_with_credentials(self, mock_validate: mock.MagicMock) -> None:
        # The status-to-message mapping lives in flexmail.validate_credentials; here we only assert
        # the source probes with the configured credentials and returns the delegate's verdict.
        mock_validate.return_value = (False, "Invalid Flexmail account ID or personal access token")
        result = self.source.validate_credentials(self.config, self.team_id)
        mock_validate.assert_called_once_with("12345", "flexmail-token")
        assert result == (False, "Invalid Flexmail account ID or personal access token")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is FlexmailResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.flexmail.source.flexmail_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "contacts"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["account_id"] == "12345"
        assert kwargs["personal_access_token"] == "flexmail-token"
        assert kwargs["endpoint"] == "contacts"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Flexmail schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

    def test_canonical_descriptions_cover_known_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions) == set(ENDPOINTS)
