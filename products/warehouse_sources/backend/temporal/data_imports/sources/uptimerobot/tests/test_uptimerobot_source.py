import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.uptimerobot import (
    UptimerobotSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.uptimerobot.source import UptimerobotSource

_INCREMENTAL_ENDPOINTS = {"monitor_logs", "response_times"}
_FULL_REFRESH_ENDPOINTS = {"monitors", "alert_contacts", "maintenance_windows", "status_pages"}


class TestUptimerobotSource:
    def setup_method(self):
        self.source = UptimerobotSource()
        self.team_id = 123
        self.config = UptimerobotSourceConfig(api_key="ur123-key")

    @pytest.mark.parametrize(
        "observed_error",
        [
            # UptimeRobot signals a bad key in-body over HTTP 200; the transport raises this message.
            "UptimeRobot API key was rejected: api_key is invalid.",
            # A monitor-specific key hitting a scope it isn't granted (e.g. maintenance windows)
            # comes back as a raw HTTP 403, bypassing the in-body auth check entirely.
            "403 Client Error: Forbidden for url: https://api.uptimerobot.com/v2/getMWindows",
            "403 Client Error: Forbidden for url: https://api.uptimerobot.com/v2/getAlertContacts",
        ],
    )
    def test_non_retryable_errors_match_credential_failures(self, observed_error):
        # Mirrors the production matcher (`error_message_matches`), which is case-insensitive.
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert error_message_matches(observed_error, non_retryable_errors)
