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

    def test_get_source_config_has_no_unreleased_flag(self) -> None:
        # A finished source ships visible — this is the one thing that must never regress.
        assert self.source.get_source_config.unreleasedSource is None

    def test_get_schemas_are_full_refresh_only(self) -> None:
        # Codemagic has no documented server-side timestamp filter on any endpoint.
        schemas = self.source.get_schemas(self.config, self.team_id)
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.incremental_fields == []

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
