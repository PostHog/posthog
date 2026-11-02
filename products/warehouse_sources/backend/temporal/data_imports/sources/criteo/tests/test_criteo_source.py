from typing import Any

import pytest
import time_machine

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.criteo.source import CriteoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.criteo import CriteoSourceConfig


def config(**overrides: str) -> CriteoSourceConfig:
    values = {
        "client_id": "example-client",
        "client_secret": "example-secret",
        "start_date": "2026-10-10",
        "currency": "USD",
    }
    return CriteoSourceConfig(**{**values, **overrides})


@pytest.mark.parametrize(
    ("schema_name", "status", "payload", "valid", "message"),
    [
        (None, 200, None, True, None),
        ("Campaigns", 200, {"data": []}, True, None),
        ("Campaigns", 401, {"errors": [{"type": "authentication"}]}, False, "access token"),
        ("Campaigns", 403, {"errors": [{"type": "authorization"}]}, False, "permissions and advertiser consent"),
        (
            "Campaigns",
            200,
            {"data": [], "errors": [{"type": "authorization"}]},
            False,
            "permissions and advertiser consent",
        ),
        ("CampaignStats", 200, {"Rows": []}, True, None),
        ("Ads", 200, {"data": [{"id": "10"}]}, True, None),
        ("Ads", 200, {"data": []}, True, None),
    ],
)
@time_machine.travel("2026-10-12T00:00:00Z", tick=False)
def test_creation_checks_only_credentials_and_table_probes_check_access(
    schema_name: str | None, status: int, payload: dict[str, Any] | None, valid: bool, message: str | None
) -> None:
    script = [ScriptedResponse(json={"access_token": "example-access-token", "expires_in": 900})]
    if schema_name:
        script.append(ScriptedResponse(status=status, json=payload))
        if schema_name == "Ads" and payload and payload["data"]:
            script.append(ScriptedResponse(json={"data": []}))
    with scripted_network(script) as network:
        result = CriteoSource().validate_credentials(config(), 1, schema_name)
    assert result[0] is valid
    if message:
        assert message in (result[1] or "")
    else:
        assert result[1] is None
    if schema_name is None:
        assert [request.path for request in network.requests_log] == ["/oauth2/token"]
    if schema_name == "CampaignStats":
        assert network.requests_log[1].json()["startDate"] == "2026-10-12"
        assert network.requests_log[1].json()["endDate"] == "2026-10-12"
    if schema_name == "Ads" and payload and payload["data"]:
        assert network.requests_log[-1].path == "/2026-07/marketing-solutions/advertisers/10/ads"


@pytest.mark.parametrize("status", [400, 401, 403])
@time_machine.travel("2026-10-12T00:00:00Z", tick=False)
def test_invalid_client_errors_return_an_actionable_message(status: int) -> None:
    with scripted_network([ScriptedResponse(status=status, json={"error": "invalid_client"})]):
        valid, message = CriteoSource().validate_credentials(config(), 1)
    assert valid is False
    assert message == "Criteo rejected the client credentials. Check the client ID and client secret."


@pytest.mark.parametrize("schema_name", [None, "Campaigns"])
@time_machine.travel("2026-10-12T00:00:00Z", tick=False)
def test_transient_probe_failures_do_not_mark_credentials_invalid(schema_name: str | None) -> None:
    script = (
        [ScriptedResponse(status=503, json={"error": "temporarily_unavailable"})]
        if schema_name is None
        else [
            ScriptedResponse(json={"access_token": "example-access-token", "expires_in": 900}),
            ScriptedResponse(status=503, json={"errors": []}),
        ]
    )
    with scripted_network(script):
        assert CriteoSource().validate_credentials(config(), 1, schema_name) == (
            False,
            "Couldn't reach Criteo to check your credentials. Try again in a few minutes.",
        )


@pytest.mark.parametrize(
    ("overrides", "schema_name", "message"),
    [
        ({"start_date": "not-a-date"}, None, "YYYY-MM-DD"),
        ({"start_date": "2026-10-13"}, None, "future"),
        ({"currency": "US"}, None, "currency code"),
        ({"currency": "123"}, None, "currency code"),
        ({}, "Unknown", "Unknown Criteo table"),
    ],
)
@time_machine.travel("2026-10-12T00:00:00Z", tick=False)
def test_invalid_setup_inputs_fail_before_a_request(
    overrides: dict[str, str], schema_name: str | None, message: str
) -> None:
    with scripted_network([]) as network:
        valid, reason = CriteoSource().validate_credentials(config(**overrides), 1, schema_name)
    assert valid is False
    assert message in (reason or "")
    assert network.requests_log == []


def test_unknown_pipeline_table_fails_before_extraction() -> None:
    result = SourceDriver(CriteoSource(), config()).run("Unknown", [])
    assert isinstance(result.raised, ValueError)
    assert str(result.raised) == "Unknown Criteo table. Select a supported table."
    assert result.requests == []
