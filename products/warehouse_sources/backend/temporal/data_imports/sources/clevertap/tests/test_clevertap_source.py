from typing import Any

import pytest
import time_machine

from products.warehouse_sources.backend.temporal.data_imports.sources.clevertap.settings import (
    AUTH_ERROR,
    EXPORT_ERROR,
    PERMISSION_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clevertap.source import ClevertapSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clevertap import (
    ClevertapSourceConfig,
)


def config(**overrides: Any) -> ClevertapSourceConfig:
    values: dict[str, Any] = {
        "account_id": "TEST-ACCOUNT",
        "passcode": "fake-passcode",
        "region": "eu1",
        "event_name": "Product Viewed",
        "start_date": "2024-01-01",
        **overrides,
    }
    return ClevertapSourceConfig(**values)


@pytest.mark.parametrize(
    ("status", "body", "schema_name", "expected"),
    [
        (200, {"status": "success", "cursor": "test-cursor"}, None, (True, None)),
        (401, {}, None, (False, AUTH_ERROR)),
        (400, {"status": "fail", "error": "Invalid credentials", "code": 400}, None, (False, AUTH_ERROR)),
        (403, {"status": "fail", "error": "API access has been temporarily suspended"}, None, (True, None)),
        (
            403,
            {"status": "fail", "error": "API access has been temporarily suspended"},
            "events",
            (False, PERMISSION_ERROR),
        ),
        (200, {"status": "fail", "code": 403}, None, (True, None)),
        (400, {}, "events", (False, EXPORT_ERROR)),
        (200, {"status": "success"}, None, (False, "CleverTap did not return an export cursor.")),
    ],
)
@time_machine.travel("2024-01-04T12:00:00Z", tick=False)
def test_credential_probe_maps_vendor_failures_and_uses_a_narrow_window(
    status: int,
    body: dict[str, Any],
    schema_name: str | None,
    expected: tuple[bool, str | None],
) -> None:
    with scripted_network([ScriptedResponse(status=status, json=body)]) as network:
        assert ClevertapSource().validate_credentials(config(), 1, schema_name) == expected
    assert len(network.requests_log) == 1
    request = network.requests_log[0]
    assert request.path == f"/1/{schema_name or 'profiles'}.json"
    assert request.origin == "https://api.clevertap.com"
    assert request.json() == {"event_name": "Product Viewed", "from": 20240103, "to": 20240103}
    assert request.param("batch_size") == "1"


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"region": "https://example.com"}, "Select a supported CleverTap region."),
        ({"start_date": "2024-02-30"}, "Enter the start date in YYYY-MM-DD format."),
        ({"start_date": "2024-01-04"}, "The start date must be before today (UTC)."),
        ({"passcode": "fake\r\nheader"}, "Enter a valid CleverTap account ID and passcode."),
        ({"event_name": " "}, "Enter a CleverTap event name."),
    ],
)
@time_machine.travel("2024-01-04T12:00:00Z", tick=False)
def test_invalid_configuration_is_rejected_before_credentials_leave_the_process(
    override: dict[str, str],
    message: str,
) -> None:
    with scripted_network([]) as network:
        assert ClevertapSource().validate_credentials(config(**override), 1) == (False, message)
    assert network.requests_log == []


@time_machine.travel("2024-01-04T12:00:00Z", tick=False)
def test_unsupported_notification_event_is_rejected_before_export() -> None:
    result = SourceDriver(ClevertapSource(), config(event_name="Notification Sent")).run("events", [])
    assert str(result.raised) == "CleverTap does not export this notification event. Select another event name."
    assert result.requests == []
