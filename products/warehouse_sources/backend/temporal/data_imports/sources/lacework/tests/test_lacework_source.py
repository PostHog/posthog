from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lacework import (
    LaceworkSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lacework.settings import (
    ENDPOINTS,
    LACEWORK_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lacework.source import LaceworkSource

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.lacework.source"


class TestLaceworkSource:
    def setup_method(self) -> None:
        self.source = LaceworkSource()
        self.config = LaceworkSourceConfig(account_name="mycompany", key_id="KEY_ID", secret_key="secret")

    def test_account_name_is_a_connection_host_field(self) -> None:
        # Retargeting the account (and therefore the host the secret is sent to) must force the
        # editor to re-enter credentials.
        assert self.source.connection_host_fields == ["account_name"]

    def test_get_schemas_covers_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1)
        assert [s.name for s in schemas] == list(ENDPOINTS)

    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_get_schemas_flags_match_endpoint_settings(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, team_id=1) if s.name == endpoint)
        endpoint_config = LACEWORK_ENDPOINTS[endpoint]
        assert schema.supports_incremental == endpoint_config.supports_incremental
        assert schema.supports_append == endpoint_config.supports_append
        assert [f["field"] for f in schema.incremental_fields] == [
            f["field"] for f in endpoint_config.incremental_fields
        ]

    def test_only_alerts_supports_merge_sync(self) -> None:
        # Only alerts has a unique row id (alertId); merge sync on any other endpoint would
        # multi-match rows and corrupt the table.
        incremental = [s.name for s in self.source.get_schemas(self.config, team_id=1) if s.supports_incremental]
        assert incremental == ["alerts"]

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1, names=["alerts", "audit_logs"])
        assert {s.name for s in schemas} == {"alerts", "audit_logs"}
