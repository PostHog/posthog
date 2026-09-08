import pytest

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kickscale import (
    KickscaleSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kickscale.settings import (
    ENDPOINTS,
    INCREMENTAL_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kickscale.source import KickscaleSource


class TestKickscaleSource:
    def setup_method(self) -> None:
        self.source = KickscaleSource()
        self.team_id = 123
        self.config = KickscaleSourceConfig(api_key="kickscale-key", client_id="kickscale-client")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Kickscale"
        assert config.label == "Kickscale"
        assert config.category == DataWarehouseSourceCategory.SALES
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/kickscale.png"
        # The source ships visible — a truthy unreleasedSource hides it from every user.
        assert not config.unreleasedSource

    def test_get_schemas_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_incremental_semantics(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        for name in ENDPOINTS:
            assert schemas[name].supports_incremental is True, name
            assert [f["field"] for f in schemas[name].incremental_fields] == ["date"], name
            assert schemas[name].default_incremental_lookback_seconds == INCREMENTAL_LOOKBACK_SECONDS, name

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["calls"])
        assert [s.name for s in schemas] == ["calls"]

    @pytest.mark.parametrize(
        "observed_error,expect_match",
        [
            ("403 Client Error: Forbidden for url: https://api.kickscale.com/meetings", True),
            ("401 Client Error: Unauthorized for url: https://api.kickscale.com/meetings", False),
            ("500 Server Error: Internal Server Error for url: https://api.kickscale.com/meetings", False),
        ],
    )
    def test_non_retryable_errors_match_auth_failures_only(self, observed_error: str, expect_match: bool) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable) is expect_match
