import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import ValidateDatabaseHostMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.microsoftdefendercloudapps import (
    MicrosoftDefenderCloudAppsSourceConfig,
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
    with scripted_network([]) as network:
        valid, error = MicrosoftDefenderCloudAppsSource().validate_credentials(config, 1)
    assert not valid
    assert error
    assert network.requests_log == []


@pytest.mark.parametrize("pipeline", [False, True])
def test_private_host_is_rejected_at_validation_and_sync(pipeline: bool) -> None:
    config = MicrosoftDefenderCloudAppsSourceConfig.from_dict(
        {"portal_url": "https://localhost", "api_token": "fake-token"}
    )
    with patch.object(
        ValidateDatabaseHostMixin, "is_database_host_valid", return_value=(False, "Private host")
    ) as check:
        source = MicrosoftDefenderCloudAppsSource()
        if pipeline:
            result = SourceDriver(source, config).run("alerts", [])
            assert isinstance(result.raised, ValueError)
            assert "Private host" in str(result.raised)
            assert result.requests == []
        else:
            with scripted_network([]) as network:
                assert source.validate_credentials(config, 1) == (False, "Private host")
            assert network.requests_log == []
        check.assert_called_once_with("localhost", 1)


@pytest.mark.parametrize(
    ("endpoint", "incremental", "field"),
    [("unknown", False, None), ("files", True, "timestamp"), ("alerts", True, "wrong")],
)
def test_invalid_table_or_cursor_fails_before_http(endpoint: str, incremental: bool, field: str | None) -> None:
    config = MicrosoftDefenderCloudAppsSourceConfig.from_dict(
        {"portal_url": "https://defender.example.com", "api_token": "fake-token"}
    )
    result = SourceDriver(MicrosoftDefenderCloudAppsSource(), config).run(
        endpoint, [], should_use_incremental_field=incremental, incremental_field=field
    )
    assert isinstance(result.raised, ValueError)
    assert result.requests == []
