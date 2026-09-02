from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.concord import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.concord.source import ConcordSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.concord import (
    ConcordSourceConfig,
)


class TestConcordSourceClass:
    def setup_method(self):
        self.source = ConcordSource()
        self.team_id = 123

    def test_lists_tables_without_credentials(self):
        # get_schemas is a static catalog, so the public docs can render the table list
        assert self.source.lists_tables_without_credentials is True
        documented = {t["name"] for t in self.source.get_documented_tables()}
        assert "agreements" in documented

    def test_get_schemas_lists_all_endpoints(self):
        names = {s.name for s in self.source.get_schemas(ConcordSourceConfig(api_key="k"), self.team_id)}
        assert {"organizations", "agreements", "members", "folders", "clauses", "tags", "events"} <= names

    def test_get_schemas_name_filter(self):
        schemas = self.source.get_schemas(ConcordSourceConfig(api_key="k"), self.team_id, names=["agreements"])
        assert [s.name for s in schemas] == ["agreements"]

    @parameterized.expand(
        [
            ("agreements", True),
            ("events", True),
            ("members", False),
            ("folders", False),
            ("groups", False),
            ("tags", False),
        ]
    )
    def test_supports_incremental_only_where_server_filter_exists(self, endpoint, expected):
        schema = self.source.get_schemas(ConcordSourceConfig(api_key="k"), self.team_id, names=[endpoint])[0]
        assert schema.supports_incremental is expected

    def test_events_is_off_by_default_and_append(self):
        schema = self.source.get_schemas(ConcordSourceConfig(api_key="k"), self.team_id, names=["events"])[0]
        assert schema.should_sync_default is False
        assert schema.supports_append is True

    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    def test_validate_credentials(self, _name, underlying, expected_ok):
        with mock.patch.object(source_module, "validate_concord_credentials", return_value=underlying):
            ok, error = self.source.validate_credentials(
                ConcordSourceConfig(api_key="k", environment="production"), self.team_id
            )
        assert ok is expected_ok
        assert (error is None) is expected_ok
