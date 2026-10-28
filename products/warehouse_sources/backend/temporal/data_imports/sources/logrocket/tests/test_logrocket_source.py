from dataclasses import replace
from typing import Any

import pytest

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.logrocket import (
    LogrocketSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.logrocket.source import LogrocketSource


def config() -> LogrocketSourceConfig:
    return LogrocketSourceConfig(api_key="fake-key", organization_id="example-org", project_id="example-project")


@pytest.mark.parametrize(
    ("status", "schema_name", "expected", "message"),
    [
        (200, None, True, None),
        (200, "session_events", True, None),
        (401, None, False, "rejected your API key"),
        (403, None, True, None),
        (403, "session_events", False, "denied access to this table"),
        (404, None, False, "could not find this project"),
        (400, None, None, None),
    ],
)
def test_credential_probe_maps_access_errors_without_requiring_all_addons(
    status: int, schema_name: str | None, expected: bool | None, message: str | None
) -> None:
    body: dict[str, list[Any]] = {"sessions": []} if schema_name == "session_events" else {"logs": []}
    with scripted_network([ScriptedResponse(status=status, json=body)]) as network:
        if expected is None:
            with pytest.raises(HTTPError):
                LogrocketSource().validate_credentials(config(), 1, schema_name)
        else:
            valid, error = LogrocketSource().validate_credentials(config(), 1, schema_name)
            assert valid is expected
            if message is None:
                assert error is None
            else:
                assert error is not None and message in error
    request = network.requests_log[0]
    assert request.param("limit") == "1"
    assert request.headers["authorization"] == "token fake-key"
    assert request.path.endswith("data-export/" if schema_name == "session_events" else "audit/logs/")


@pytest.mark.parametrize(
    ("overrides", "schema_name", "message"),
    [
        ({"organization_id": "../different"}, None, "organization ID"),
        ({"project_id": "https://example.com"}, None, "project ID"),
        ({"api_key": "fake\nkey"}, None, "valid LogRocket API key"),
        ({"api_key": "\u2603"}, None, "valid LogRocket API key"),
        ({}, "unknown", "Unknown LogRocket table"),
    ],
)
def test_invalid_connection_inputs_fail_before_http(
    overrides: dict[str, str], schema_name: str | None, message: str
) -> None:
    with scripted_network([]) as network:
        valid, error = LogrocketSource().validate_credentials(replace(config(), **overrides), 1, schema_name)
    assert valid is False
    assert error is not None and message in error
    assert network.requests_log == []


def test_pipeline_rejects_unverified_incremental_mode() -> None:
    result = SourceDriver(LogrocketSource(), config()).run("audit_logs", [], incremental_field="created_date")
    assert isinstance(result.raised, ValueError)
    assert "full refresh only" in str(result.raised)
    assert result.requests == []


def test_table_permissions_report_missing_addon_without_blocking_accessible_table() -> None:
    with scripted_network(
        [ScriptedResponse(json={"logs": []}), ScriptedResponse(status=403, json={"error": "forbidden"})]
    ):
        permissions = LogrocketSource().get_endpoint_permissions(config(), 1, ["audit_logs", "session_events"])
    assert permissions["audit_logs"] is None
    assert permissions["session_events"] is not None
    assert "required add-on" in permissions["session_events"]
