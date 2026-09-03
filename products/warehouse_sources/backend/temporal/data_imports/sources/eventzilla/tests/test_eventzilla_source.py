import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.eventzilla import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.eventzilla.source import EventzillaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.eventzilla import (
    EventzillaSourceConfig,
)


class TestEventzillaSourceClass:
    def setup_method(self) -> None:
        self.source = EventzillaSource()

    def test_all_schemas_are_full_refresh_only(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=1)
        assert {s.name for s in schemas} == {"events", "categories", "users", "attendees", "transactions", "tickets"}
        # Eventzilla has no server-side updated-since filter, so nothing supports incremental/append.
        for schema in schemas:
            assert schema.supports_incremental is False, schema.name
            assert schema.supports_append is False, schema.name
            assert schema.incremental_fields == [], schema.name

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=1, names=["events", "attendees"])
        assert {s.name for s in schemas} == {"events", "attendees"}

    def test_fan_out_endpoints_carry_a_description(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(MagicMock(), team_id=1)}
        assert schemas["attendees"].description is not None
        assert schemas["events"].description is None

    @pytest.mark.parametrize("valid,expected", [(True, (True, None)), (False, (False, "Invalid Eventzilla API key"))])
    def test_validate_credentials(self, valid: bool, expected: tuple[bool, str | None]) -> None:
        config = EventzillaSourceConfig(api_key="key")
        with patch.object(source_module, "validate_eventzilla_credentials", return_value=valid):
            assert self.source.validate_credentials(config, team_id=1) == expected

    def test_documented_tables_render_without_credentials(self) -> None:
        # `lists_tables_without_credentials` is on, so public docs get the full static catalog.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == {
            "events",
            "categories",
            "users",
            "attendees",
            "transactions",
            "tickets",
        }
