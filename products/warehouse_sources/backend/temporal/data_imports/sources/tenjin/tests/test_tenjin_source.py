import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tenjin import TenjinSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tenjin.settings import TENJIN_REPORTS
from products.warehouse_sources.backend.temporal.data_imports.sources.tenjin.source import TenjinSource
from products.warehouse_sources.backend.temporal.data_imports.sources.tenjin.tenjin import (
    TenjinCredentialsError,
    TenjinRetryableError,
)

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.tenjin.source"


class TestTenjinSource:
    def setup_method(self) -> None:
        self.source = TenjinSource()
        self.team_id = 123
        self.config = TenjinSourceConfig(api_key="tenjin-token")

    def test_source_is_released(self) -> None:
        # A truthy unreleasedSource hides the connector from users entirely.
        assert not self.source.get_source_config.unreleasedSource

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas iterates a static report catalog with no I/O — safe for public docs.
        assert self.source.lists_tables_without_credentials is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.tenjin.com/v2/reports/spend?start_date=2026-06-01",
            "403 Client Error: Forbidden for url: https://api.tenjin.com/v2/reports/spend",
            "400 Client Error: Bad Request for url: https://api.tenjin.com/v2/reports/ad_revenue",
        ],
    )
    def test_permanent_failures_are_non_retryable(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "observed_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.tenjin.com/v2/reports/spend",
            "Tenjin API error (retryable): status=503",
        ],
    )
    def test_throttles_and_5xx_stay_retryable(self, observed_error: str) -> None:
        assert not any(key in observed_error for key in self.source.get_non_retryable_errors())

    def test_every_report_is_incremental_on_date(self) -> None:
        # start_date/end_date is a real server-side filter, so every report can sync
        # incrementally on date.
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert len(schemas) == len(TENJIN_REPORTS)
        for schema in schemas:
            assert schema.supports_incremental is True
            assert [field["field"] for field in schema.incremental_fields] == ["date"]

    @mock.patch(f"{_SOURCE_MODULE}.validate_tenjin_credentials")
    def test_validate_credentials_success(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = True

        assert self.source.validate_credentials(self.config, self.team_id) == (True, None)
        mock_validate.assert_called_once_with("tenjin-token")

    @mock.patch(f"{_SOURCE_MODULE}.validate_tenjin_credentials")
    def test_validate_credentials_surfaces_the_specific_rejection(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.side_effect = TenjinCredentialsError("Tenjin rejected the access token.")

        is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert message == "Tenjin rejected the access token."

    @pytest.mark.parametrize(
        "raised",
        [TenjinRetryableError("status=503"), requests.ConnectionError("boom"), requests.ReadTimeout("slow")],
    )
    @mock.patch(f"{_SOURCE_MODULE}.validate_tenjin_credentials")
    def test_transient_failures_are_not_reported_as_bad_credentials(
        self, mock_validate: mock.MagicMock, raised: Exception
    ) -> None:
        mock_validate.side_effect = raised

        is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert message is not None
        assert "temporary rate-limit or network issue" in message

    @mock.patch(f"{_SOURCE_MODULE}.tenjin_source")
    def test_source_for_pipeline_drops_watermark_when_not_incremental(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "app_report"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-06-01"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        # A full refresh must not inherit a stale watermark and silently skip history.
        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    @pytest.mark.parametrize("report", sorted(TENJIN_REPORTS))
    def test_canonical_descriptions_document_the_primary_key_columns(self, report: str) -> None:
        # The key columns are what a user joins on, so they must not fall through to LLM guessing.
        columns = self.source.get_canonical_descriptions()[report]["columns"]
        assert set(TENJIN_REPORTS[report].primary_keys) <= set(columns)
