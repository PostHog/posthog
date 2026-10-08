from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.knowbe4 import (
    Knowbe4SourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.knowbe4.source import Knowbe4Source


class TestKnowBe4Source:
    def setup_method(self) -> None:
        self.source = Knowbe4Source()
        self.team_id = 123
        self.config = Knowbe4SourceConfig(api_key="tok", region="us")

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — powers the public docs table list.
        assert self.source.lists_tables_without_credentials is True

    def test_connection_host_fields_cover_token_destination(self) -> None:
        # Dropping `region` would let an editor retarget the stored API key at a different
        # regional host without re-entering it (the update serializer keys off this list).
        assert self.source.connection_host_fields == ["region"]

    def test_api_docs_url_is_https(self) -> None:
        assert self.source.api_docs_url is not None
        assert self.source.api_docs_url.startswith("https://")
