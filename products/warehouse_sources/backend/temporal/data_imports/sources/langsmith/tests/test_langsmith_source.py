import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.langsmith import (
    LangSmithSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.langsmith.langsmith import RETRYABLE_API_ERROR
from products.warehouse_sources.backend.temporal.data_imports.sources.langsmith.source import LangSmithSource


class TestLangSmithSource:
    def setup_method(self):
        self.source = LangSmithSource()
        self.team_id = 123
        self.config = LangSmithSourceConfig(api_key="key", host=None)

    def test_host_is_a_connection_host_field(self):
        # The key is sent to `host`; retargeting it must force re-entry of the key secret.
        assert self.source.connection_host_fields == ["host"]

    def test_validate_credentials_collapses_blank_host_and_forwards_team_id(self):
        config = LangSmithSourceConfig(api_key="key", host="")

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.langsmith.source.validate_langsmith_credentials",
            return_value=(True, None),
        ) as validate:
            result = self.source.validate_credentials(config, self.team_id)

        assert result == (True, None)
        # An empty host override collapses to None so the US-cloud default is used; team_id is
        # forwarded so the credential probe can SSRF-check the resolved host.
        validate.assert_called_once_with("key", None, self.team_id)

    @pytest.mark.parametrize(
        "host,expected_base_url",
        [
            (None, "https://api.smith.langchain.com"),
            ("https://eu.api.smith.langchain.com/", "https://eu.api.smith.langchain.com"),
        ],
    )
    def test_source_for_pipeline_resolves_base_url(self, host, expected_base_url):
        inputs = mock.MagicMock()
        inputs.schema_name = "runs"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-06-01T00:00:00Z"
        inputs.enabled_columns = ["id", "start_time"]
        config = LangSmithSourceConfig(api_key="key", host=host)

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.langsmith.source.langsmith_source"
        ) as langsmith_source:
            self.source.source_for_pipeline(config, mock.MagicMock(), inputs)

        _, kwargs = langsmith_source.call_args
        assert kwargs["endpoint"] == "runs"
        assert kwargs["base_url"] == expected_base_url
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-06-01T00:00:00Z"
        assert kwargs["enabled_columns"] == ["id", "start_time"]

    def test_source_for_pipeline_drops_incremental_value_on_full_refresh(self):
        inputs = mock.MagicMock()
        inputs.schema_name = "runs"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-06-01T00:00:00Z"

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.langsmith.source.langsmith_source"
        ) as langsmith_source:
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        _, kwargs = langsmith_source.call_args
        # A stale watermark must not leak into a full-refresh run.
        assert kwargs["db_incremental_field_last_value"] is None

    def test_rejected_request_is_non_retryable(self):
        # A 4xx means LangSmith rejected the request we built, so every retry re-sends the same
        # query for the whole activity budget and stores the raw requests error for the customer.
        non_retryable = self.source.get_non_retryable_errors()
        message = non_retryable["400 Client Error"]
        assert message is not None
        assert "Host field" in message

    @pytest.mark.parametrize(
        "observed_error",
        [
            "HTTPSConnectionPool(host='api.smith.langchain.com', port=443): Max retries exceeded with "
            'url: /api/v1/runs/query (Caused by ReadTimeoutError("HTTPSConnectionPool('
            "host='api.smith.langchain.com', port=443): Read timed out. (read timeout=60)\"))",
            f"{RETRYABLE_API_ERROR}: status=429, url=https://api.smith.langchain.com/api/v1/runs/query",
            "('Connection aborted.', ConnectionResetError(104, 'Connection reset by peer'))",
            '("Connection broken: IncompleteRead(1048576 bytes read, 4194304 more expected)", '
            "IncompleteRead(1048576 bytes read, 4194304 more expected))",
        ],
    )
    def test_exhausted_inline_retries_are_classified_retryable(self, observed_error):
        # `_fetch_page` retries a read timeout, a 429/5xx, and a dropped connection itself, and
        # Temporal then retries the activity from the saved pagination checkpoint. The failure is
        # self-recovering, so it must match here to be logged at warning instead of reaching error
        # tracking. The last two cases carry no urllib3 wrapper: the shared retry policy skips the
        # runs/query POST, and a drop while `_read_capped_body` streams the body happens after the
        # headers arrive.
        assert any(pattern in observed_error for pattern in self.source.get_retryable_errors())
