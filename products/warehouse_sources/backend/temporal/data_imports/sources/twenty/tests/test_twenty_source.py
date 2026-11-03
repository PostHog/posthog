from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.twenty import TwentySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.twenty.source import TwentySource


class TestTwentySource:
    def setup_method(self):
        self.source = TwentySource()
        self.team_id = 123
        self.config = TwentySourceConfig(api_key="tok", base_url=None)

    def test_connection_host_fields_force_secret_reentry(self):
        # The API key is sent to base_url, so retargeting it must re-require the key.
        assert self.source.connection_host_fields == ["base_url"]

    def test_retryable_errors_match_transient_database_error(self):
        # Twenty returns this as a 400, so the shared REST client's own retry loop never retries
        # it; this is what keeps the self-recovering failure out of error tracking as noise.
        observed_error = (
            "400 Client Error: Bad Request for url: https://api.twenty.com/rest/people"
            " | api error: code=TRANSIENT_DATABASE_ERROR"
        )
        retryable_errors = self.source.get_retryable_errors()
        assert any(key in observed_error for key in retryable_errors)
