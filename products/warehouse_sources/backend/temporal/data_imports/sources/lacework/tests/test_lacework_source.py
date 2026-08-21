from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lacework import (
    LaceworkSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lacework.source import LaceworkSource

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.lacework.source"


class TestLaceworkSource:
    def setup_method(self) -> None:
        self.source = LaceworkSource()
        self.config = LaceworkSourceConfig(account_name="mycompany", key_id="KEY_ID", secret_key="secret")

    def test_only_alerts_supports_merge_sync(self) -> None:
        # Only alerts has a unique row id (alertId); merge sync on any other endpoint would
        # multi-match rows and corrupt the table.
        incremental = [s.name for s in self.source.get_schemas(self.config, team_id=1) if s.supports_incremental]
        assert incremental == ["alerts"]
