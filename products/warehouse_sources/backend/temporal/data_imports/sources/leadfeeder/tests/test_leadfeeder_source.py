from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import LeadfeederSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.leadfeeder import (
    LeadfeederResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.source import LeadfeederSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestLeadfeederSource:
    def setup_method(self) -> None:
        self.source = LeadfeederSource()
        self.team_id = 123
        self.config = LeadfeederSourceConfig(api_token="token", start_date="2024-01-01")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.LEADFEEDER

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Leadfeeder"
        assert config.label == "Leadfeeder"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # Kept unreleased until the alpha has been exercised end to end against the live API.
        assert config.unreleasedSource is True
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/leadfeeder"
        assert [f.name for f in config.fields] == ["api_token", "start_date"]

    def test_api_token_field_is_secret_password(self) -> None:
        token_field = next(
            f
            for f in self.source.get_source_config.fields
            if isinstance(f, SourceFieldInputConfig) and f.name == "api_token"
        )
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O, so public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True

    @parameterized.expand(
        [
            "401 Client Error: Unauthorized for url: https://api.leadfeeder.com/accounts",
            "403 Client Error: Forbidden for url: https://api.leadfeeder.com/accounts/1/leads",
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            "429 Client Error: Too Many Requests for url: https://api.leadfeeder.com/accounts/1/visits",
            "500 Server Error for url: https://api.leadfeeder.com/accounts",
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, other_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)

    def test_get_schemas_marks_only_date_filtered_endpoints_incremental(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert set(schemas) == set(ENDPOINTS)
        # Accounts has no server-side date filter -> full refresh only.
        assert schemas["accounts"].supports_incremental is False
        assert schemas["accounts"].supports_append is False
        # Leads and visits filter server-side on start_date/end_date -> incremental.
        for name in ("leads", "visits"):
            assert schemas[name].supports_incremental is True
            assert schemas[name].supports_append is True

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["leads"])
        assert [s.name for s in schemas] == ["leads"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @parameterized.expand(
        [
            (True, True, None),
            (
                False,
                False,
                "Unable to verify your Leadfeeder API token. Check that the token is correct and that Leadfeeder is reachable.",
            ),
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.source.validate_leadfeeder_credentials"
    )
    def test_validate_credentials(
        self, mock_return: bool, expected_valid: bool, expected_message: str | None, mock_validate: mock.MagicMock
    ) -> None:
        mock_validate.return_value = mock_return
        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("token")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is LeadfeederResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.source.leadfeeder_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "leads"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-06-01"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_token"] == "token"
        assert kwargs["endpoint"] == "leads"
        assert kwargs["start_date_config"] == "2024-01-01"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["db_incremental_field_last_value"] == "2024-06-01"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.source.leadfeeder_source")
    def test_source_for_pipeline_drops_watermark_when_not_incremental(self, mock_source: mock.MagicMock) -> None:
        # A stale watermark must not leak into a full-refresh run.
        config = LeadfeederSourceConfig(api_token="token")
        inputs = mock.MagicMock()
        inputs.schema_name = "accounts"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-06-01"

        self.source.source_for_pipeline(config, mock.MagicMock(), inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["db_incremental_field_last_value"] is None
        assert kwargs["start_date_config"] == ""

    def test_canonical_descriptions_cover_key_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions) == set(ENDPOINTS)
        assert "last_visit_date" in descriptions["leads"]["columns"]
        assert "started_at" in descriptions["visits"]["columns"]

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
