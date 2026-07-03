import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.attio.source import AttioSource


class TestAttioSource:
    def setup_method(self):
        self.source = AttioSource()

    @pytest.mark.parametrize(
        "pattern",
        [
            "401 Client Error: Unauthorized for url: https://api.attio.com",
            "403 Client Error: Forbidden for url: https://api.attio.com",
            "400 Client Error: Bad Request for url: https://api.attio.com/v2/objects/",
        ],
    )
    def test_non_retryable_errors_includes_pattern(self, pattern):
        errors = self.source.get_non_retryable_errors()

        assert pattern in errors

    @pytest.mark.parametrize(
        "error_message",
        [
            "400 Client Error: Bad Request for url: https://api.attio.com/v2/objects/users/records/query",
            "400 Client Error: Bad Request for url: https://api.attio.com/v2/objects/workspaces/records/query",
            "400 Client Error: Bad Request for url: https://api.attio.com/v2/objects/deals/records/query",
        ],
    )
    def test_attio_records_query_bad_request_is_non_retryable(self, error_message):
        """Attio returns 400 on /v2/objects/<slug>/records/query when the object slug is not enabled
        in the workspace. The request body is deterministic on our side, so retrying will not help."""
        non_retryable_errors = self.source.get_non_retryable_errors()

        assert any(pattern in error_message for pattern in non_retryable_errors), (
            f"Expected '{error_message}' to match a non-retryable pattern"
        )

    def test_other_attio_bad_request_is_retryable(self):
        """Only record-query 400s are treated as non-retryable; a 400 on an unrelated Attio endpoint
        should still flow through the normal retry path so genuine bugs surface."""
        error_message = "400 Client Error: Bad Request for url: https://api.attio.com/v2/notes"

        non_retryable_errors = self.source.get_non_retryable_errors()

        assert not any(pattern in error_message for pattern in non_retryable_errors), (
            f"'{error_message}' must not match a non-retryable pattern"
        )

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
