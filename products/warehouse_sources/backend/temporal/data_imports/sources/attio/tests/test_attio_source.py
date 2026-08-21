import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.attio.source import AttioSource


class TestAttioSource:
    def setup_method(self):
        self.source = AttioSource()

    def test_http_error_message_format_matches_pattern(self):
        """Verify that requests.HTTPError messages raised via raise_for_status on an Attio 400
        records/query response match the non-retryable pattern we rely on."""
        mock_response = requests.Response()
        mock_response.status_code = 400
        mock_response.url = "https://api.attio.com/v2/objects/users/records/query"
        mock_response.reason = "Bad Request"

        with pytest.raises(requests.HTTPError) as exc_info:
            mock_response.raise_for_status()

        error_msg = str(exc_info.value)
        non_retryable_errors = self.source.get_non_retryable_errors()

        assert any(pattern in error_msg for pattern in non_retryable_errors), (
            f"HTTPError message '{error_msg}' did not match any non-retryable pattern"
        )
