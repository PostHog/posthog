from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.firecrawl.source import FirecrawlSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.firecrawl import (
    FirecrawlSourceConfig,
)


def _config() -> FirecrawlSourceConfig:
    return FirecrawlSourceConfig(api_key="fc-test")


class TestFirecrawlValidateCredentials:
    @parameterized.expand([("valid", True), ("invalid", False)])
    def test_maps_token_probe_to_result(self, _name: str, probe_result: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.firecrawl.source.validate_firecrawl_credentials",
            return_value=probe_result,
        ):
            ok, error = FirecrawlSource().validate_credentials(_config(), team_id=1)
        assert ok is probe_result
        assert (error is None) is probe_result
