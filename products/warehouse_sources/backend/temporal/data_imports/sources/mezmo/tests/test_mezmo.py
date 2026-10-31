from typing import Any

import pytest

from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mezmo import MezmoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mezmo.mezmo import MezmoResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mezmo.source import MezmoSource


def driver() -> SourceDriver:
    return SourceDriver(MezmoSource(), MezmoSourceConfig(api_key="sts_example_key"))


def test_alert_resume_skips_completed_pipeline() -> None:
    result = driver().run(
        "alerts",
        [
            ScriptedResponse(json={"data": [{"id": "one"}, {"id": "two"}]}),
            ScriptedResponse(json={"data": [{"id": "alert-two"}]}),
        ],
        resume_state=MezmoResumeConfig(
            paginator_state={"completed": ["pipeline/one/alert"], "current": "pipeline/two/alert", "child_state": None}
        ),
    )

    assert result.raised is None
    assert result.rows == [{"id": "alert-two", "pipeline_id": "two"}]
    assert result.paths == ["/v3/pipeline", "/v3/pipeline/two/alert"]


@pytest.mark.parametrize("status", [401, 403])
def test_permanent_http_errors_match_source_messages(status: int) -> None:
    body = (
        {"message": "Unauthorized", "status": 401, "code": "EAUTH"}
        if status == 401
        else {"message": "Forbidden", "status": 403}
    )
    result = driver().run("pipelines", [ScriptedResponse(status=status, json=body)])

    assert isinstance(result.raised, HTTPError)
    assert error_message_matches(str(result.raised), MezmoSource().get_non_retryable_errors())
    assert result.paths == ["/v3/pipeline"]


@pytest.mark.parametrize("status, schema, valid", [(403, None, True), (403, "pipelines", False)])
def test_credential_probe(status: int, schema: str | None, valid: bool) -> None:
    config = MezmoSourceConfig(api_key="sts_example_key")
    with scripted_network([ScriptedResponse(status=status, json={"data": []})]) as network:
        result, message = MezmoSource().validate_credentials(config, 1, schema)

    assert result is valid
    assert (message is None) is valid
    assert [request.path for request in network.requests_log] == ["/v3/pipeline"]


@pytest.mark.parametrize(
    "schema, key, message",
    [("missing", "sts_example", "Unknown Mezmo table"), (None, "ste_example", "delegated account ID")],
)
def test_invalid_setup_does_not_request(schema: str | None, key: str, message: str) -> None:
    with scripted_network([]) as network:
        valid, reason = MezmoSource().validate_credentials(MezmoSourceConfig(api_key=key), 1, schema)

    assert not valid
    assert reason is not None and message in reason
    assert network.requests_log == []


@pytest.mark.parametrize("body", [{}, {"message": "Unexpected response"}])
def test_missing_collection_fails_instead_of_erasing_table(body: dict[str, Any]) -> None:
    result = driver().run("pipelines", [ScriptedResponse(json=body)])

    assert isinstance(result.raised, ValueError)
    assert "Required data_selector" in str(result.raised)
    assert result.paths == ["/v3/pipeline"]


def test_alert_probe_checks_child_permissions() -> None:
    with scripted_network(
        [
            ScriptedResponse(json={"data": [{"id": "one"}]}),
            ScriptedResponse(status=403, json={"message": "Forbidden"}),
        ]
    ) as network:
        valid, message = MezmoSource().validate_credentials(MezmoSourceConfig(api_key="sts_example"), 1, "alerts")

    assert not valid
    assert message is not None and "read access" in message
    assert [request.path for request in network.requests_log] == ["/v3/pipeline", "/v3/pipeline/one/alert"]


def test_probe_preserves_unexpected_http_errors() -> None:
    with scripted_network([ScriptedResponse(status=404, json={"message": "Not found"})]) as network:
        with pytest.raises(HTTPError):
            MezmoSource().validate_credentials(MezmoSourceConfig(api_key="sts_example"), 1)

    assert [request.path for request in network.requests_log] == ["/v3/pipeline"]
