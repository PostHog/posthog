from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sumologic import (
    SumoLogicSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sumo_logic.source import SumoLogicSource


class TestSumoLogicSource:
    def setup_method(self) -> None:
        self.source = SumoLogicSource()
        self.team_id = 123
        self.config = SumoLogicSourceConfig(
            access_id="suAbc", access_key="sk-secret", deployment="eu", search_query="_sourceCategory=prod"
        )

    def test_deployment_is_a_connection_host_field(self) -> None:
        # Changing the deployment must force the secrets to be re-entered so they're never
        # sent to a freshly-specified host.
        assert self.source.connection_host_fields == ["deployment"]

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["monitors"])
        assert len(schemas) == 1
        assert schemas[0].name == "monitors"
