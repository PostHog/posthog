from sources.codescene._config import CodesceneSourceConfig
from sources.codescene.source import CodesceneSource


class TestCodesceneSource:
    def setup_method(self) -> None:
        self.source = CodesceneSource()
        self.team_id = 123
        self.config = CodesceneSourceConfig(api_token="cs-token", base_url=None)

    def test_connection_host_fields(self) -> None:
        assert self.source.connection_host_fields == ["base_url"]
