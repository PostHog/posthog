from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.workday import (
    WorkdaySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.workday.settings import (
    ENDPOINTS,
    WORKDAY_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.workday.source import WorkdaySource

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.workday.source"


def _config() -> WorkdaySourceConfig:
    return WorkdaySourceConfig(
        hostname="wd2-impl-services1.workday.com",
        tenant="acme_pt1",
        client_id="client",
        client_secret="secret",
        refresh_token="refresh",
    )


class TestWorkdaySource:
    def setup_method(self) -> None:
        self.source = WorkdaySource()
        self.team_id = 123
        self.config = _config()

    def test_every_endpoint_has_a_primary_key(self) -> None:
        assert all(WORKDAY_ENDPOINTS[name].primary_key for name in ENDPOINTS)
