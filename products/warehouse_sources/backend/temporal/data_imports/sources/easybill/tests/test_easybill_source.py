from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.easybill import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.easybill.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.easybill.source import EasybillSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.easybill import (
    EasybillSourceConfig,
)


class TestEasybillSourceClass:
    def setup_method(self) -> None:
        self.source = EasybillSource()
        self.config = EasybillSourceConfig(api_key="key")
        self.team_id = 1

    def test_no_unreleased_flag(self) -> None:
        # A finished source ships visible: unreleasedSource must not be set at all.
        assert self.source.get_source_config.unreleasedSource is None

    @parameterized.expand([("valid", True, (True, None)), ("invalid", False, (False, "Invalid easybill API key"))])
    def test_validate_credentials(self, _name: str, api_result: bool, expected: tuple[bool, str | None]) -> None:
        with mock.patch.object(source_module, "validate_easybill_credentials", return_value=api_result):
            assert self.source.validate_credentials(self.config, self.team_id) == expected


class TestCanonicalDescriptions:
    def test_keys_are_all_real_endpoints(self) -> None:
        # A canonical entry keyed by a name that isn't an endpoint would silently never render.
        descriptions: dict[str, Any] = EasybillSource().get_canonical_descriptions()
        assert set(descriptions).issubset(set(ENDPOINTS))
        assert "Documents" in descriptions


if __name__ == "__main__":
    pytest.main([__file__])
