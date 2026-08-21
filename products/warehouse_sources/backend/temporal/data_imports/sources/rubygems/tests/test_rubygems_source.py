from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.rubygems import (
    RubygemsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rubygems.source import RubygemsSource


class TestRubygemsSource:
    def setup_method(self):
        self.source = RubygemsSource()
        self.team_id = 123
        self.config = RubygemsSourceConfig(gems="rails\nrspec")

    def test_no_non_retryable_errors(self):
        # Unauthenticated API: there are no credential errors to permanently fail on.
        assert self.source.get_non_retryable_errors() == {}
