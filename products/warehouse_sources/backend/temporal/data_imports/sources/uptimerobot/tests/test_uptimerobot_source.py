import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.uptimerobot import (
    UptimerobotSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.uptimerobot.source import UptimerobotSource


class TestUptimerobotSource:
    def setup_method(self):
        self.source = UptimerobotSource()
        self.team_id = 123
        self.config = UptimerobotSourceConfig(api_key="ur123-key")

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

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["monitors"])
        assert len(schemas) == 1
        assert schemas[0].name == "monitors"
