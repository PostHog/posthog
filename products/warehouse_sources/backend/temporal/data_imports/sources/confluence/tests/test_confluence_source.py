import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.confluence.source import ConfluenceSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.confluence import (
    ConfluenceSourceConfig,
)


class TestConfluenceSource:
    def setup_method(self) -> None:
        self.source = ConfluenceSource()
        self.team_id = 123
        self.config = ConfluenceSourceConfig(subdomain="acme", email="you@example.com", api_token="token")

    def test_connection_host_fields_includes_subdomain(self) -> None:
        # Changing the subdomain retargets where the API token is sent.
        assert self.source.connection_host_fields == ["subdomain"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://acme.atlassian.net/wiki/api/v2/spaces",
            "403 Client Error: Forbidden for url: https://acme.atlassian.net/wiki/api/v2/pages",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "500 Server Error for url: https://acme.atlassian.net/wiki/api/v2/spaces",
            "429 Client Error: Too Many Requests",
        ],
    )
    def test_non_retryable_errors_does_not_match_transient(self, other_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)
