from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import ValidateDatabaseHostMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.microsoftdefendercloudapps import (
    MicrosoftDefenderCloudAppsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_defender_cloud_apps.microsoft_defender_cloud_apps import (
    DefenderClient,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_defender_cloud_apps.source import (
    MicrosoftDefenderCloudAppsSource,
)


@pytest.mark.parametrize(
    "url",
    [
        "http://defender.example.com",
        "defender.example.com",
        "https://user:password@defender.example.com",
        "https://defender.example.com:8443",
        "https://defender.example.com:wrong",
        "https://defender.example.com/api/v1/alerts",
        "https://defender.example.com?host=localhost",
        "https://defender.example.com#fragment",
        "https://[::1]",
        "https://defender.example.com\\@localhost",
    ],
)
def test_unsafe_url_is_rejected_before_http(url: str) -> None:
    config = MicrosoftDefenderCloudAppsSourceConfig.from_dict({"portal_url": url, "api_token": "fake-token"})
    with patch.object(DefenderClient, "validate_credentials") as probe:
        valid, error = MicrosoftDefenderCloudAppsSource().validate_credentials(config, 1)
    assert not valid
    assert error
    probe.assert_not_called()


@pytest.mark.parametrize("pipeline", [False, True])
def test_private_host_is_rejected_at_validation_and_sync(pipeline: bool) -> None:
    config = MicrosoftDefenderCloudAppsSourceConfig.from_dict(
        {"portal_url": "https://localhost", "api_token": "fake-token"}
    )
    with (
        patch.object(
            ValidateDatabaseHostMixin, "is_database_host_valid", return_value=(False, "Private host")
        ) as check,
        patch.object(DefenderClient, "validate_credentials") as probe,
    ):
        source = MicrosoftDefenderCloudAppsSource()
        if pipeline:
            with pytest.raises(ValueError, match="Private host"):
                source.source_for_pipeline(config, MagicMock(), MagicMock(team_id=1, api_version="v1"))
        else:
            assert source.validate_credentials(config, 1) == (False, "Private host")
        check.assert_called_once_with("localhost", 1)
        probe.assert_not_called()


@pytest.mark.parametrize(
    ("endpoint", "incremental", "field"),
    [("unknown", False, None), ("files", True, "timestamp"), ("alerts", True, "wrong")],
)
def test_invalid_table_or_cursor_fails_before_http(endpoint: str, incremental: bool, field: str | None) -> None:
    config = MicrosoftDefenderCloudAppsSourceConfig.from_dict(
        {"portal_url": "https://defender.example.com", "api_token": "fake-token"}
    )
    with patch.object(ValidateDatabaseHostMixin, "is_database_host_valid", return_value=(True, None)):
        inputs: Any = MagicMock(schema_name=endpoint, should_use_incremental_field=incremental, incremental_field=field)
        with pytest.raises(ValueError):
            DefenderClient(config, 1, "v1").source_response(inputs, MagicMock())
