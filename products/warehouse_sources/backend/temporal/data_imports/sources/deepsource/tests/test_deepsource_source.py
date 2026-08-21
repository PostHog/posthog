from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.deepsource.settings import (
    DEEPSOURCE_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.deepsource.source import DeepsourceSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.deepsource import (
    DeepsourceSourceConfig,
)

_CONFIG = DeepsourceSourceConfig(api_token="tok", account_login="acme", vcs_provider="GITHUB")


def _source_inputs(schema_name: str) -> MagicMock:
    inputs = MagicMock()
    inputs.schema_name = schema_name
    return inputs


class TestDeepsourceSource:
    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_source_for_pipeline_wires_endpoint_config(self, endpoint: str) -> None:
        response = DeepsourceSource().source_for_pipeline(_CONFIG, MagicMock(), _source_inputs(endpoint))

        assert response.name == endpoint
        assert response.primary_keys == DEEPSOURCE_ENDPOINTS[endpoint].primary_keys
        assert callable(response.items)
