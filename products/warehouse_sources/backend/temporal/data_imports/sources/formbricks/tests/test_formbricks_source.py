import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.formbricks.formbricks import (
    FormbricksResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.formbricks.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.formbricks.source import FormbricksSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FormbricksSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestFormbricksSource:
    def setup_method(self) -> None:
        self.source = FormbricksSource()
        self.team_id = 123
        self.config = FormbricksSourceConfig(api_key="fb-key", host="https://formbricks.example.com")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.FORMBRICKS

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Formbricks"
        assert config.label == "Formbricks"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/formbricks"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["host", "api_key"]

    def test_api_key_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_host_field_is_optional_connection_target(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "host")
        assert field.required is False
        assert field.secret is False
        # The base URL field must stay named `host`: the update serializer treats `host` as a
        # connection target and forces secrets to be re-entered when it changes. Renaming it
        # without adding it to connection_host_fields would let an editor retarget the stored
        # API key at a server they control.
        assert field.name == "host"

    def test_connection_host_fields_cover_host(self) -> None:
        # `host` decides where the stored API key gets sent, so changing it must force re-entry.
        assert self.source.connection_host_fields == ["host"]

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_covers_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_only_responses_supports_incremental(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        by_name = {s.name: s for s in schemas}
        assert by_name["responses"].supports_incremental is True
        assert {f["field"] for f in by_name["responses"].incremental_fields} == {"createdAt", "updatedAt"}
        for name, schema in by_name.items():
            if name == "responses":
                continue
            assert schema.supports_incremental is False
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["surveys", "nope"])
        assert [s.name for s in schemas] == ["surveys"]

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://app.formbricks.com/api/v2/management/responses",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://formbricks.example.com/api/v1/management/surveys",
            ),
            ("host_not_allowed", "Formbricks host is not allowed: internal IP"),
            ("plaintext_http", "Formbricks host must use HTTPS"),
        ]
    )
    def test_non_retryable_errors_match_permanent_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("server_error", "500 Server Error: Internal Server Error for url: https://app.formbricks.com"),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://app.formbricks.com"),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, _name: str, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.formbricks.source.validate_formbricks_credentials"
    )
    def test_validate_credentials_delegates_with_host_and_key(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (False, "Invalid Formbricks API key")
        result = self.source.validate_credentials(self.config, self.team_id)
        mock_validate.assert_called_once_with("https://formbricks.example.com", "fb-key", self.team_id)
        assert result == (False, "Invalid Formbricks API key")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is FormbricksResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.formbricks.source.formbricks_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "responses"
        inputs.team_id = self.team_id
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = "updatedAt"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["host"] == "https://formbricks.example.com"
        assert kwargs["api_key"] == "fb-key"
        assert kwargs["endpoint"] == "responses"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["team_id"] == self.team_id
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"
        assert kwargs["incremental_field"] == "updatedAt"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.formbricks.source.formbricks_source")
    def test_source_for_pipeline_drops_last_value_on_full_refresh(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "responses"
        inputs.team_id = self.team_id
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Formbricks schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
