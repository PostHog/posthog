from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.snyk import SnykSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.snyk.settings import SNYK_ENDPOINTS, SnykScope
from products.warehouse_sources.backend.temporal.data_imports.sources.snyk.source import SnykSource


class TestSnykSource:
    def setup_method(self) -> None:
        self.source = SnykSource()
        self.team_id = 1

    def test_generated_config_parses_fields(self) -> None:
        # Guards the generated-config round trip: form fields must map to config attributes.
        config = SnykSourceConfig.from_dict({"api_token": "tok_123"})
        assert config.api_token == "tok_123"
        assert config.region == "us"
        assert config.organization_id is None

    def test_fan_out_children_carry_organization_id_in_primary_key(self) -> None:
        # Fan-out children aggregate rows from every org, so the injected org id must be part of
        # the primary key — otherwise per-org id collisions would seed duplicate rows that slow
        # every subsequent merge.
        for config in SNYK_ENDPOINTS.values():
            if config.scope is SnykScope.PER_ORG:
                assert "organization_id" in config.primary_keys, config.name
