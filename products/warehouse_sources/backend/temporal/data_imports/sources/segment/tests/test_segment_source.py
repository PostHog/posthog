from typing import Literal, cast

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.segment import (
    SegmentSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.segment.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.segment.source import SegmentSource


def _config(region: str = "api", api_token: str = "tok") -> SegmentSourceConfig:
    return SegmentSourceConfig(api_token=api_token, region=cast(Literal["api", "eu1"], region))

    # Intentionally unreleased: the source is shipped behind the flag while it stabilizes.


class TestValidateCredentials:
    @parameterized.expand([("us", "api"), ("eu", "eu1")])
    def test_validate_credentials_targets_region_host(self, _name: str, region: str) -> None:
        with scripted_network([ScriptedResponse(status=200, json={})]) as network:
            SegmentSource().validate_credentials(_config(region=region), team_id=1)

        assert region in network.requests_log[0].url


class TestCanonicalDescriptions:
    def test_descriptions_cover_known_endpoints(self) -> None:
        descriptions = SegmentSource().get_canonical_descriptions()
        # Every documented endpoint with a curated description must be a real schema.
        assert set(descriptions).issubset(set(ENDPOINTS))
        assert "sources" in descriptions
