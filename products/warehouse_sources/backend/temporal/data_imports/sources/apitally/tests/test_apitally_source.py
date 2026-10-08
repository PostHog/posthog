from products.warehouse_sources.backend.temporal.data_imports.sources.apitally.apitally import ApitallyResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.apitally.source import ApitallySource


class TestApitallySourceConfig:
    def setup_method(self) -> None:
        self.source = ApitallySource()

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas iterates a static endpoint catalog with no I/O.
        assert self.source.lists_tables_without_credentials is True


def test_apitally_resume_config_defaults_to_no_token() -> None:
    assert ApitallyResumeConfig().next_token is None
