import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.uptimerobot import (
    UptimerobotSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.uptimerobot.settings import ENDPOINTS
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

    @pytest.mark.parametrize(
        "other_error",
        [
            "UptimeRobot API error (retryable): status=429, method=getMonitors",
            "UptimeRobot API error (invalid_parameter): offset is invalid.",
            "HTTPSConnectionPool(host='api.uptimerobot.com', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "error_message",
        [
            "UptimeRobot API error (retryable): status=429, method=getMonitors",
            "UptimeRobot API error (retryable): status=500, method=getMonitors",
            "UptimeRobot API error (retryable): status=503, method=getAlertContacts",
        ],
    )
    def test_retryable_errors_match_exhausted_backoff(self, error_message):
        # _post already retries 429/5xx internally with backoff; once those attempts are
        # exhausted, this must stay classified as retryable so it doesn't get tracked as noise.
        retryable_errors = self.source.get_retryable_errors()
        assert any(pattern in error_message for pattern in retryable_errors)

    def test_get_schemas_match_endpoints_with_correct_sync_modes(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for name in _INCREMENTAL_ENDPOINTS:
            assert schemas[name].supports_incremental is True
            assert schemas[name].supports_append is True
            assert [f["field"] for f in schemas[name].incremental_fields] == ["datetime"]
        for name in _FULL_REFRESH_ENDPOINTS:
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["monitors"])
        assert len(schemas) == 1
        assert schemas[0].name == "monitors"

    def test_lists_tables_without_credentials_publishes_catalog(self):
        # Static endpoint catalog (no I/O) — the public docs table list should render.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)
