import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.codefresh.source import CodefreshSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.codefresh import (
    CodefreshSourceConfig,
)


class TestCodefreshSource:
    def setup_method(self) -> None:
        self.source = CodefreshSource()
        self.team_id = 123

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://g.codefresh.io/api/projects?limit=100&offset=0",),
            ("403 Client Error: Forbidden for url: https://g.codefresh.io/api/workflow?limit=100&page=1",),
        ]
    )
    def test_credential_errors_are_non_retryable(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='g.codefresh.io', port=443): Read timed out."),
            ("server_error", "500 Server Error: Internal Server Error for url: https://g.codefresh.io/api/projects"),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://g.codefresh.io/api/workflow"),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)

    @parameterized.expand(
        [
            ("valid", True, None, True),
            ("invalid", False, "Your Codefresh API key is invalid or has been revoked.", False),
        ]
    )
    def test_validate_credentials_plumbs_through(
        self, _name: str, inner_valid: bool, inner_error: str | None, expected_valid: bool
    ) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.codefresh.source.validate_codefresh_credentials",
            return_value=(inner_valid, inner_error),
        ) as mocked:
            valid, error = self.source.validate_credentials(CodefreshSourceConfig(api_key="t"), self.team_id)
        mocked.assert_called_once_with("t", schema_name=None)
        assert valid is expected_valid
        if not expected_valid:
            assert error == inner_error


if __name__ == "__main__":
    pytest.main([__file__])
