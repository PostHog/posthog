from sources.pypi._config import PyPISourceConfig
from sources.pypi.source import PyPISource


class TestPyPISource:
    def setup_method(self):
        self.source = PyPISource()
        self.team_id = 123
        self.config = PyPISourceConfig(packages="requests\ndjango")

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["releases"])

        assert [schema.name for schema in schemas] == ["releases"]
