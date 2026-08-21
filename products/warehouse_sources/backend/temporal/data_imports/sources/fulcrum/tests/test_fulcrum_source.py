import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.fulcrum import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.fulcrum.source import FulcrumSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.fulcrum import (
    FulcrumSourceConfig,
)


class TestFulcrumSourceClass:
    def setup_method(self) -> None:
        self.source = FulcrumSource()
        self.config = FulcrumSourceConfig(api_token="token")
        self.team_id = 1

    def test_only_records_is_incremental(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["records"].supports_incremental is True
        assert [f["field"] for f in schemas["records"].incremental_fields] == ["updated_at"]
        for name, schema in schemas.items():
            if name != "records":
                assert schema.supports_incremental is False, name

    @parameterized.expand([("valid", True, (True, None)), ("invalid", False, (False, "Invalid Fulcrum API token"))])
    def test_validate_credentials(self, _name: str, api_result: bool, expected: tuple[bool, str | None]) -> None:
        with mock.patch.object(source_module, "validate_fulcrum_credentials", return_value=api_result):
            assert self.source.validate_credentials(self.config, self.team_id) == expected


if __name__ == "__main__":
    pytest.main([__file__])
