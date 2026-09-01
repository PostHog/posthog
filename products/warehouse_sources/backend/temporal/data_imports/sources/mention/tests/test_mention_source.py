import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mention import (
    MentionSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mention.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.mention.source import MentionSource


class TestMentionSource:
    def setup_method(self) -> None:
        self.source = MentionSource()
        self.team_id = 123
        self.config = MentionSourceConfig(access_token="tok")

    def test_new_sources_default_to_latest_version(self) -> None:
        # New sources are stamped with default_version; it must be the newest supported label.
        assert self.source.supported_versions == ("1.19", "1.21")
        assert self.source.default_version == "1.21"

    def test_no_connection_host_fields(self) -> None:
        # The only field is the secret access token; the base URL is hardcoded, so there is no
        # non-secret field an editor could retarget to reuse a preserved token against another host.
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
        schemas = self.source.get_schemas(self.config, self.team_id, names=["mentions"])
        assert len(schemas) == 1
        assert schemas[0].name == "mentions"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.mention.net/api/accounts/me",),
            ("403 Client Error: Forbidden for url: https://api.mention.net/api/accounts/acc1/alerts",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("500 Server Error: Internal Server Error for url: https://api.mention.net/api/accounts/me",),
            ("429 Client Error: Too Many Requests for url: https://api.mention.net/api/accounts/acc1/alerts",),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mention.source.validate_credentials")
    def test_validate_credentials_delegates_to_shared_helper(self, mock_validate: mock.MagicMock) -> None:
        # The source method forwards the account access token to the shared validator and returns its result verbatim.
        mock_validate.return_value = (False, "Invalid Mention access token")
        result = self.source.validate_credentials(self.config, self.team_id)
        assert result == (False, "Invalid Mention access token")
        mock_validate.assert_called_once_with("tok", api_version="1.21")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mention.source.mention_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "mentions"
        inputs.api_version = "1.21"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["access_token"] == "tok"
        assert kwargs["endpoint"] == "mentions"
        assert kwargs["resumable_source_manager"] is manager
        # The resolved source pin is threaded to the request layer so it drives the Accept-Version header.
        assert kwargs["api_version"] == "1.21"

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Mention schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
