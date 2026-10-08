import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.adjust.adjust import (
    AdjustCredentialsError,
    AdjustRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.adjust.source import AdjustSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.adjust import AdjustSourceConfig

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.adjust.source"


class TestAdjustSource:
    def setup_method(self) -> None:
        self.source = AdjustSource()
        self.team_id = 123
        self.config = AdjustSourceConfig(api_token="adjust-token", app_tokens="abc123")

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas iterates a static report catalog with no I/O — safe for public docs.
        assert self.source.lists_tables_without_credentials is True

    def test_api_docs_url_is_https(self) -> None:
        assert self.source.api_docs_url is not None
        assert self.source.api_docs_url.startswith("https://")

    def test_exhausted_connection_pool_error_is_classified_retryable(self) -> None:
        # Matches the message urllib3 raises once the tracked session's own GET retries
        # (read timeouts, connection failures) exhaust — keeps this transient, self-recovering
        # failure out of error tracking instead of reaching `logger.aexception`.
        observed_error = (
            "HTTPSConnectionPool(host='automate.adjust.com', port=443): Max retries exceeded with "
            'url: /reports-service/report?dimensions=day (Caused by ReadTimeoutError("HTTPSConnectionPool'
            "(host='automate.adjust.com', port=443): Read timed out. (read timeout=300)\"))"
        )
        assert any(key in observed_error for key in self.source.get_retryable_errors())

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

    @mock.patch(f"{_SOURCE_MODULE}.adjust_source")
    def test_source_for_pipeline_drops_watermark_when_not_incremental(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "daily_report"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-06-01"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        # A full refresh must not inherit a stale watermark and silently skip history.
        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
