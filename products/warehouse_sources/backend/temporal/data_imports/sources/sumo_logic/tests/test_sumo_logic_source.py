from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sumologic import (
    SumoLogicSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sumo_logic.settings import ENDPOINTS
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

    def test_get_schemas_returns_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_only_logs_is_incremental(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["logs"].supports_incremental is True
        assert schemas["logs"].supports_append is True
        assert schemas["logs"].incremental_fields == [
            {
                "label": "message_time",
                "type": "datetime",
                "field": "message_time",
                "field_type": "datetime",
            }
        ]

        for name in set(ENDPOINTS) - {"logs"}:
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["monitors"])
        assert len(schemas) == 1
        assert schemas[0].name == "monitors"
