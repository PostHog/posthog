import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gong import GongSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gong.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.gong.source import GongSource


class TestGongSource:
    def setup_method(self):
        self.source = GongSource()
        self.team_id = 123
        self.config = GongSourceConfig(access_key="key", access_key_secret="secret")

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_get_schemas_incremental_flags(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        # Only `calls` exposes a server-side timestamp filter.
        assert schemas["calls"].supports_incremental is True
        assert schemas["calls"].supports_append is True
        assert any(f["field"] == "started" for f in schemas["calls"].incremental_fields)

        for name in ("users", "scorecards", "workspaces"):
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["calls"])

        assert len(schemas) == 1
        assert schemas[0].name == "calls"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["nonexistent"])

        assert schemas == []

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "403 Client Error: Forbidden for url: https://api.klaviyo.com/api/accounts",
        ],
    )
    def test_non_retryable_errors_does_not_match_other_vendors(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)
