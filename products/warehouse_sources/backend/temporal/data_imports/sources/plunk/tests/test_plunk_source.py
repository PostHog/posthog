from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.plunk import PlunkSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.plunk.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.plunk.source import PlunkSource


class TestPlunkSource:
    def setup_method(self):
        self.source = PlunkSource()
        self.team_id = 123
        self.config = PlunkSourceConfig(api_key="sk_test", base_url=None)

    def test_connection_host_fields_force_secret_reentry(self):
        # The secret key is sent to base_url, so retargeting it must re-require the key.
        assert self.source.connection_host_fields == ["base_url"]

    def test_get_schemas_returns_all_endpoints_full_refresh(self):
        # No Plunk list endpoint accepts a server-side timestamp filter, so every stream must
        # ship full-refresh only — flipping one to incremental would corrupt sync watermarks.
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_lists_tables_without_credentials(self):
        # Static endpoint catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)

    def test_canonical_descriptions_match_endpoint_catalog(self):
        # Descriptions are keyed by schema name; a rename in settings.py must not silently
        # orphan the curated docs.
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions) == set(ENDPOINTS)
