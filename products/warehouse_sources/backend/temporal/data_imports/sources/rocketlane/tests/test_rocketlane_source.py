import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RocketlaneSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.rocketlane.rocketlane import (
    RocketlaneResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rocketlane.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.rocketlane.source import RocketlaneSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestRocketlaneSource:
    def setup_method(self) -> None:
        self.source = RocketlaneSource()
        self.team_id = 123
        self.config = RocketlaneSourceConfig(api_key="rl-key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.ROCKETLANE

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Rocketlane"
        assert config.label == "Rocketlane"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is visible — it must not carry the scaffolding flag.
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/rocketlane"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    def test_api_key_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_no_connection_host_fields(self) -> None:
        # The only field is the secret `api_key`; the base URL is hardcoded and the account is
        # implicit in the key, so there is no non-secret field that retargets where the key is sent.
        assert self.source.connection_host_fields == []

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_covers_all_endpoints_as_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # Rocketlane's list endpoints have no single server-side timestamp cursor, so every schema
        # is full refresh.
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["tasks"])
        assert len(schemas) == 1
        assert schemas[0].name == "tasks"

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
            "401 Client Error: Unauthorized for url: https://api.rocketlane.com/api/1.0/projects?pageSize=100",
            "403 Client Error: Forbidden for url: https://api.rocketlane.com/api/1.0/tasks?pageSize=100&pageToken=abc",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @pytest.mark.parametrize(
        "unrelated_error",
        [
            "500 Server Error: Internal Server Error for url: https://api.rocketlane.com/api/1.0/projects",
            "HTTPSConnectionPool(host='api.rocketlane.com', port=443): Read timed out.",
            "429 Client Error: Too Many Requests for url: https://api.rocketlane.com/api/1.0/users",
        ],
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid Rocketlane API key"),
            (403, False, "Invalid Rocketlane API key"),
            (500, False, "Rocketlane returned HTTP 500"),
            (0, False, "Could not connect to Rocketlane: boom"),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.rocketlane.source.check_access")
    def test_validate_credentials(
        self,
        mock_check: mock.MagicMock,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        message = (
            "Rocketlane returned HTTP 500"
            if status == 500
            else ("Could not connect to Rocketlane: boom" if status == 0 else None)
        )
        mock_check.return_value = (status, message)
        is_valid, returned = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        assert returned == expected_message

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.rocketlane.source.check_access")
    def test_validate_credentials_probes_the_account_key(self, mock_check: mock.MagicMock) -> None:
        # The api-key is account-wide, so validation probes the key, not a per-schema scope.
        mock_check.return_value = (200, None)
        self.source.validate_credentials(self.config, self.team_id, schema_name="tasks")
        mock_check.assert_called_once_with("rl-key")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is RocketlaneResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.rocketlane.source.rocketlane_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_rocketlane_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "projects"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_rocketlane_source.assert_called_once()
        kwargs = mock_rocketlane_source.call_args.kwargs
        assert kwargs["api_key"] == "rl-key"
        assert kwargs["endpoint"] == "projects"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Rocketlane schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
