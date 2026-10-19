import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import scripted_network
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.onesignal import (
    OneSignalSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onesignal.source import OneSignalSource


@pytest.mark.parametrize(
    ("app_id", "api_key", "schema_name", "message_part"),
    [
        ("not-an-app-id", "test_key", None, "valid OneSignal App ID"),
        ("11111111-2222-4333-8444-555555555555", "", None, "without spaces"),
        ("11111111-2222-4333-8444-555555555555", "Key test_key", None, "without spaces"),
        ("11111111-2222-4333-8444-555555555555", "test_key\n", None, "without spaces"),
        ("11111111-2222-4333-8444-555555555555", "test_\u200bkey", None, "without spaces"),
        ("11111111-2222-4333-8444-555555555555", "test_key", "unknown_table", "supported table"),
    ],
)
def test_invalid_connection_inputs_fail_before_http(
    app_id: str, api_key: str, schema_name: str | None, message_part: str
) -> None:
    config = OneSignalSourceConfig(app_id=app_id, api_key=api_key)
    with scripted_network([]) as network:
        valid, message = OneSignalSource().validate_credentials(config, team_id=1, schema_name=schema_name)

    assert valid is False
    assert message is not None and message_part in message
    assert network.requests_log == []
