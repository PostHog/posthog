import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import JustSiftSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.justsift.justsift import JustSiftResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.justsift.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.justsift.source import JustSiftSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestJustSiftSource:
    def setup_method(self) -> None:
        self.source = JustSiftSource()
        self.team_id = 123
        self.config = JustSiftSourceConfig(api_key="sift-token")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.JUSTSIFT

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "JustSift"
        assert config.label == "JustSift"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is visible — it must not carry the scaffolding flag.
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/justsift"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    def test_api_key_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_no_connection_host_fields(self) -> None:
        # The only field is the secret token itself; the base URL is hardcoded and the org is implicit
        # in the token. There is no non-secret field that retargets where the token is sent.
        assert self.source.connection_host_fields == []

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_covers_all_endpoints_as_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # Sift's list endpoints have no server-side timestamp filter, so every schema is full refresh.
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["fields"])
        assert len(schemas) == 1
        assert schemas[0].name == "fields"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_for_public_docs(self) -> None:
        # Exercises the credential-free catalog path used by the posthog.com docs.
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.justsift.com/v1/search/people?page=1&pageSize=100",),
            ("403 Client Error: Forbidden for url: https://api.justsift.com/v1/fields?page=1&pageSize=100",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("500 Server Error: Internal Server Error for url: https://api.justsift.com/v1/search/people",),
            ("HTTPSConnectionPool(host='api.justsift.com', port=443): Read timed out.",),
            ("429 Client Error: Too Many Requests for url: https://api.justsift.com/v1/fields",),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @parameterized.expand(
        [
            (200, True, None),
            (401, False, "Invalid Sift API token"),
            (403, False, "Invalid Sift API token"),
            (500, False, "Sift returned HTTP 500"),
            (0, False, "Could not connect to Sift: boom"),
        ]
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.justsift.source.check_access")
    def test_validate_credentials(
        self,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_check: mock.MagicMock,
    ) -> None:
        message = (
            "Sift returned HTTP 500" if status == 500 else ("Could not connect to Sift: boom" if status == 0 else None)
        )
        mock_check.return_value = (status, message)
        is_valid, returned = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        assert returned == expected_message

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.justsift.source.check_access")
    def test_validate_credentials_probes_the_token(self, mock_check: mock.MagicMock) -> None:
        # The token is org-wide, so validation probes the token, not a per-schema scope.
        mock_check.return_value = (200, None)
        self.source.validate_credentials(self.config, self.team_id, schema_name="fields")
        mock_check.assert_called_once_with("sift-token")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is JustSiftResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.justsift.source.justsift_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_justsift_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "people"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_justsift_source.assert_called_once()
        kwargs = mock_justsift_source.call_args.kwargs
        assert kwargs["api_key"] == "sift-token"
        assert kwargs["endpoint"] == "people"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Sift schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
