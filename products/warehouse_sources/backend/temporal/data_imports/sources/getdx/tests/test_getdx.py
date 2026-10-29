from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.getdx import GetdxSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.getdx.getdx import (
    API_ERROR,
    AUTH_ERROR,
    PERMISSION_ERROR,
    GetdxResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.getdx.source import GetdxSource


def driver() -> SourceDriver:
    return SourceDriver(GetdxSource(), GetdxSourceConfig(api_key="test-token"))


def query_params(request: RecordedRequest) -> dict[str, list[str]]:
    return {name: list(values) for name, values in request.query.items()}


@pytest.mark.parametrize(
    "table,path,selector,params",
    [
        ("team_audit_events", "teams.auditTrail", "events", {}),
        ("scorecards", "scorecards.list", "scorecards", {"limit": ["50"], "include_unpublished": ["true"]}),
    ],
)
@pytest.mark.parametrize("terminal", [{}, {"next_cursor": None}, {"next_cursor": ""}])
def test_cursor_pages_and_terminal_page(
    table: str, path: str, selector: str, params: dict[str, list[str]], terminal: dict[str, Any]
) -> None:
    result = driver().run(
        table,
        [
            ScriptedResponse(
                json={"ok": True, selector: [{"id": "a"}], "response_metadata": {"next_cursor": "next-1"}}
            ),
            ScriptedResponse(json={"ok": True, selector: [{"id": "b"}], "response_metadata": terminal}),
        ],
    )

    assert result.raised is None
    assert result.rows == [{"id": "a"}, {"id": "b"}]
    assert result.paths == [f"/{path}", f"/{path}"]
    assert query_params(result.requests[0]) == params
    assert query_params(result.requests[1]) == {**params, "cursor": ["next-1"]}
    assert all(request.headers["authorization"] == "Bearer test-token" for request in result.requests)
    assert result.saved_states == [GetdxResumeConfig(paginator_state={"cursor": "next-1"})]


@pytest.mark.parametrize(
    "status,payload,message",
    [
        (401, {}, AUTH_ERROR),
        (403, {}, PERMISSION_ERROR),
        (200, {"ok": False, "error": "not_authed"}, AUTH_ERROR),
        (200, {"ok": False, "error": "invalid_auth"}, AUTH_ERROR),
        (200, {"ok": False, "error": "not_authorized"}, PERMISSION_ERROR),
        (422, {"ok": False, "error": "invalid_arguments"}, API_ERROR),
        (200, {"ok": False, "error": "unknown_error"}, API_ERROR),
    ],
)
def test_errors_fail_instead_of_importing_empty_data(status: int, payload: dict[str, Any], message: str) -> None:
    result = driver().run("teams", [ScriptedResponse(status=status, json=payload)])

    assert isinstance(result.raised, ValueError)
    assert message in str(result.raised)
    assert GetdxSource().get_non_retryable_errors()[message] == message


@pytest.mark.parametrize("payload", [{"ok": True}, {"unexpected": []}])
def test_missing_collection_fails(payload: dict[str, Any]) -> None:
    result = driver().run("teams", [ScriptedResponse(json=payload)])

    assert isinstance(result.raised, ValueError)
    assert "Required data_selector" in str(result.raised)


@pytest.mark.parametrize(
    "status,payload,expected",
    [
        (200, {"ok": True, "account": {"name": "Test account"}}, (True, None)),
        (200, {"ok": False, "error": "invalid_auth"}, (False, AUTH_ERROR)),
        (200, {}, (False, "DX returned an invalid response.")),
    ],
)
def test_credential_probe(status: int, payload: dict[str, Any], expected: tuple[bool, str | None]) -> None:
    with scripted_network([ScriptedResponse(status=status, json=payload)]) as network:
        assert GetdxSource().validate_credentials(GetdxSourceConfig(api_key="test-token"), 1) == expected

    assert len(network.requests_log) == 1
    assert network.requests_log[0].url == "https://api.getdx.com/auth.whoami"
    assert network.requests_log[0].headers["authorization"] == "Bearer test-token"


@pytest.mark.parametrize(
    "table,incremental,message", [("missing", False, "Unknown DX table"), ("teams", True, "full refresh only")]
)
def test_invalid_sync_request(table: str, incremental: bool, message: str) -> None:
    result = driver().run(table, [], should_use_incremental_field=incremental)

    assert isinstance(result.raised, ValueError)
    assert message in str(result.raised)
    assert result.requests == []
