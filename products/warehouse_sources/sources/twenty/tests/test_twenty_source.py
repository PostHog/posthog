from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.sources.twenty._config import TwentySourceConfig
from products.warehouse_sources.sources.twenty.source import TwentySource


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

    def test_non_retryable_errors_match_api_type_error(self):
        # Also a 400 with an `api error: code=...` body, but this one is a genuine bug on Twenty's
        # side (an unhandled exception while building the query), not a transient DB hiccup, so it
        # must stay out of `get_retryable_errors()` and instead stop the sync from retrying forever.
        observed_error = (
            "400 Client Error: Bad Request for url: https://api.twenty.com/rest/opportunities"
            " | api error: code=TypeError"
        )
        assert error_message_matches(observed_error, self.source.get_non_retryable_errors())
