import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ReplyIoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.reply_io.reply_io import ReplyIoResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.reply_io.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.reply_io.source import ReplyIoSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestReplyIoSource:
    def setup_method(self) -> None:
        self.source = ReplyIoSource()
        self.team_id = 123
        self.config = ReplyIoSourceConfig(api_key="reply-key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.REPLYIO

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "ReplyIo"
        assert config.label == "Reply.io"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/reply-io"

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
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.reply.io/v3/contacts?top=1000"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.reply.io/v3/sequences?top=1000"),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.reply.io/v3/contacts"),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.reply.io/v3/tasks"),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, _name: str, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @parameterized.expand(
        [
            ("source_create_probes_whoami", None, None),
            ("known_schema_probes_its_endpoint", "contacts", "contacts"),
            ("unknown_schema_falls_back_to_whoami", "not_a_table", None),
        ]
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.reply_io.source.validate_credentials")
    def test_validate_credentials_delegates(
        self, _name: str, schema_name: str | None, expected_endpoint: str | None, mock_validate: mock.MagicMock
    ) -> None:
        mock_validate.return_value = (True, None)
        result = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)
        mock_validate.assert_called_once_with("reply-key", endpoint=expected_endpoint)
        assert result == (True, None)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.reply_io.source.check_endpoint_permissions"
    )
    def test_get_endpoint_permissions_delegates(self, mock_check: mock.MagicMock) -> None:
        mock_check.return_value = {"contacts": None}
        result = self.source.get_endpoint_permissions(self.config, self.team_id, ["contacts"])
        mock_check.assert_called_once_with("reply-key", ["contacts"])
        assert result == {"contacts": None}

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ReplyIoResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.reply_io.source.reply_io_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "contacts"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "reply-key"
        assert kwargs["endpoint"] == "contacts"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Reply.io schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
