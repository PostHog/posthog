from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.knowbe4 import (
    Knowbe4SourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.knowbe4.source import Knowbe4Source


class TestKnowBe4Source:
    def setup_method(self) -> None:
        self.source = Knowbe4Source()
        self.team_id = 123
        self.config = Knowbe4SourceConfig(api_key="tok", region="us")

    def test_api_docs_url_is_https(self) -> None:
        assert self.source.api_docs_url is not None
        assert self.source.api_docs_url.startswith("https://")
