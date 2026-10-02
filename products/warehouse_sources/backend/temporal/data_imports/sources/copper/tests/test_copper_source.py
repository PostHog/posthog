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
            ("activities", True),
            ("users", False),
            ("pipelines", False),
            ("pipeline_stages", False),
            ("lead_statuses", False),
            ("activity_types", False),
            ("custom_activity_types", False),
            ("loss_reasons", False),
            ("custom_field_definitions", False),
            ("tags", False),
            ("field_layouts", False),
            ("related_items", False),
        ],
    )
    def test_get_schemas_incremental_support(self, endpoint, expected_incremental):
        schemas = {s.name: s for s in self.source.get_schemas(_config(), team_id=1)}
        schema = schemas[endpoint]
        assert schema.supports_incremental is expected_incremental
        assert schema.supports_append is expected_incremental
        if not expected_incremental:
            assert schema.incremental_fields == []

    @pytest.mark.parametrize(
        "endpoint,expected_fields",
        [
            ("people", {"date_modified", "date_created"}),
            # Activities only filter on the activity date, so that is all we advertise.
            ("activities", {"activity_date"}),
        ],
    )
    def test_get_schemas_advertises_only_server_filterable_fields(self, endpoint, expected_fields):
        schemas = {s.name: s for s in self.source.get_schemas(_config(), team_id=1)}
        assert {f["field"] for f in schemas[endpoint].incremental_fields} == expected_fields

    def test_get_schemas_filters_by_names(self):
        schemas = self.source.get_schemas(_config(), team_id=1, names=["people"])
        assert [s.name for s in schemas] == ["people"]
