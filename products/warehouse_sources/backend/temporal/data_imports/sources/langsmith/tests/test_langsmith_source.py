import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.langsmith import (
    LangSmithSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.langsmith.source import LangSmithSource


class TestLangSmithSource:
    def setup_method(self):
        self.source = LangSmithSource()
        self.team_id = 123
        self.config = LangSmithSourceConfig(api_key="key", host=None)

    @pytest.mark.parametrize(
        "endpoint,expected_incremental",
        [
            ("runs", True),
            ("projects", False),
            ("datasets", False),
            ("examples", False),
            ("feedback", True),
            ("annotation_queues", False),
        ],
    )
    def test_get_schemas(self, endpoint, expected_incremental):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        assert endpoint in schemas
        schema = schemas[endpoint]
        assert schema.supports_incremental is expected_incremental
        assert schema.supports_append is expected_incremental
        assert schema.detected_primary_keys == ["id"]
