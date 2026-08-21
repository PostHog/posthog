from typing import Any

from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.honeycomb import (
    HoneycombSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.honeycomb.settings import (
    ENDPOINTS,
    HONEYCOMB_ENDPOINTS,
    HoneycombScope,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.honeycomb.source import HoneycombSource


class TestHoneycombSource:
    def setup_method(self) -> None:
        self.source = HoneycombSource()
        self.team_id = 1

    def test_generated_config_parses_fields(self) -> None:
        # Guards the generated_configs.py wiring: the form fields must map to `api_key` and
        # `region`, with the region defaulting to US for configs saved before the field existed.
        config = HoneycombSourceConfig.from_dict({"api_key": "hcaik_123"})
        assert config.api_key == "hcaik_123"
        assert config.region == "us"
        assert HoneycombSourceConfig.from_dict({"api_key": "k", "region": "eu"}).region == "eu"

    def test_get_schemas_lists_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_all_schemas_are_full_refresh(self) -> None:
        # Honeycomb's v1 config endpoints have no server-side timestamp filter, so advertising
        # incremental would silently re-walk history every run while claiming a delta sync.
        for schema in self.source.get_schemas(MagicMock(), team_id=self.team_id):
            assert schema.supports_incremental is False, schema.name
            assert schema.supports_append is False, schema.name

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=self.team_id, names=["datasets", "slos"])
        assert {s.name for s in schemas} == {"datasets", "slos"}

    def test_fan_out_children_carry_dataset_slug_in_primary_key(self) -> None:
        # Fan-out children aggregate rows from every dataset (and multi-dataset SLOs are listed
        # under each dataset they span), so the injected dataset slug must be part of the primary
        # key — otherwise per-dataset-unique ids collide table-wide and every merge multi-matches.
        for config in HONEYCOMB_ENDPOINTS.values():
            if config.scope in (HoneycombScope.PER_DATASET, HoneycombScope.PER_SLO):
                assert "dataset_slug" in config.primary_keys, config.name

    def test_canonical_description_keys_are_real_endpoints(self) -> None:
        # Canonical descriptions are keyed by schema name; a typo'd key would silently never apply.
        descriptions: dict[str, Any] = self.source.get_canonical_descriptions()
        assert set(descriptions) == set(ENDPOINTS)
        for endpoint, entry in descriptions.items():
            assert entry["description"], endpoint
