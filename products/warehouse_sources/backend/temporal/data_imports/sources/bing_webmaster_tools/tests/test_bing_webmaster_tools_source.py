import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.bing_webmaster_tools.settings import (
    ENDPOINT_CONFIGS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bing_webmaster_tools.source import (
    BingWebmasterToolsSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bingwebmastertools import (
    BingWebmasterToolsSourceConfig,
)

_STATS_ENDPOINTS = [name for name, endpoint in ENDPOINT_CONFIGS.items() if endpoint.per_site]


class TestBingWebmasterToolsSource:
    def setup_method(self):
        self.source = BingWebmasterToolsSource()
        self.team_id = 123
        self.config = BingWebmasterToolsSourceConfig(api_key="test-key")

    @pytest.mark.parametrize(
        "error_message",
        [
            "Bing Webmaster Tools GetUserSites failed with status 400: InvalidApiKey",
            "Bing Webmaster Tools GetQueryStats failed with status 400: NotAuthorized",
            "401 Client Error: Unauthorized for url: https://ssl.bing.com/webmaster/api.svc/json/GetUserSites?apikey=REDACTED",
            "400 Client Error: Bad Request for url: https://ssl.bing.com/webmaster/api.svc/json/GetQueryStats?apikey=REDACTED",
        ],
    )
    def test_non_retryable_errors_cover_credential_failures(self, error_message):
        assert error_message_matches(error_message, self.source.get_non_retryable_errors())

    def test_throttling_faults_stay_retryable(self):
        # A throttling fault must be retried by Temporal, not permanently fail the sync.
        message = "Bing Webmaster Tools GetQueryStats failed with status 429: ThrottleUser"

        assert not error_message_matches(message, self.source.get_non_retryable_errors())
