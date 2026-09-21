import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.okta import OktaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.okta.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.okta.source import OktaSource


class TestOktaSource:
    def setup_method(self):
        self.source = OktaSource()
        self.team_id = 123
        self.config = OktaSourceConfig(okta_domain="example.okta.com", api_key="00token")

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "endpoint, incremental",
        [
            ("users", True),
            ("groups", True),
            ("applications", False),
            ("logs", True),
            ("group_rules", False),
            ("user_types", False),
        ],
    )
    def test_schema_incremental_support(self, endpoint, incremental):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas[endpoint].supports_incremental is incremental
        assert schemas[endpoint].supports_append is incremental

    def test_logs_schema_has_lookback_description(self):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert "90 days" in (schemas["logs"].description or "")

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["users"])
        assert len(schemas) == 1
        assert schemas[0].name == "users"

    def test_get_schemas_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []
