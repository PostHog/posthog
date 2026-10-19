import pytest
import time_machine

from products.warehouse_sources.backend.temporal.data_imports.sources.adapty.source import AdaptySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.adapty import AdaptySourceConfig


@pytest.mark.parametrize(
    ("start_date", "api_key", "message"),
    [
        ("2024-02-30", "secret_live_example", "YYYY-MM-DD"),
        ("20240101", "secret_live_example", "YYYY-MM-DD"),
        ("2024-01-02", "secret_live_example", "before today"),
        ("2024-01-03", "secret_live_example", "before today"),
        ("2024-01-01", "secret_live_example\n", "without spaces"),
        ("2024-01-01", "secret_live_éxample", "without spaces"),
        ("2024-01-01", "", "without spaces"),
    ],
)
@time_machine.travel("2024-01-02T12:00:00Z", tick=False)
def test_invalid_config_stops_before_any_request(start_date: str, api_key: str, message: str) -> None:
    with scripted_network([]) as network:
        valid, error = AdaptySource().validate_credentials(
            AdaptySourceConfig(api_key=api_key, start_date=start_date), team_id=1
        )
    assert valid is False
    assert error is not None and message in error
    assert network.requests_log == []


@pytest.mark.parametrize(
    ("schema", "status", "payload", "valid", "message"),
    [
        (None, 200, {"data": {"revenue": {"data": [], "value": 0}}}, True, None),
        ("Paywalls", 200, {"data": []}, True, None),
        ("Conversions", 200, {"data": [], "value": 0}, True, None),
        (
            None,
            401,
            {"errors": ["Invalid API key"], "error_code": "unauthorized", "status_code": 401},
            False,
            "rejected the API key",
        ),
        (None, 403, {}, True, None),
        ("Analytics", 403, {}, False, "denied access"),
        ("Retention", 400, {"error_code": "validation_error"}, False, "rejected the request"),
        (None, 429, {}, False, "Could not read"),
        (None, 200, {"unexpected": []}, False, "Could not read"),
    ],
)
@time_machine.travel("2024-01-02T12:00:00Z", tick=False)
def test_credential_probe_uses_table_request_and_maps_failures(
    schema: str | None, status: int, payload: object, valid: bool, message: str | None
) -> None:
    with scripted_network(
        always(ScriptedResponse(status=status, json=payload, headers={"Retry-After": "86400"}))
    ) as network:
        actual, error = AdaptySource().validate_credentials(
            AdaptySourceConfig(api_key="secret_live_example", start_date="2024-01-01"), team_id=1, schema_name=schema
        )
    assert actual is valid
    assert error is None if message is None else error is not None and message in error
    request = network.requests_log[0]
    if schema == "Paywalls":
        assert request.method == "GET"
        assert request.param("page[size]") == "1"
    else:
        assert request.method == "POST"
        assert request.json()["filters"] == {"date": ["2024-01-01", "2024-01-01"]}
        if schema == "Conversions":
            assert request.json()["from_period"] == "1"
            assert request.json()["to_period"] == "6+"
