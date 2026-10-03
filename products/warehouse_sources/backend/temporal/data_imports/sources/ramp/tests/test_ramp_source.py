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
