from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pypi import PyPISourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pypi.source import PyPISource


class TestPyPISource:
    def setup_method(self):
        self.source = PyPISource()
        self.team_id = 123
        self.config = PyPISourceConfig(packages="requests\ndjango")

    def test_no_non_retryable_errors(self):
        # Unauthenticated API: there are no credential errors to permanently fail on.
        assert self.source.get_non_retryable_errors() == {}
