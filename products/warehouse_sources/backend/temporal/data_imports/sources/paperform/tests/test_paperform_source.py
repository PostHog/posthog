import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PaperformSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.paperform.paperform import PaperformResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.paperform.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.paperform.source import PaperformSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestPaperformSource:
    def setup_method(self) -> None:
        self.source = PaperformSource()
        self.team_id = 123
        self.config = PaperformSourceConfig(api_key="pf-key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.PAPERFORM

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Paperform"
        assert config.label == "Paperform"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # The source is still landing across PRs, so it stays hidden until released.
        assert config.unreleasedSource is True
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/paperform"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    def test_api_key_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_only_submissions_supports_incremental(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert set(schemas) == set(ENDPOINTS)
        assert schemas["submissions"].supports_incremental is True
        assert [f["field"] for f in schemas["submissions"].incremental_fields] == ["created_at_utc"]
        # Forms and partial submissions mutate after creation, so a creation-time cursor would
        # freeze their updates — they must stay full refresh.
        assert all(
            s.supports_incremental is False and s.incremental_fields == []
            for name, s in schemas.items()
            if name != "submissions"
        )

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["submissions"])
        assert len(schemas) == 1
        assert schemas[0].name == "submissions"

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
                "401 Client Error: Unauthorized for url: https://api.paperform.co/v1/forms?limit=100",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://api.paperform.co/v1/spaces?limit=100",
            ),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.paperform.co/v1/forms"),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.paperform.co/v1/forms"),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, _name: str, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.paperform.source.validate_credentials"
    )
    def test_validate_credentials_delegates_with_api_key(self, mock_validate: mock.MagicMock) -> None:
        # The status-to-message mapping lives in paperform.validate_credentials; here we only assert
        # the source probes with the configured key and returns the delegate's verdict unchanged.
        mock_validate.return_value = (False, "Invalid Paperform API key")
        result = self.source.validate_credentials(self.config, self.team_id)
        mock_validate.assert_called_once_with("pf-key")
        assert result == (False, "Invalid Paperform API key")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is PaperformResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.paperform.source.paperform_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "submissions"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "pf-key"
        assert kwargs["endpoint"] == "submissions"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-01T00:00:00Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.paperform.source.paperform_source")
    def test_source_for_pipeline_drops_watermark_on_full_refresh(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "submissions"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        # A full refresh must re-read everything, even when a stale watermark is still stored.
        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Paperform schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
