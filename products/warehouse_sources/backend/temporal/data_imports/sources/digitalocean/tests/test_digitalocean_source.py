import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.source import DigitalOceanSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.digitalocean import (
    DigitalOceanSourceConfig,
)


def _config() -> DigitalOceanSourceConfig:
    return DigitalOceanSourceConfig(api_key="dop_v1_token")


class TestDigitalOceanValidateCredentials:
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.source.validate_digitalocean_credentials",
        return_value=(True, 200),
    )
    def test_accepts_valid_token(self, _mock: MagicMock) -> None:
        assert DigitalOceanSource().validate_credentials(_config(), team_id=1) == (True, None)

    @pytest.mark.parametrize("status_code", [401, 403])
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.source.validate_digitalocean_credentials"
    )
    def test_auth_rejection_says_token_invalid(self, mock_validate: MagicMock, status_code: int) -> None:
        mock_validate.return_value = (False, status_code)
        valid, error = DigitalOceanSource().validate_credentials(_config(), team_id=1)
        assert not valid
        assert error is not None
        assert "rejected the API token" in error

    @pytest.mark.parametrize("status_code", [429, 500, 503, None])
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.source.validate_digitalocean_credentials"
    )
    def test_transient_failure_does_not_blame_the_token(
        self, mock_validate: MagicMock, status_code: int | None
    ) -> None:
        # A rate limit, server error, or transport failure is not proof the token is bad; the
        # message must ask the user to retry rather than tell them to regenerate a good token.
        mock_validate.return_value = (False, status_code)
        valid, error = DigitalOceanSource().validate_credentials(_config(), team_id=1)
        assert not valid
        assert error is not None
        assert "rejected the API token" not in error


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
