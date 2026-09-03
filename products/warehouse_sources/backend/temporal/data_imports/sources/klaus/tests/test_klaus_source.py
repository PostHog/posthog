from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.klaus import KlausSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.klaus.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.klaus.source import KlausSource

INCREMENTAL_ENDPOINTS = {"reviews", "autoqa_reviews", "autoqa_ratings", "csat", "calibration_sessions"}
FULL_REFRESH_ENDPOINTS = {"users", "workspaces", "quizzes", "scorecards", "disputes"}


class TestKlausSource:
    def setup_method(self) -> None:
        self.source = KlausSource()
        self.team_id = 123
        self.config = KlausSourceConfig(subdomain="acme", api_token="test-token")

    def test_subdomain_is_a_connection_host_field(self) -> None:
        # Changing the subdomain retargets where the stored token is sent, so it must
        # force the token to be re-entered.
        assert self.source.connection_host_fields == ["subdomain"]

    def test_get_schemas_incremental_flags(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        assert {name for name, s in schemas.items() if s.supports_incremental} == INCREMENTAL_ENDPOINTS
        assert {name for name, s in schemas.items() if not s.supports_incremental} == FULL_REFRESH_ENDPOINTS
        for name in INCREMENTAL_ENDPOINTS:
            assert schemas[name].incremental_fields, name
        for name in FULL_REFRESH_ENDPOINTS:
            assert schemas[name].incremental_fields == [], name

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["reviews", "nonexistent"])
        assert [s.name for s in schemas] == ["reviews"]

    def test_get_documented_tables_lists_static_catalog(self) -> None:
        # lists_tables_without_credentials must stay in sync with a get_schemas that
        # does no I/O, so the public docs can render the table catalog.
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
