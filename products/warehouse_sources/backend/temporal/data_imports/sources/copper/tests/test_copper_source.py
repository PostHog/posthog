from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.copper.source import CopperSource


def _config() -> MagicMock:
    config = MagicMock()
    config.api_key = "key"
    config.user_email = "user@example.com"
    return config


class TestCopperSource:
    def setup_method(self):
        self.source = CopperSource()

    def test_get_schemas_filters_by_names(self):
        schemas = self.source.get_schemas(_config(), team_id=1, names=["people"])
        assert [s.name for s in schemas] == ["people"]
