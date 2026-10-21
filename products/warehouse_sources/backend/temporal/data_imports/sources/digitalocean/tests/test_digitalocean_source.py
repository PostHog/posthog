import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.source import DigitalOceanSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.digitalocean import (
    DigitalOceanSourceConfig,
)


def _config() -> DigitalOceanSourceConfig:
    return DigitalOceanSourceConfig(api_key="dop_v1_token")


class TestDigitalOceanValidateCredentials:
    def test_accepts_valid_token(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert DigitalOceanSource().validate_credentials(_config(), team_id=1) == (True, None)

        assert [request.path for request in network.requests_log] == ["/v2/account"]

    @pytest.mark.parametrize("status_code", [401])
    def test_auth_rejection_says_token_invalid(self, status_code: int) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            valid, error = DigitalOceanSource().validate_credentials(_config(), team_id=1)

        assert not valid
        assert error is not None
        assert "rejected the API token" in error
        assert [request.path for request in network.requests_log] == ["/v2/account"]

    @pytest.mark.parametrize("status_code", [429, 503, None])
    def test_transient_failure_does_not_blame_the_token(self, status_code: int | None) -> None:
        # A rate limit, server error, or transport failure is not proof the token is bad; the
        # message must ask the user to retry rather than tell them to regenerate a good token.
        answer = ConnectionError("boom") if status_code is None else ScriptedResponse(status=status_code)
        with scripted_network(always(answer)) as network:
            valid, error = DigitalOceanSource().validate_credentials(_config(), team_id=1)

        assert not valid
        assert error is not None
        assert "rejected the API token" not in error
        assert {request.path for request in network.requests_log} == {"/v2/account"}


class TestDigitalOceanSourceForPipeline:
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.source.digitalocean_source")
    def test_passes_token_and_endpoint_through(self, mock_source: MagicMock) -> None:
        resource = MagicMock()
        resource.name = "droplets"
        resource.column_hints = None
        mock_source.return_value = resource

        inputs = MagicMock()
        inputs.schema_name = "droplets"
        inputs.team_id = 7
        inputs.job_id = "job-42"

        DigitalOceanSource().source_for_pipeline(_config(), inputs)

        _, kwargs = mock_source.call_args
        assert kwargs == {
            "api_key": "dop_v1_token",
            "endpoint": "droplets",
            "team_id": 7,
            "job_id": "job-42",
        }
