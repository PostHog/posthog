from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.fulcrum import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.fulcrum.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.fulcrum.source import FulcrumSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.fulcrum import (
    FulcrumSourceConfig,
)


class TestFulcrumSourceClass:
    def setup_method(self) -> None:
        self.source = FulcrumSource()
        self.config = FulcrumSourceConfig(api_token="token")
        self.team_id = 1

    def test_documented_tables_render_without_credentials(self) -> None:
        # lists_tables_without_credentials must expose the static catalog for public docs, with the
        # curated record description flowing through.
        assert self.source.lists_tables_without_credentials is True
        tables = {t["name"]: t for t in self.source.get_documented_tables()}
        assert set(tables) == set(ENDPOINTS)
        assert tables["records"]["description"]
        assert tables["photos"]["primary_keys"] == []  # detected keys only populated at sync time

    @parameterized.expand([("valid", True, (True, None)), ("invalid", False, (False, "Invalid Fulcrum API token"))])
    def test_validate_credentials(self, _name: str, api_result: bool, expected: tuple[bool, str | None]) -> None:
        with mock.patch.object(source_module, "validate_fulcrum_credentials", return_value=api_result):
            assert self.source.validate_credentials(self.config, self.team_id) == expected


class TestCanonicalDescriptions:
    def test_keys_are_all_real_endpoints(self) -> None:
        # A canonical entry keyed by a name that isn't an endpoint would silently never render.
        descriptions: dict[str, Any] = FulcrumSource().get_canonical_descriptions()
        assert set(descriptions).issubset(set(ENDPOINTS))
        assert "records" in descriptions


if __name__ == "__main__":
    pytest.main([__file__])
