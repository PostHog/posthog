import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.heyreach.source import HeyReachSource


class TestHeyReachSourceErrorClassification:
    @pytest.mark.parametrize(
        ("status_code", "reason"),
        [
            (401, "Unauthorized"),
            (403, "Forbidden"),
        ],
    )
    def test_auth_http_errors_match_a_non_retryable_pattern(self, status_code: int, reason: str) -> None:
        # Verifies the raise_for_status message shape the patterns rely on, so a requests
        # formatting change or a wrong pattern prefix surfaces here instead of as an
        # endlessly retrying job.
        mock_response = requests.Response()
        mock_response.status_code = status_code
        mock_response.url = "https://api.heyreach.io/api/public/campaign/GetAll"
        mock_response.reason = reason

        with pytest.raises(requests.HTTPError) as exc_info:
            mock_response.raise_for_status()

        non_retryable_errors = HeyReachSource().get_non_retryable_errors()
        assert any(pattern in str(exc_info.value) for pattern in non_retryable_errors)

    def test_transient_server_errors_stay_retryable(self) -> None:
        error_message = (
            "500 Server Error: Internal Server Error for url: https://api.heyreach.io/api/public/campaign/GetAll"
        )

        non_retryable_errors = HeyReachSource().get_non_retryable_errors()
        assert not any(pattern in error_message for pattern in non_retryable_errors)
