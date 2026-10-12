from sources.hyperspell._config import HyperspellSourceConfig
from sources.hyperspell.source import HyperspellSource

MODULE = "sources.hyperspell.source"


class TestHyperspellSource:
    def setup_method(self):
        self.source = HyperspellSource()
        self.team_id = 123
        self.config = HyperspellSourceConfig(api_key="hs_test", region="eu", user_ids="user-1, user-2")

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["memories", "nonexistent"])

        assert [schema.name for schema in schemas] == ["memories"]
