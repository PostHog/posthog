from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.bugsnag.settings import (
    BUGSNAG_ENDPOINTS,
    ENDPOINTS,
    BugsnagScope,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bugsnag.source import BugsnagSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bugsnag import (
    BugsnagSourceConfig,
)


class TestBugsnagSource:
    def setup_method(self) -> None:
        self.source = BugsnagSource()
        self.team_id = 1

    def test_generated_config_parses_auth_token(self) -> None:
        # Guards the hand-checked generated_configs.py edit: the form field must map to `auth_token`.
        config = BugsnagSourceConfig.from_dict({"auth_token": "tok_123"})
        assert config.auth_token == "tok_123"

    def test_get_schemas_lists_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_all_schemas_are_full_refresh(self) -> None:
        # Incremental isn't advertised until the server-side time-filter behavior is verified
        # against the live API, so every table ships full refresh only.
        for schema in self.source.get_schemas(MagicMock(), team_id=self.team_id):
            assert schema.supports_incremental is False, schema.name
            assert schema.supports_append is False, schema.name

    @parameterized.expand(
        [
            ("organizations", True),
            ("projects", True),
            ("errors", True),
            ("events", False),
            ("pivots", False),
            ("event_fields", False),
            ("trace_fields", False),
        ]
    )
    def test_should_sync_default(self, endpoint: str, expected_default: bool) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(MagicMock(), team_id=self.team_id)}
        assert schemas[endpoint].should_sync_default is expected_default

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=self.team_id, names=["errors", "projects"])
        assert {s.name for s in schemas} == {"errors", "projects"}

    def test_fan_out_children_carry_parent_id_in_primary_key(self) -> None:
        # Fan-out children aggregate rows from every parent, so the parent id injected into each row
        # must be part of the primary key — otherwise per-parent-unique ids collide table-wide and
        # seed duplicate rows that slow every subsequent merge.
        for config in BUGSNAG_ENDPOINTS.values():
            if config.scope is BugsnagScope.PER_ORG:
                assert "organization_id" in config.primary_keys, config.name
            elif config.scope is BugsnagScope.PER_PROJECT:
                assert "project_id" in config.primary_keys, config.name
