from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.postscript import (
    PostscriptSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postscript.source import PostscriptSource


class TestPostscriptSource:
    def setup_method(self) -> None:
        self.source = PostscriptSource()
        self.team_id = 123
        self.config = PostscriptSourceConfig(api_key="sk_postscript")

    def test_resolve_api_version_defaults_to_v2(self) -> None:
        assert self.source.resolve_api_version(None) == "v2"
        assert self.source.default_version in self.source.supported_versions
