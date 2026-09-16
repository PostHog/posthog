from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zep import ZepSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.zep.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.zep.source import ZepSource


class TestZepSource:
    def setup_method(self) -> None:
        self.source = ZepSource()
        self.team_id = 7

    def test_get_schemas_returns_every_endpoint_as_full_refresh(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # Zep has no server-side timestamp filter, so nothing is incremental/append.
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=self.team_id, names=["threads"])
        assert [s.name for s in schemas] == ["threads"]

    @parameterized.expand([("valid", True, (True, None)), ("invalid", False, (False, "Invalid Zep API key"))])
    def test_validate_credentials(self, _name: str, probe_ok: bool, expected: tuple[bool, str | None]) -> None:
        config = ZepSourceConfig(api_key="z_test")
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.zep.source.validate_zep_credentials",
            return_value=probe_ok,
        ):
            assert self.source.validate_credentials(config, self.team_id) == expected

    def test_documented_tables_render_without_credentials(self) -> None:
        # lists_tables_without_credentials=True: get_schemas is a static catalog, so public docs
        # can render the table list with no live connection.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
