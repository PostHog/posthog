import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.waydev import WaydevSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.waydev.source import WaydevSource


class TestWaydevSource:
    def setup_method(self) -> None:
        self.source = WaydevSource()
        self.team_id = 123
        self.config = WaydevSourceConfig(api_key="key")

    def test_api_version(self) -> None:
        assert self.source.supported_versions == ("v2",)
        assert self.source.default_version == "v2"
        assert self.source.api_docs_url is not None and self.source.api_docs_url.startswith("https://")

    @pytest.mark.parametrize(
        ("status", "expected_valid", "expected_message"),
        [
            (None, False, "Could not connect to Waydev with the provided API token"),
        ],
    )
    def test_validate_credentials(self, status: int | None, expected_valid: bool, expected_message: str | None) -> None:
        script = always(ConnectionError("down") if status is None else ScriptedResponse(status=status, json=[]))

        with scripted_network(script) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        assert {request.path for request in network.requests_log} == {"/v2/metrics"}
        assert {request.headers["authorization"] for request in network.requests_log} == {"key"}

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.waydev.source.waydev_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_waydev_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "Incidents"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        manager = mock.MagicMock()
        mock_waydev_source.return_value.name = "Incidents"
        mock_waydev_source.return_value.column_hints = None

        response = self.source.source_for_pipeline(self.config, manager, inputs)

        mock_waydev_source.assert_called_once_with(
            api_key="key",
            endpoint="Incidents",
            team_id=self.team_id,
            job_id="job-1",
            resumable_source_manager=manager,
        )
        assert response.primary_keys == ["id"]
        assert response.name == "Incidents"
