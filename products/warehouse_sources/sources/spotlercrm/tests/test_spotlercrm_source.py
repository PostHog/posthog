import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.spotlercrm import (
    SpotlerCRMSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.spotlercrm.source import SpotlerCRMSource


class TestSpotlerCRMSource:
    def setup_method(self) -> None:
        self.source = SpotlerCRMSource()
        self.config = SpotlerCRMSourceConfig(access_token="test-token")

    def test_auth_error_from_live_api_matches_non_retryable_pattern(self) -> None:
        # The live API answers 403 for a bad token (verified with curl); make sure the
        # HTTPError string requests raises for it maps to a non-retryable error.
        response = requests.Response()
        response.status_code = 403
        response.url = "https://apiv4.reallysimplesystems.com/accounts"
        response.reason = "Forbidden"

        with pytest.raises(requests.HTTPError) as exc_info:
            response.raise_for_status()

        non_retryable = self.source.get_non_retryable_errors()
        assert any(pattern in str(exc_info.value) for pattern in non_retryable)
