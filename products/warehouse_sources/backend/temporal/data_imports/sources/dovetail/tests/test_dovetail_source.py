from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, ReleaseStatus
from products.warehouse_sources.backend.temporal.data_imports.sources.dovetail.source import DovetailSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dovetail import (
    DovetailSourceConfig,
)


class TestDovetailSource:
    def setup_method(self) -> None:
        self.source = DovetailSource()
        self.team_id = 123
        self.config = DovetailSourceConfig(api_key="dovetail-key")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Dovetail"
        assert config.label == "Dovetail"
        assert config.category == DataWarehouseSourceCategory.PRODUCTIVITY
        assert config.releaseStatus == ReleaseStatus.BETA
        # The source ships visible: unreleasedSource hides the connector from every user.
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/dovetail.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/dovetail"
