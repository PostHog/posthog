import json
from collections.abc import Iterable, Iterator
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

from requests import PreparedRequest, Response, Session

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.getdx import GetdxSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.getdx.getdx import (
    API_ERROR,
    AUTH_ERROR,
    PERMISSION_ERROR,
    GetdxResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.getdx.source import GetdxSource


@pytest.fixture
def transport() -> Iterator[MagicMock]:
    session = Session()
    with (
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session",
            return_value=session,
        ),
        patch.object(session, "send") as send,
    ):
        yield send
    session.close()


def respond(transport: MagicMock, payloads: list[dict[str, Any]], status: int = 200) -> list[PreparedRequest]:
    sent: list[PreparedRequest] = []
    payload_iter = iter(payloads)

    def send(request: PreparedRequest, **kwargs: Any) -> Response:
        sent.append(request)
        response = Response()
        response.status_code = status
        response._content = json.dumps(next(payload_iter)).encode()
        response.url = request.url or ""
        response.request = request
        return response

    transport.side_effect = send
    return sent


def query_params(request: PreparedRequest) -> dict[str, list[str]]:
    return parse_qs(urlsplit(cast(str, request.url)).query)


def inputs_for(table: str, incremental: bool = False) -> SourceInputs:
    return SourceInputs(
        schema_name=table,
        schema_id="schema-test",
        source_id="source-test",
        team_id=1,
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=1735689600,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-test",
        logger=MagicMock(),
        reset_pipeline=False,
    )


def manager_for(state: dict[str, Any] | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = state is not None
    manager.load_state.return_value = GetdxResumeConfig(paginator_state=state) if state else None
    return manager


def extract(table: str, manager: MagicMock) -> list[Any]:
    response = GetdxSource().source_for_pipeline(
        GetdxSourceConfig(api_key="test-token"),
        cast(ResumableSourceManager[GetdxResumeConfig], manager),
        inputs_for(table),
    )
    return [row for page in cast(Iterable[Any], response.items()) for row in page]


@pytest.mark.parametrize(
    "table,path,selector,params",
    [
        ("team_audit_events", "teams.auditTrail", "events", {}),
        ("scorecards", "scorecards.list", "scorecards", {"limit": ["50"], "include_unpublished": ["true"]}),
    ],
)
@pytest.mark.parametrize("terminal", [{}, {"next_cursor": None}, {"next_cursor": ""}])
def test_cursor_pages_and_terminal_page(
    transport: MagicMock, table: str, path: str, selector: str, params: dict, terminal: dict
) -> None:
    sent = respond(
        transport,
        [
            {"ok": True, selector: [{"id": "a"}], "response_metadata": {"next_cursor": "next-1"}},
            {"ok": True, selector: [{"id": "b"}], "response_metadata": terminal},
        ],
    )
    manager = manager_for()

    assert extract(table, manager) == [{"id": "a"}, {"id": "b"}]
    assert len(sent) == 2
    assert urlsplit(sent[0].url).path == f"/{path}"
    assert query_params(sent[0]) == params
    assert query_params(sent[1]) == {**params, "cursor": ["next-1"]}
    assert all(request.headers["Authorization"] == "Bearer test-token" for request in sent)
    manager.save_state.assert_called_once_with(GetdxResumeConfig(paginator_state={"cursor": "next-1"}))


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
def test_errors_fail_instead_of_importing_empty_data(
    transport: MagicMock, status: int, payload: dict, message: str
) -> None:
    respond(transport, [payload], status)
    with pytest.raises(ValueError, match=message):
        extract("teams", manager_for())
    assert GetdxSource().get_non_retryable_errors()[message] == message


@pytest.mark.parametrize("payload", [{"ok": True}, {"unexpected": []}])
def test_missing_collection_fails(transport: MagicMock, payload: dict) -> None:
    respond(transport, [payload])
    with pytest.raises(ValueError, match="Required data_selector"):
        extract("teams", manager_for())


@pytest.mark.parametrize(
    "status,payload,expected",
    [
        (200, {"ok": True, "account": {"name": "Test account"}}, (True, None)),
        (200, {"ok": False, "error": "invalid_auth"}, (False, AUTH_ERROR)),
        (401, {"ok": False, "error": "not_authed"}, (False, AUTH_ERROR)),
        (403, {}, (False, PERMISSION_ERROR)),
        (200, {}, (False, "DX returned an invalid response.")),
    ],
)
def test_credential_probe(transport: MagicMock, status: int, payload: dict, expected: tuple) -> None:
    sent = respond(transport, [payload], status)
    assert GetdxSource().validate_credentials(GetdxSourceConfig(api_key="test-token"), 1) == expected
    assert len(sent) == 1
    assert sent[0].url == "https://api.getdx.com/auth.whoami"
    assert sent[0].headers["Authorization"] == "Bearer test-token"


@pytest.mark.parametrize(
    "table,incremental,message", [("missing", False, "Unknown DX table"), ("teams", True, "full refresh only")]
)
def test_invalid_sync_request(transport: MagicMock, table: str, incremental: bool, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        GetdxSource().source_for_pipeline(
            GetdxSourceConfig(api_key="test-token"), manager_for(), inputs_for(table, incremental)
        )
    transport.assert_not_called()
