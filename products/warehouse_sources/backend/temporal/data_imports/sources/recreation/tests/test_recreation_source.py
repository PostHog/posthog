from typing import Optional

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.recreation import (
    RecreationSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recreation.settings import RECREATION_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.recreation.source import RecreationSource


class TestRecreationSource:
    def setup_method(self) -> None:
        self.source = RecreationSource()
        self.config = RecreationSourceConfig(api_key="test-key")

    @pytest.mark.parametrize(
        ("status_code", "expected_valid", "expected_error_fragment"),
        [
            (200, True, None),
        ],
    )
    def test_validate_credentials_status_mapping(
        self, status_code: int, expected_valid: bool, expected_error_fragment: Optional[str]
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))) as network:
            valid, error = self.source.validate_credentials(self.config, team_id=1)

        assert valid is expected_valid
        assert network.requests_log[0].headers["apikey"] == "test-key"
        if expected_error_fragment is None:
            assert error is None
        else:
            assert error is not None and expected_error_fragment in error

    @pytest.mark.parametrize("endpoint", list(RECREATION_ENDPOINTS.keys()))
    def test_source_for_pipeline_maps_endpoint_to_response(self, endpoint: str) -> None:
        empty_page = ScriptedResponse(
            json={"RECDATA": [], "METADATA": {"RESULTS": {"CURRENT_COUNT": 0, "TOTAL_COUNT": 0}}}
        )

        result = SourceDriver(self.source, self.config).run(endpoint, [empty_page])

        response = result.response
        assert response is not None
        endpoint_config = RECREATION_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == [endpoint_config.primary_key]
        if endpoint_config.partition_key is not None:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [endpoint_config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
