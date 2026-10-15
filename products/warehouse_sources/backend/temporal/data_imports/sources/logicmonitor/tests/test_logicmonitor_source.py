import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.logicmonitor import (
    LogicmonitorSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.logicmonitor.logicmonitor import (
    validate_portal_host,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.logicmonitor.source import LogicmonitorSource

HOST_CHECK = "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins.ValidateDatabaseHostMixin.is_database_host_valid"
CLIENT = "products.warehouse_sources.backend.temporal.data_imports.sources.logicmonitor.source.LogicMonitorClient"


@pytest.mark.parametrize("valid", [True, False])
def test_host_check_controls_credential_probe(valid: bool) -> None:
    config = LogicmonitorSourceConfig(portal_url="https://example.logicmonitor.com", bearer_token="fake-token")
    with (
        patch(HOST_CHECK, return_value=(valid, None if valid else "Host is private")) as check,
        patch(CLIENT) as client,
    ):
        client.return_value.validate_credentials.return_value = (True, None)
        assert LogicmonitorSource().validate_credentials(config, 42) == (
            (True, None) if valid else (False, "Host is private")
        )
        check.assert_called_once_with("example.logicmonitor.com", 42)
        assert client.call_count == int(valid)


def test_invalid_portal_fails_before_dns() -> None:
    with patch(HOST_CHECK) as check:
        valid, error = validate_portal_host("http://localhost", 42)
        assert not valid
        assert error and "HTTPS LogicMonitor" in error
        check.assert_not_called()


def test_pipeline_rechecks_host() -> None:
    config = LogicmonitorSourceConfig(portal_url="https://example.logicmonitor.com", bearer_token="fake-token")
    inputs = MagicMock(team_id=42)
    with patch(HOST_CHECK, return_value=(False, "Host is private")) as check, patch(CLIENT) as client:
        with pytest.raises(ValueError, match="Host is private"):
            LogicmonitorSource().source_for_pipeline(config, MagicMock(), inputs)
        check.assert_called_once_with("example.logicmonitor.com", 42)
        client.assert_not_called()
