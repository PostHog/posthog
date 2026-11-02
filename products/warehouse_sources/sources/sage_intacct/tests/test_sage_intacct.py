from typing import Any
from urllib.parse import parse_qs

import pytest

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sageintacct import (
    SageIntacctSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sage_intacct.sage_intacct import (
    SageIntacctResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sage_intacct.source import SageIntacctSource


def config() -> SageIntacctSourceConfig:
    return SageIntacctSourceConfig(client_id="example-client", client_secret="example-secret", username="user@example")


def token() -> ScriptedResponse:
    return ScriptedResponse(json={"access_token": "example-access-token", "expires_in": 3600})


def page(keys: list[str], next_start: int | None) -> ScriptedResponse:
    return ScriptedResponse(json={"ia::result": [{"key": key} for key in keys], "ia::meta": {"next": next_start}})


def record(key: str) -> ScriptedResponse:
    return ScriptedResponse(json={"ia::result": {"key": key, "name": "Example", "audit": {"modifiedBy": "1"}}})


@pytest.mark.parametrize(
    ("schema", "object_name"),
    [
        ("Customers", "accounts-receivable/customer"),
        ("Vendors", "accounts-payable/vendor"),
        ("Invoices", "accounts-receivable/invoice"),
        ("Bills", "accounts-payable/bill"),
        ("GLAccounts", "general-ledger/account"),
        ("JournalEntries", "general-ledger/journal-entry"),
    ],
)
def test_query_pages_hydrate_records_and_commit_checkpoint(schema: str, object_name: str) -> None:
    result = SourceDriver(SageIntacctSource(), config()).run(
        schema, [token(), page(["7"], 20), record("7"), page(["20"], None), record("20")]
    )
    assert result.raised is None
    assert [row["key"] for row in result.rows] == ["7", "20"]
    assert result.rows[0]["audit"] == {"modifiedBy": "1"}
    assert [result.requests[i].json()["start"] for i in (1, 3)] == [1, 20]
    assert result.requests[1].json() == {
        "object": object_name,
        "fields": ["key"],
        "orderBy": [{"key": "asc"}],
        "size": 100,
        "start": 1,
    }
    assert result.paths[2] == f"/ia/api/v1/objects/{object_name}/7"
    assert result.saved_states == result.committed_states == [SageIntacctResumeConfig(next_start=20)]
    assert parse_qs((result.requests[0].body or b"").decode()) == {
        "grant_type": ["client_credentials"],
        "client_id": ["example-client"],
        "client_secret": ["example-secret"],
        "username": ["user@example"],
    }
    assert all(request.headers["authorization"] == "Bearer example-access-token" for request in result.requests[1:])


def test_resume_starts_at_saved_page_and_ignores_reference_href() -> None:
    result = SourceDriver(SageIntacctSource(), config()).run(
        "Customers",
        [
            token(),
            ScriptedResponse(
                json={
                    "ia::result": [{"key": "7", "href": "https://example.com/untrusted"}],
                    "ia::meta": {"next": None},
                }
            ),
            record("7"),
        ],
        resume_state=SageIntacctResumeConfig(next_start=20),
    )
    assert result.raised is None
    assert result.requests[1].json()["start"] == 20
    assert result.requests[2].origin == "https://api.intacct.com"
    assert result.rows[0]["key"] == "7"


def test_failed_detail_does_not_commit_parent_page() -> None:
    result = SourceDriver(SageIntacctSource(), config()).run(
        "Customers", [token(), page(["7", "8"], 20), record("7"), ScriptedResponse(status=403, json={})]
    )
    assert isinstance(result.raised, HTTPError)
    assert result.rows == []
    assert result.saved_states == result.committed_states == []


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"ia::result": [], "ia::meta": {"next": 1}}, "did not advance"),
        ({"ia::result": [], "ia::meta": {"next": True}}, "did not advance"),
        ({"ia::result": [], "ia::meta": {"next": "20"}}, "did not advance"),
        ({"ia::result": []}, "no pagination metadata"),
        ({"ia::result": {}, "ia::meta": {"next": None}}, "invalid query result"),
        ({"ia::error": {"code": "example-error"}}, "Required data_selector"),
        ({"ia::result": [{}], "ia::meta": {"next": None}}, "without a key"),
    ],
)
def test_bad_query_results_fail_without_silent_data_loss(body: dict[str, Any], message: str) -> None:
    result = SourceDriver(SageIntacctSource(), config()).run("Customers", [token(), ScriptedResponse(json=body)])
    assert isinstance(result.raised, ValueError)
    assert message in str(result.raised)
    assert result.rows == []


@pytest.mark.parametrize("body", [{"ia::result": None}, {"ia::result": {"key": "other"}}, {"ia::result": []}])
def test_invalid_detail_fails_before_checkpoint(body: dict[str, Any]) -> None:
    result = SourceDriver(SageIntacctSource(), config()).run(
        "Customers", [token(), page(["7"], 20), ScriptedResponse(json=body)]
    )
    assert isinstance(result.raised, ValueError)
    assert result.saved_states == []


def test_empty_query_finishes_without_detail_requests() -> None:
    result = SourceDriver(SageIntacctSource(), config()).run("Customers", [token(), page([], None)])
    assert result.raised is None
    assert result.rows == []
    assert len(result.requests) == 2


@pytest.mark.parametrize("status", [400, 401, 403])
def test_credential_probe_reports_read_or_auth_failure(status: int) -> None:
    with scripted_network([token(), ScriptedResponse(status=status, json={})]) as network:
        valid, message = SageIntacctSource().validate_credentials(config(), 1, schema_name="Bills")
    assert valid is False
    assert message == "Check your Sage Intacct credentials and read access to this table."
    assert network.requests_log[1].json()["object"] == "accounts-payable/bill"


def test_credential_probe_success() -> None:
    with scripted_network([token(), page([], None)]) as network:
        assert SageIntacctSource().validate_credentials(config(), 1) == (True, None)
    assert network.requests_log[1].json()["size"] == 1


@pytest.mark.parametrize("status", [400, 503])
def test_token_failure_distinguishes_permanent_from_transient(status: int) -> None:
    with scripted_network([ScriptedResponse(status=status, json={"error": "invalid_client"})]):
        valid, message = SageIntacctSource().validate_credentials(config(), 1)
        assert valid is False
        assert message == (
            "Couldn't reach Sage Intacct to check your credentials. Try again in a few minutes."
            if status == 503
            else "Check your Sage Intacct client credentials and web services username."
        )


@pytest.mark.parametrize(
    ("schema", "inputs", "error"),
    [
        ("Unknown", {}, UnknownResourceError),
        ("Customers", {"incremental_field": "key"}, ValueError),
    ],
)
def test_unsupported_table_or_sync_mode_fails_before_network(
    schema: str, inputs: dict[str, Any], error: type[Exception]
) -> None:
    result = SourceDriver(SageIntacctSource(), config()).run(schema, [], **inputs)
    assert isinstance(result.raised, error)
    assert result.requests == []
