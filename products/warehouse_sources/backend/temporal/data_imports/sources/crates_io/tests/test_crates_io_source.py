from products.warehouse_sources.backend.temporal.data_imports.sources.crates_io.source import CratesIOSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cratesio import (
    CratesIOSourceConfig,
)


class TestCratesIOSource:
    def setup_method(self):
        self.source = CratesIOSource()
        self.team_id = 123
        self.config = CratesIOSourceConfig(crates="serde\ntokio")

    def test_no_non_retryable_errors(self):
        # Unauthenticated API: there are no credential errors to permanently fail on.
        assert self.source.get_non_retryable_errors() == {}
