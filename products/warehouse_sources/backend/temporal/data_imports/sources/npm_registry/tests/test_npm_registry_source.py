from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.npmregistry import (
    NpmRegistrySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.npm_registry.source import NpmRegistrySource


class TestNpmRegistrySource:
    def setup_method(self):
        self.source = NpmRegistrySource()
        self.team_id = 123
        self.config = NpmRegistrySourceConfig(package_names="react\nlodash")

    def test_no_non_retryable_errors(self):
        # Unauthenticated API: there are no credential errors to permanently fail on.
        assert self.source.get_non_retryable_errors() == {}
