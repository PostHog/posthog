import pytest

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.codescene.source import CodesceneSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.codescene import (
    CodesceneSourceConfig,
)


class TestCodesceneSource:
    def setup_method(self) -> None:
        self.source = CodesceneSource()
        self.team_id = 123
        self.config = CodesceneSourceConfig(api_token="cs-token", base_url=None)

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Codescene"
        assert config.label == "CodeScene"
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/codescene.png"
        # The source ships visible — a truthy unreleasedSource hides it from every user.
        assert not config.unreleasedSource

    def test_connection_host_fields(self) -> None:
        assert self.source.connection_host_fields == ["base_url"]

    @pytest.mark.parametrize(
        "observed_error,expect_match",
        [
            ("401 Client Error: Unauthorized for url: https://api.codescene.io/v2/projects", True),
            ("403 Client Error: Forbidden for url: https://api.codescene.io/v2/projects", True),
            ("500 Server Error: Internal Server Error for url: https://api.codescene.io/v2/projects", False),
        ],
    )
    def test_non_retryable_errors_match_auth_failures_only(self, observed_error: str, expect_match: bool) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable) is expect_match
