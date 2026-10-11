from sources.rubygems._config import RubygemsSourceConfig
from sources.rubygems.source import RubygemsSource


class TestRubygemsSource:
    def setup_method(self):
        self.source = RubygemsSource()
        self.team_id = 123
        self.config = RubygemsSourceConfig(gems="rails\nrspec")

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["versions"])

        assert [schema.name for schema in schemas] == ["versions"]
