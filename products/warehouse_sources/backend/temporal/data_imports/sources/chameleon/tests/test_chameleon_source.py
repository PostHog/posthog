from products.warehouse_sources.backend.temporal.data_imports.sources.chameleon.source import ChameleonSource


class TestChameleonSourceConfig:
    def setup_method(self) -> None:
        self.source = ChameleonSource()

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static endpoint catalog with no I/O, so the public docs can render it.
        assert self.source.lists_tables_without_credentials is True
