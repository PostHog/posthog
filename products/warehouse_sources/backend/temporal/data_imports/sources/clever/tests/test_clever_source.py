from unittest.mock import MagicMock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.clever.source import CleverSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clever import CleverSourceConfig


class TestCleverSource:
    def setup_method(self) -> None:
        self.source = CleverSource()
        self.config = CleverSourceConfig(bearer_token="test-token")

    def test_non_retryable_errors_match_requests_error_format(self) -> None:
        # The pipeline disables a source by substring-matching these keys against the raised
        # error; they must match the message `requests.raise_for_status` actually produces.
        response = MagicMock(spec=requests.Response)
        response.status_code = 401
        response.reason = "Unauthorized"
        response.url = "https://api.clever.com/v3.0/districts?limit=10000"
        error = requests.HTTPError(f"401 Client Error: Unauthorized for url: {response.url}", response=response)

        assert any(key in str(error) for key in self.source.get_non_retryable_errors())
