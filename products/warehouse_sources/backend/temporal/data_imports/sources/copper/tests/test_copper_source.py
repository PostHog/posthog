import pytest
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.copper.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.copper.source import CopperSource


def _config() -> MagicMock:
    config = MagicMock()
    config.api_key = "key"
    config.user_email = "user@example.com"
    return config


class TestCopperSource:
    def setup_method(self):
        self.source = CopperSource()

    def test_get_schemas_lists_all_endpoints(self):
        schemas = self.source.get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "endpoint,expected_incremental",
        [
            ("people", True),
            ("companies", True),
            ("opportunities", True),
            ("users", False),
            ("pipelines", False),
            ("loss_reasons", False),
        ],
    )
    def test_get_schemas_incremental_support(self, endpoint, expected_incremental):
        schemas = {s.name: s for s in self.source.get_schemas(_config(), team_id=1)}
        schema = schemas[endpoint]
        assert schema.supports_incremental is expected_incremental
        assert schema.supports_append is expected_incremental
        if expected_incremental:
            assert {f["field"] for f in schema.incremental_fields} == {"date_modified", "date_created"}
        else:
            assert schema.incremental_fields == []

    def test_get_schemas_filters_by_names(self):
        schemas = self.source.get_schemas(_config(), team_id=1, names=["people"])
        assert [s.name for s in schemas] == ["people"]
