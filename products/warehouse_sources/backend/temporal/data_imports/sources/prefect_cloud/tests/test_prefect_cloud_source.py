import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.prefectcloud import (
    PrefectCloudSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.prefect_cloud.source import PrefectCloudSource

# Endpoints whose Prefect filter model exposes a server-side `after_` time filter with an
# ascending sort; everything else is full refresh only.
_INCREMENTAL_ENDPOINTS = {"flow_runs", "task_runs"}
_FULL_REFRESH_ENDPOINTS = {"flows", "deployments", "work_pools", "work_queues"}

_ACCOUNT_ID = "11111111-2222-3333-4444-555555555555"
_WORKSPACE_ID = "66666666-7777-8888-9999-aaaaaaaaaaaa"


class TestPrefectCloudSource:
    def setup_method(self):
        self.source = PrefectCloudSource()
        self.team_id = 123
        self.config = PrefectCloudSourceConfig(account_id=_ACCOUNT_ID, workspace_id=_WORKSPACE_ID, api_key="pnu_key")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid Prefect Cloud API key"),
            (
                (False, 404),
                False,
                "Prefect Cloud account or workspace not found — check the account ID and workspace ID",
            ),
            (
                (False, None),
                False,
                "Could not connect to Prefect Cloud with the provided account ID, workspace ID, and API key",
            ),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.prefect_cloud.source.validate_prefect_cloud_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(_ACCOUNT_ID, _WORKSPACE_ID, "pnu_key")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.prefect_cloud.source.validate_prefect_cloud_credentials"
    )
    def test_validate_credentials_surfaces_malformed_ids(self, mock_validate):
        mock_validate.side_effect = ValueError("Invalid Prefect Cloud account ID: 'not-a-uuid'.")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert "Invalid Prefect Cloud account ID" in (error_message or "")
