from typing import Any

from sources.gnews._config import GNewsSourceConfig
from sources.gnews.source import GNewsSource

_MODULE = "sources.gnews.source"


def _config(**overrides: Any) -> GNewsSourceConfig:
    defaults: dict[str, Any] = {"api_key": "k", "query": "posthog", "category": "general"}
    defaults.update(overrides)
    return GNewsSourceConfig(**defaults)


class TestGNewsSource:
    def setup_method(self) -> None:
        self.source = GNewsSource()

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(_config(), team_id=1, names=["top_headlines"])
        assert [s.name for s in schemas] == ["top_headlines"]
