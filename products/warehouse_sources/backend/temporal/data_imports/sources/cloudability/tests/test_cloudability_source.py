import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudability.source import CloudabilitySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cloudability import (
    CloudabilitySourceConfig,
)


class TestCloudabilitySource:
    def setup_method(self) -> None:
        self.source = CloudabilitySource()
        self.team_id = 123
        self.config = CloudabilitySourceConfig(api_key="key", region="us", view_id=None)

    @pytest.mark.parametrize(
        ("status_code", "expected_valid", "expected_message"),
        [
            (200, True, None),
        ],
    )
    def test_validate_credentials(self, status_code: int, expected_valid: bool, expected_message: str | None) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        assert network.requests_log[0].url == "https://api.cloudability.com/v3/views"
        assert network.requests_log[0].headers["authorization"] == "Basic a2V5Og=="

    def test_source_for_pipeline_passes_blank_view_id_as_none(self) -> None:
        # An empty string from the form must not be sent to Cloudability as a literal viewId="".
        config = CloudabilitySourceConfig(api_key="key", region="eu", view_id="")
        result = SourceDriver(self.source, config).run(
            "Anomalies", [ScriptedResponse(json=[{"id": "a1"}])], team_id=self.team_id, job_id="job-2"
        )

        assert result.raised is None
        assert result.rows == [{"id": "a1"}]
        assert result.requests[0].url.startswith("https://api-eu.cloudability.com/v3/anomalies")
        assert result.requests[0].param("viewId") is None
