import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.debugbear.source import DebugbearSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.debugbear import (
    DebugbearSourceConfig,
)


class TestDebugbearSource:
    def setup_method(self) -> None:
        self.source = DebugbearSource()
        self.team_id = 123
        self.config = DebugbearSourceConfig(api_key="test-key")

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static endpoint catalog with no I/O, so the public docs table
        # catalog can render without a real credential.
        assert self.source.lists_tables_without_credentials is True

    def test_get_source_config_has_no_unreleased_flag(self) -> None:
        # A finished source must not stay hidden behind unreleasedSource.
        assert self.source.get_source_config.unreleasedSource is None

    @pytest.mark.parametrize(
        ("pattern", "message"),
        [
            ("401 Client Error", "401 Client Error: Unauthorized for url: https://www.debugbear.com/api/v1/projects"),
            ("403 Client Error", "403 Client Error: Forbidden for url: https://www.debugbear.com/api/v1/projects"),
        ],
    )
    def test_non_retryable_errors_match(self, pattern: str, message: str) -> None:
        errors = self.source.get_non_retryable_errors()
        assert pattern in errors
        assert any(p in message for p in errors)
