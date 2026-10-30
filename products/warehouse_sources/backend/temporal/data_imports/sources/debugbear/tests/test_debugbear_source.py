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
            (
                "DebugBear rejected the RUM metrics request",
                "DebugBear rejected the RUM metrics request for project 1 with a 400 error — "
                "Real User Monitoring is likely not set up for this project.",
            ),
        ],
    )
    def test_non_retryable_errors_match(self, pattern: str, message: str) -> None:
        errors = self.source.get_non_retryable_errors()
        assert pattern in errors
        assert any(p in message for p in errors)

    @pytest.mark.parametrize(
        "message",
        [
            # DebugBear sits behind Cloudflare; a persistent edge/origin blip surfaces as a raw
            # 52x after the transport's own retries are exhausted.
            "530 Server Error: <none> for url: https://www.debugbear.com/api/v1/projects",
            "502 Server Error: Bad Gateway for url: https://www.debugbear.com/api/v1/projects",
            "503 Server Error: Service Unavailable for url: https://www.debugbear.com/api/v1/projects",
            "429 Client Error: Too Many Requests for url: https://www.debugbear.com/api/v1/projects",
        ],
    )
    def test_retryable_errors_match(self, message: str) -> None:
        errors = self.source.get_retryable_errors()
        assert any(p in message for p in errors)

    @pytest.mark.parametrize(
        "message",
        [
            "401 Client Error: Unauthorized for url: https://www.debugbear.com/api/v1/projects",
            "403 Client Error: Forbidden for url: https://www.debugbear.com/api/v1/projects",
        ],
    )
    def test_retryable_errors_do_not_match_client_errors(self, message: str) -> None:
        errors = self.source.get_retryable_errors()
        assert not any(p in message for p in errors)
