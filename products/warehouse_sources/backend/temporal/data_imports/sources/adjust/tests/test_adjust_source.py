from datetime import date

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.adjust import adjust
from products.warehouse_sources.backend.temporal.data_imports.sources.adjust.source import AdjustSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.adjust import AdjustSourceConfig


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

    def test_validate_credentials_success(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert self.source.validate_credentials(self.config, self.team_id) == (True, None)

        assert network.requests_log[0].headers["authorization"] == "Bearer adjust-token"
        assert network.requests_log[0].param("app_token__in") == "abc123"

    @pytest.mark.parametrize(
        "response",
        [ScriptedResponse(status=503), ConnectionResetError("boom"), TimeoutError("slow")],
    )
    def test_transient_failures_are_not_reported_as_bad_credentials(self, response: ScriptedResponse | OSError) -> None:
        def answer(_request: RecordedRequest) -> ScriptedResponse:
            if isinstance(response, OSError):
                raise response
            return response

        with scripted_network(answer):
            is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert message is not None
        assert "temporary rate-limit or network issue" in message

    def test_source_for_pipeline_drops_watermark_when_not_incremental(self) -> None:
        with mock.patch.object(adjust, "_today", return_value=date(2024, 6, 30)):
            result = SourceDriver(self.source, self.config).run(
                "daily_report",
                always(ScriptedResponse(json={"rows": []})),
                db_incremental_field_last_value="2024-06-01",
            )

        # A full refresh must not inherit a stale watermark and silently skip history.
        assert result.raised is None
        assert result.requests[0].param("date_period") == "2022-07-01:2022-07-30"
