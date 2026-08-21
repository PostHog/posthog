import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import UNVERSIONED_API_VERSION
from products.warehouse_sources.backend.temporal.data_imports.sources.dbt.settings import DBT_API_VERSION_V3, ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.dbt.source import DbtSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dbt import DbtSourceConfig


class TestDbtSource:
    def setup_method(self):
        self.source = DbtSource()
        self.team_id = 123
        self.config = DbtSourceConfig(account_id="12345", api_token="dbtc_token")

    def test_connection_host_fields_cover_host_determining_fields(self):
        # These fields retarget where the stored token is sent (host and account path); missing one
        # lets an editor point the preserved credential at their own server or another account.
        assert self.source.connection_host_fields == ["region", "custom_base_url", "account_id"]

    def test_declares_v3_as_default_over_legacy_pin(self):
        # New sources are stamped with default_version; a revert here silently pins them to the
        # meaningless "v1" placeholder instead of dbt's recommended v3. The legacy label stays
        # supported so existing "v1"-pinned rows keep resolving to their unchanged wire behaviour.
        assert self.source.supported_versions == (UNVERSIONED_API_VERSION, DBT_API_VERSION_V3)
        assert self.source.default_version == DBT_API_VERSION_V3

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "endpoint, incremental",
        [
            ("accounts", False),
            ("projects", False),
            ("environments", False),
            ("jobs", False),
            ("users", False),
            ("runs", True),
        ],
    )
    def test_schema_incremental_support(self, endpoint, incremental):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas[endpoint].supports_incremental is incremental
        # The lookback re-pulls a window of rows each run, so merge is the only safe mode.
        assert schemas[endpoint].supports_append is False

    def test_users_not_synced_by_default(self):
        # Listing users needs permissions many read-only tokens lack; a default connection
        # must not enable a table whose first sync would 403.
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["users"].should_sync_default is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["runs"])
        assert len(schemas) == 1
        assert schemas[0].name == "runs"

    def test_get_schemas_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []
