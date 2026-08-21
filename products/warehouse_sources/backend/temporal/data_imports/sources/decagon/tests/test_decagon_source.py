from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.decagon.source import DecagonSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.decagon import (
    DecagonSourceConfig,
)


class TestDecagonSource:
    def setup_method(self) -> None:
        self.source = DecagonSource()
        self.team_id = 123
        self.config = DecagonSourceConfig(api_key="decagon-test-key")

    @parameterized.expand(
        [
            (
                "connection_error_wrapping_read_timeout",
                "HTTPSConnectionPool(host='api.decagon.ai', port=443): Max retries exceeded with url: "
                "/conversation/export (Caused by ReadTimeoutError(\"HTTPSConnectionPool(host='api.decagon.ai', "
                'port=443): Read timed out. (read timeout=60)"))',
            ),
            (
                "exhausted_retryable_status",
                "Decagon API error (retryable): status=503, url=https://api.decagon.ai/tag/all",
            ),
        ]
    )
    def test_retryable_errors_cover_exhausted_transient_failures(self, _name: str, error_msg: str) -> None:
        # fetch_page already retries these with backoff; once that budget exhausts they must
        # stay classified as retryable (self-recovering via Temporal) rather than tracked
        # exception noise.
        assert error_message_matches(error_msg, self.source.get_retryable_errors())

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.decagon.source.validate_decagon_credentials"
    )
    def test_validate_credentials(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = True
        assert self.source.validate_credentials(self.config, self.team_id) == (True, None)

        mock_validate.return_value = False
        is_valid, message = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is False
        assert message is not None

        mock_validate.assert_called_with(self.config.api_key)

    # The second case guards the null-out: a watermark left over from an earlier
    # incremental configuration must not window a sync that is no longer incremental,
    # or the full refresh silently drops every row older than the stale watermark.
