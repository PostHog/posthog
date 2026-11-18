from products.warehouse_sources.sources.fusionauth._config import FusionAuthSourceConfig
from products.warehouse_sources.sources.fusionauth.source import FusionAuthSource


class TestFusionAuthSource:
    def setup_method(self):
        self.source = FusionAuthSource()
        self.team_id = 123
        self.config = FusionAuthSourceConfig(base_url="https://auth.example.com", api_key="00token")

    def test_connection_host_fields(self):
        assert self.source.connection_host_fields == ["base_url"]

    def test_non_retryable_errors_recognizes_report_endpoint_forbidden(self):
        # A tenant-scoped key gets a 403 on every report request, never a transient one, so this
        # must be classified non-retryable rather than retried to exhaustion.
        message = (
            "403 Client Error: Forbidden for url: https://auth.example.com/api/report/monthly-active-user"
            "?start=0&end=1795036986052"
        )
        assert any(pattern in message for pattern in self.source.get_non_retryable_errors())
