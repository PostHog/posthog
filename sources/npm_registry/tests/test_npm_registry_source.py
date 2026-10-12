from sources.npm_registry._config import NpmRegistrySourceConfig
from sources.npm_registry.source import NpmRegistrySource


class TestNpmRegistrySource:
    def setup_method(self):
        self.source = NpmRegistrySource()
        self.team_id = 123
        self.config = NpmRegistrySourceConfig(package_names="react\nlodash")

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Versions"])

        assert [schema.name for schema in schemas] == ["Versions"]
