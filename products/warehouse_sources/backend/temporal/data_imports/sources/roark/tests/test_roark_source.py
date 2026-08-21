from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.roark import RoarkSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.roark import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.roark.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.roark.settings import ENDPOINTS, ROARK_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.roark.source import RoarkSource


class TestRoarkSource:
    def setup_method(self) -> None:
        self.source = RoarkSource()
        self.team_id = 123

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static, no-I/O catalog, so public docs may render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_returns_every_endpoint_as_full_refresh(self) -> None:
        schemas = self.source.get_schemas(RoarkSourceConfig(api_key="k"), self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []
            assert schema.detected_primary_keys == ROARK_ENDPOINTS[schema.name].primary_keys

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(RoarkSourceConfig(api_key="k"), self.team_id, names=["call", "chat"])
        assert {s.name for s in schemas} == {"call", "chat"}

    @parameterized.expand([(True, True, None), (False, False, "Invalid Roark API key")])
    def test_validate_credentials(self, valid: bool, expected_ok: bool, expected_msg: str | None) -> None:
        with patch.object(source_module, "validate_roark_credentials", return_value=valid):
            ok, msg = self.source.validate_credentials(RoarkSourceConfig(api_key="k"), self.team_id)
        assert ok is expected_ok
        assert msg == expected_msg

    def test_canonical_descriptions_keys_match_endpoints(self) -> None:
        # Canonical descriptions are keyed by the schema/endpoint name get_schemas returns.
        assert self.source.get_canonical_descriptions() is CANONICAL_DESCRIPTIONS
        assert set(CANONICAL_DESCRIPTIONS).issubset(set(ENDPOINTS))

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        for table in tables:
            assert "Full refresh" in table["sync_methods"]
