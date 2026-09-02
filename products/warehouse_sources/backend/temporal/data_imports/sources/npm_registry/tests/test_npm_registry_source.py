from posthog.schema import ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.npmregistry import (
    NpmRegistrySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.npm_registry.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.npm_registry.source import NpmRegistrySource


class TestNpmRegistrySource:
    def setup_method(self):
        self.source = NpmRegistrySource()
        self.team_id = 123
        self.config = NpmRegistrySourceConfig(package_names="react\nlodash")

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "NpmRegistry"
        assert config.label == "npm registry"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source ships visible — re-adding the flag would hide it from every user.
        assert not config.unreleasedSource

    def test_get_schemas_lists_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_downloads_supports_incremental_versions_full_refresh_only(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["Downloads"].supports_incremental is True
        assert [f["field"] for f in schemas["Downloads"].incremental_fields] == ["day"]

        # The registry document has no server-side "changed since" filter, so Versions is always a
        # full refresh — re-fetching wouldn't reduce the amount of data pulled per sync.
        assert schemas["Versions"].supports_incremental is False
        assert schemas["Versions"].incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Versions"])

        assert [schema.name for schema in schemas] == ["Versions"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    def test_no_non_retryable_errors(self):
        # Unauthenticated API: there are no credential errors to permanently fail on.
        assert self.source.get_non_retryable_errors() == {}

    def test_lists_tables_without_credentials(self):
        # Static endpoint catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True
        assert len(self.source.get_documented_tables()) == len(ENDPOINTS)
