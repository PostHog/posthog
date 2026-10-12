from sources.gridly._config import GridlySourceConfig
from sources.gridly.source import GridlySource

_SOURCE_MODULE = "sources.gridly.source"


class TestGridlySource:
    def setup_method(self):
        self.source = GridlySource()
        self.team_id = 123
        self.config = GridlySourceConfig(api_key="key", view_id="view")

    def test_lists_tables_without_credentials(self):
        # get_schemas is a static catalog (no I/O), so the source opts into public-docs table listing.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["records"])
        assert [s.name for s in schemas] == ["records"]
