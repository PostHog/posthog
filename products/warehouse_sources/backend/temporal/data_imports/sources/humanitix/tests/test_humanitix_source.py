import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HumanitixSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.humanitix.humanitix import HumanitixResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.humanitix.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.humanitix.source import HumanitixSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestHumanitixSource:
    def setup_method(self) -> None:
        self.source = HumanitixSource()
        self.team_id = 123
        self.config = HumanitixSourceConfig(api_key="hmtx-key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.HUMANITIX

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Humanitix"
        assert config.label == "Humanitix"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is visible — it must not carry the scaffolding flag.
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/humanitix"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    def test_api_key_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_no_connection_host_fields(self) -> None:
        # The only field is the secret `api_key` itself; the base URL is hardcoded and the account is
        # implicit in the key. There is no non-secret field that retargets where the key is sent.
        assert self.source.connection_host_fields == []

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_covers_all_endpoints_as_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # Humanitix's list endpoints have no server-side timestamp filter, so every schema is full refresh.
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["tags"])
        assert len(schemas) == 1
        assert schemas[0].name == "tags"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_for_public_docs(self) -> None:
        # Exercises the credential-free catalog path used by the posthog.com docs.
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.humanitix.com/v1/events?page=1&pageSize=100",
            "403 Client Error: Forbidden for url: https://api.humanitix.com/v1/tags?page=2&pageSize=100",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @pytest.mark.parametrize(
        "unrelated_error",
        [
            "500 Server Error: Internal Server Error for url: https://api.humanitix.com/v1/events",
            "HTTPSConnectionPool(host='api.humanitix.com', port=443): Read timed out.",
            "429 Client Error: Too Many Requests for url: https://api.humanitix.com/v1/tags",
        ],
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid Humanitix API key"),
            (403, False, "Invalid Humanitix API key"),
            (500, False, "Humanitix returned HTTP 500"),
            (0, False, "Could not connect to Humanitix: boom"),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.humanitix.source.check_access")
    def test_validate_credentials(
        self,
        mock_check: mock.MagicMock,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        message = (
            "Humanitix returned HTTP 500"
            if status == 500
            else ("Could not connect to Humanitix: boom" if status == 0 else None)
        )
        mock_check.return_value = (status, message)
        is_valid, returned = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        assert returned == expected_message

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.humanitix.source.check_access")
    def test_validate_credentials_probes_the_account_key(self, mock_check: mock.MagicMock) -> None:
        # The API key is account-wide, so validation probes the key, not a per-schema scope.
        mock_check.return_value = (200, None)
        self.source.validate_credentials(self.config, self.team_id, schema_name="tags")
        mock_check.assert_called_once_with("hmtx-key")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is HumanitixResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.humanitix.source.humanitix_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_humanitix_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "events"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_humanitix_source.assert_called_once()
        kwargs = mock_humanitix_source.call_args.kwargs
        assert kwargs["api_key"] == "hmtx-key"
        assert kwargs["endpoint"] == "events"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Humanitix schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
