import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.easybill import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.easybill.source import EasybillSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.easybill import (
    EasybillSourceConfig,
)


class TestEasybillSourceClass:
    def setup_method(self) -> None:
        self.source = EasybillSource()
        self.config = EasybillSourceConfig(api_key="key")
        self.team_id = 1

    def test_only_documents_is_incremental(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["Documents"].supports_incremental is True
        assert [f["field"] for f in schemas["Documents"].incremental_fields] == ["edited_at"]
        for name, schema in schemas.items():
            if name != "Documents":
                assert schema.supports_incremental is False, name

    @parameterized.expand([("valid", True, (True, None)), ("invalid", False, (False, "Invalid easybill API key"))])
    def test_validate_credentials(self, _name: str, api_result: bool, expected: tuple[bool, str | None]) -> None:
        with mock.patch.object(source_module, "validate_easybill_credentials", return_value=api_result):
            assert self.source.validate_credentials(self.config, self.team_id) == expected


if __name__ == "__main__":
    pytest.main([__file__])
