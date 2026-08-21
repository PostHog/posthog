import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.codemagic.source import CodemagicSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.codemagic import (
    CodemagicSourceConfig,
)


class TestCodemagicSource:
    def setup_method(self) -> None:
        self.source = CodemagicSource()
        self.team_id = 123
        self.config = CodemagicSourceConfig(api_token="test-token")

    @pytest.mark.parametrize(
        ("error_message", "expected_substring"),
        [
            ("401 Client Error: Unauthorized for url: https://api.codemagic.io/apps", "Invalid Codemagic API token"),
            ("Unauthorized for url: https://api.codemagic.io/builds", "Invalid Codemagic API token"),
        ],
    )
    def test_get_non_retryable_errors_matches_auth_failures(self, error_message: str, expected_substring: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        matched = next((msg for key, msg in non_retryable.items() if key in error_message), None)
        assert matched is not None
        assert expected_substring in matched
