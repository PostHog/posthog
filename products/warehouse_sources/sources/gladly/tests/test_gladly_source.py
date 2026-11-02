from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gladly import GladlySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gladly.source import GladlySource


class TestGladlySource:
    def setup_method(self):
        self.source = GladlySource()
        self.team_id = 123
        self.config = GladlySourceConfig(organization="myorg", agent_email="agent@x.com", api_token="token")

    def test_connection_host_fields_cover_organization(self):
        # The org subdomain and the domain together decide where the stored token gets sent.
        assert self.source.connection_host_fields == ["organization", "domain"]

    def test_a_missing_report_body_is_classified_retryable_with_exhaustion_copy(self):
        retryable = self.source.get_retryable_errors()
        exhausted = self.source.get_retry_exhausted_errors()

        assert "Gladly returned no report" in retryable
        assert set(exhausted) <= retryable
        assert not any("Gladly returned no report" in key for key in self.source.get_non_retryable_errors())

    def test_a_report_gladly_never_served_stops_the_sync_instead_of_retrying(self):
        observed_error = (
            "Gladly report unavailable for this account: metricSet=ContactTimestampsReport returned "
            "an error body instead of a CSV on every attempt, and this table has never completed a "
            "sync. First line: ['Unexpected error occurred']"
        )
        message = self.source.get_non_retryable_errors()["Gladly report unavailable for this account"]

        assert any(key in observed_error for key in self.source.get_non_retryable_errors())
        assert not any(key in observed_error for key in self.source.get_retryable_errors())
        assert message is not None
        assert "gladly support" in message.lower()
