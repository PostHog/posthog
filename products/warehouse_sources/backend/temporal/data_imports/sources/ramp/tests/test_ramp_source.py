import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ramp import RampSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.ramp.source import RampSource


class TestRampSource:
    def setup_method(self):
        self.source = RampSource()
        self.team_id = 123
        self.config = RampSourceConfig(environment="production", client_id="cid", client_secret="sec")

    def test_environment_is_a_connection_host_field(self):
        # Changing environment retargets where the stored client secret is sent, so it must force
        # re-entering secrets.
        assert self.source.connection_host_fields == ["environment"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            # Permanent OAuth2 token-exchange failures carry the framework's stable marker.
            "HTTP 401 from the OAuth2 token endpoint: invalid_client [oauth2_token_config_error]",
            "HTTP 400 from the OAuth2 token endpoint: invalid_scope [oauth2_token_config_error]",
            "403 Client Error: Forbidden for url: https://api.ramp.com/developer/v1/transactions",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "500 Server Error for url: https://api.ramp.com/developer/v1/transactions",
            # Mid-sync 401s on data endpoints are handled by token re-mint.
            "401 Client Error: Unauthorized for url: https://api.ramp.com/developer/v1/transactions",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "observed_error",
        [
            "Tunnel connection failed: 429 Too Many Requests",
            "HTTPSConnectionPool(host='api.ramp.com', port=443): Max retries exceeded with url: "
            "/developer/v1/token (Caused by ProxyError('Cannot connect to proxy.', "
            "OSError('Tunnel connection failed: 429 Too Many Requests')))",
        ],
    )
    def test_token_mint_proxy_tunnel_429_is_retryable(self, observed_error):
        # PostHog's own egress proxy throttling the OAuth token-mint CONNECT tunnel is transient
        # and self-recovering on Temporal's activity retry, so it must stay out of error tracking
        # as noise rather than mint a fresh issue per burst.
        retryable_errors = self.source.get_retryable_errors()
        assert any(pattern in observed_error for pattern in retryable_errors)

    def test_token_mint_proxy_auth_rejection_stays_reportable(self):
        # A 407 shares the "Cannot connect to proxy." wording but is a deterministic proxy-auth
        # rejection that repeats on every attempt, not a transient throttling burst — it must not
        # be swallowed by the 429 tunnel pattern.
        observed_error = (
            "Caused by ProxyError('Cannot connect to proxy.', OSError('Tunnel connection failed: "
            "407 Proxy Authentication Required'))"
        )
        retryable_errors = self.source.get_retryable_errors()
        assert not any(pattern in observed_error for pattern in retryable_errors)
