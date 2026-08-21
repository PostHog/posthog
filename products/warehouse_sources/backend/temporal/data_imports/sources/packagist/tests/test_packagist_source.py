from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.packagist import (
    PackagistSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.packagist.source import PackagistSource


class TestPackagistSource:
    def setup_method(self):
        self.source = PackagistSource()
        self.team_id = 123
        self.config = PackagistSourceConfig(packages="monolog/monolog\nsymfony/console")

    def test_no_non_retryable_errors(self):
        # Unauthenticated API: there are no credential errors to permanently fail on.
        assert self.source.get_non_retryable_errors() == {}
