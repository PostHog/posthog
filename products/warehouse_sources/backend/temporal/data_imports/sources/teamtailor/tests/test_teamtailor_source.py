import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TeamtailorSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.teamtailor.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.teamtailor.source import TeamtailorSource
from products.warehouse_sources.backend.temporal.data_imports.sources.teamtailor.teamtailor import (
    TeamtailorResumeConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestTeamtailorSource:
    def setup_method(self) -> None:
        self.source = TeamtailorSource()
        self.team_id = 123
        self.config = TeamtailorSourceConfig(api_key="tt-key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.TEAMTAILOR

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Teamtailor"
        assert config.label == "Teamtailor"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is visible — it must not carry the scaffolding flag.
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/teamtailor"

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
        schemas = self.source.get_schemas(self.config, self.team_id, names=["jobs"])
        assert len(schemas) == 1
        assert schemas[0].name == "jobs"

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
                "401 Client Error: Unauthorized for url: https://api.teamtailor.com/v1/candidates?page%5Bsize%5D=30",
            ),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.teamtailor.com/v1/jobs?page%5Bsize%5D=30"),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://api.teamtailor.com/v1/candidates",
            ),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.teamtailor.com/v1/jobs"),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, _name: str, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Teamtailor API key"),
            ("forbidden", 403, False, "Invalid Teamtailor API key"),
            ("server_error", 500, False, "Teamtailor returned HTTP 500"),
            ("connection_error", 0, False, "Could not connect to Teamtailor: boom"),
        ]
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.teamtailor.teamtailor.check_access")
    def test_validate_credentials(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_check: mock.MagicMock,
    ) -> None:
        message = (
            "Teamtailor returned HTTP 500"
            if status == 500
            else ("Could not connect to Teamtailor: boom" if status == 0 else None)
        )
        mock_check.return_value = (status, message)
        is_valid, returned = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        assert returned == expected_message

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is TeamtailorResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.teamtailor.source.teamtailor_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "candidates"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "tt-key"
        assert kwargs["endpoint"] == "candidates"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Teamtailor schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
