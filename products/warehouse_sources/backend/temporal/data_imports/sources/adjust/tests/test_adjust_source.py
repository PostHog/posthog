import pytest
from unittest import mock

import requests

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.adjust.adjust import (
    AdjustCredentialsError,
    AdjustResumeConfig,
    AdjustRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.adjust.settings import ADJUST_REPORTS, ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.adjust.source import AdjustSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.adjust import AdjustSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.adjust.source"


class TestAdjustSource:
    def setup_method(self) -> None:
        self.source = AdjustSource()
        self.team_id = 123
        self.config = AdjustSourceConfig(api_token="adjust-token", app_tokens="abc123")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.ADJUST

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Adjust"
        assert config.label == "Adjust"
        assert config.category == DataWarehouseSourceCategory.ADVERTISING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/adjust"
        assert [field.name for field in config.fields] == ["api_token", "app_tokens"]

    def test_source_is_released(self) -> None:
        # A truthy unreleasedSource hides the connector from users entirely.
        assert not self.source.get_source_config.unreleasedSource

    def test_api_token_field_is_a_secret_password(self) -> None:
        field = next(f for f in self.source.get_source_config.fields if f.name == "api_token")
        assert isinstance(field, SourceFieldInputConfig)
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.required is True
        assert field.secret is True

    def test_app_tokens_field_is_optional_and_not_secret(self) -> None:
        field = next(f for f in self.source.get_source_config.fields if f.name == "app_tokens")
        assert isinstance(field, SourceFieldInputConfig)
        assert field.required is False
        assert field.secret is False

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas iterates a static report catalog with no I/O — safe for public docs.
        assert self.source.lists_tables_without_credentials is True

    def test_api_docs_url_is_https(self) -> None:
        assert self.source.api_docs_url is not None
        assert self.source.api_docs_url.startswith("https://")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://automate.adjust.com/reports-service/report?dimensions=day",
            "403 Client Error: Forbidden for url: https://automate.adjust.com/reports-service/report",
            "400 Client Error: Bad Request for url: https://automate.adjust.com/reports-service/report — Unknown metric",
            "404 Client Error: Not Found for url: https://automate.adjust.com/reports-service/report",
        ],
    )
    def test_permanent_failures_are_non_retryable(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "observed_error",
        [
            "429 Client Error: Too Many Requests for url: https://automate.adjust.com/reports-service/report",
            "Adjust API error (retryable): status=503, url=https://automate.adjust.com/reports-service/report",
        ],
    )
    def test_throttles_and_5xx_stay_retryable(self, observed_error: str) -> None:
        assert not any(key in observed_error for key in self.source.get_non_retryable_errors())

    def test_get_schemas_covers_every_report(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_every_report_is_incremental_on_day(self) -> None:
        # date_period is a real server-side filter, so every report can sync incrementally on day.
        for schema in self.source.get_schemas(self.config, self.team_id):
            assert schema.supports_incremental is True
            assert [field["field"] for field in schema.incremental_fields] == ["day"]

    def test_get_schemas_carries_descriptions(self) -> None:
        by_name = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        assert all(schema.description for schema in by_name.values())

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["country_report"])
        assert [schema.name for schema in schemas] == ["country_report"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @mock.patch(f"{_SOURCE_MODULE}.validate_adjust_credentials")
    def test_validate_credentials_success(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = True

        assert self.source.validate_credentials(self.config, self.team_id) == (True, None)
        mock_validate.assert_called_once_with("adjust-token", "abc123")

    @mock.patch(f"{_SOURCE_MODULE}.validate_adjust_credentials")
    def test_validate_credentials_surfaces_the_specific_rejection(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.side_effect = AdjustCredentialsError("Adjust rejected the API token.")

        is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert message == "Adjust rejected the API token."

    @pytest.mark.parametrize(
        "raised",
        [AdjustRetryableError("status=503"), requests.ConnectionError("boom"), requests.ReadTimeout("slow")],
    )
    @mock.patch(f"{_SOURCE_MODULE}.validate_adjust_credentials")
    def test_transient_failures_are_not_reported_as_bad_credentials(
        self, mock_validate: mock.MagicMock, raised: Exception
    ) -> None:
        mock_validate.side_effect = raised

        is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert message is not None
        assert "temporary rate-limit or network issue" in message

    def test_get_resumable_source_manager_binds_the_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is AdjustResumeConfig

    @mock.patch(f"{_SOURCE_MODULE}.adjust_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "campaign_report"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-06-01"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_token"] == "adjust-token"
        assert kwargs["app_tokens"] == "abc123"
        assert kwargs["report"] == "campaign_report"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-06-01"

    @mock.patch(f"{_SOURCE_MODULE}.adjust_source")
    def test_source_for_pipeline_drops_watermark_when_not_incremental(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "daily_report"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-06-01"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        # A full refresh must not inherit a stale watermark and silently skip history.
        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_cover_every_report(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions) == set(ENDPOINTS)

    @pytest.mark.parametrize("report", sorted(ADJUST_REPORTS))
    def test_canonical_descriptions_document_the_primary_key_columns(self, report: str) -> None:
        # The key columns are what a user joins on, so they must not fall through to LLM guessing.
        columns = self.source.get_canonical_descriptions()[report]["columns"]
        assert set(ADJUST_REPORTS[report].primary_keys) <= set(columns)
