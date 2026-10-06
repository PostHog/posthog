import json
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import pytest
import time_machine
from unittest.mock import MagicMock, patch

from requests import HTTPError, PreparedRequest, Response, Session

from products.warehouse_sources.backend.temporal.data_imports.sources.checkly.checkly import (
    ChecklyResumeConfig,
    checkly_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.checkly.source import ChecklySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.checkly import (
    ChecklySourceConfig,
)

CONFIG = ChecklySourceConfig(api_key="fake-checkly-key", account_id="00000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 6, 1, tzinfo=UTC)


class Transport:
    def __init__(self) -> None:
        self.responses: list[Response] = []
        self.requests: list[PreparedRequest] = []

    def add(self, body: object, status: int = 200) -> None:
        response = Response()
        response.status_code = status
        response.reason = {401: "Unauthorized", 403: "Forbidden", 404: "Not Found", 429: "Too Many Requests"}.get(
            status, "OK"
        )
        response._content = json.dumps(body).encode()
        response.headers["Content-Type"] = "application/json"
        self.responses.append(response)

    def send(self, request: PreparedRequest, **kwargs: object) -> Response:
        self.requests.append(request)
        assert self.responses, f"Unexpected request: {request.url}"
        response = self.responses.pop(0)
        response.url = request.url or ""
        response.request = request
        return response

    def params(self, index: int) -> dict[str, list[str]]:
        return parse_qs(urlparse(self.requests[index].url or "").query)

    def paths(self) -> list[str]:
        return [urlparse(request.url or "").path for request in self.requests]


@pytest.fixture
def transport() -> Iterator[Transport]:
    transport = Transport()
    with (
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session",
            side_effect=lambda **kwargs: Session(),
        ),
        patch.object(Session, "send", side_effect=transport.send),
    ):
        yield transport
    assert not transport.responses


@pytest.fixture
def manager() -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = False
    return manager


def materialize(response: SourceResponse) -> list[list[dict[str, Any]]]:
    return list(cast(Iterable[list[dict[str, Any]]], response.items()))


def inputs(name: str, *, incremental: bool = False, watermark: object = None) -> SourceInputs:
    return SourceInputs(
        schema_name=name,
        schema_id="schema",
        source_id="source",
        team_id=1,
        job_id="job",
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
        db_incremental_field_earliest_value=None,
        incremental_field="created_at" if incremental else None,
        incremental_field_type=None,
        logger=MagicMock(),
        reset_pipeline=False,
    )


@pytest.mark.parametrize(
    "name,path",
    [("checks", "/v2/checks"), ("check_groups", "/v1/check-groups"), ("alert_channels", "/v1/alert-channels")],
)
def test_list_pagination_auth_and_terminal_page(transport: Transport, manager: MagicMock, name: str, path: str) -> None:
    transport.add([{"id": "a"}])
    transport.add([{"id": "b"}])
    transport.add([])
    response = checkly_source(CONFIG, manager, inputs(name))
    assert materialize(response) == [[{"id": "a"}], [{"id": "b"}]]
    assert transport.paths() == [path] * 3
    assert [transport.params(i) for i in range(3)] == [{"limit": ["100"], "page": [str(page)]} for page in (1, 2, 3)]
    for request in transport.requests:
        assert request.headers["Authorization"] == "Bearer fake-checkly-key"
        assert request.headers["X-Checkly-Account"] == CONFIG.account_id
    assert [call.args[0].paginator_state for call in manager.save_state.call_args_list] == [{"page": 2}, {"page": 3}]
    manager.clear_state.assert_not_called()
    assert response.on_complete is not None
    response.on_complete()
    manager.clear_state.assert_called_once()


@pytest.mark.parametrize("name", ["checks", "check_groups", "alert_channels"])
def test_definitions_project_only_safe_metadata(transport: Transport, manager: MagicMock, name: str) -> None:
    transport.add(
        [
            {
                "id": "check-a",
                "request": {
                    "url": "https://hooks.slack.com/services/T000/B000/SECRET",
                    "basicAuth": {"username": "user", "password": "secret"},
                    "body": "password=secret",
                    "headers": [{"key": "Authorization", "value": "Bearer secret"}],
                    "queryParameters": [{"key": "token", "value": "secret"}],
                    "grpcConfig": {"metadata": [{"key": "authorization", "value": "Bearer secret"}]},
                },
                "heartbeat": {"pingToken": "secret", "pingUrl": "https://checklyhq.com/ping/secret"},
                "script": "login('secret')",
                "localSetupScript": "setup('secret')",
                "localTearDownScript": "teardown('secret')",
                "apiCheckDefaults": {
                    "basicAuth": {"username": "user", "password": "group-secret"},
                    "environmentVariables": [{"key": "TOKEN", "value": "group-secret"}],
                    "headers": [{"key": "X-Api-Key", "value": "group-secret"}],
                    "browserCheckDefaults": {"script": "login('group-secret')"},
                },
                "config": {"webhookUrl": "https://example.com/secret"},
                "newProviderField": "future-secret",
            }
        ]
    )
    transport.add([])

    assert materialize(checkly_source(CONFIG, manager, inputs(name))) == [[{"id": "check-a"}]]


def test_list_resume(transport: Transport, manager: MagicMock) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = ChecklyResumeConfig(paginator_state={"page": 4})
    transport.add([{"id": "last"}])
    transport.add([])
    assert materialize(checkly_source(CONFIG, manager, inputs("checks"))) == [[{"id": "last"}]]
    assert [transport.params(i)["page"] for i in range(2)] == [["4"], ["5"]]


def test_statuses_are_unpaginated_and_exclude_null_statuses(transport: Transport, manager: MagicMock) -> None:
    transport.add([None, {"checkId": "check-a", "hasFailures": False}])
    response = checkly_source(CONFIG, manager, inputs("check_statuses"))
    assert materialize(response) == [[{"checkId": "check-a", "hasFailures": False}]]
    assert transport.paths() == ["/v1/check-statuses"]
    assert transport.params(0) == {}
    assert response.primary_keys == ["checkId"]


@time_machine.travel(NOW, tick=False)
@pytest.mark.parametrize(
    "incremental,watermark,expected_from",
    [
        (False, NOW - timedelta(hours=2), NOW - timedelta(days=30)),
        (True, None, NOW - timedelta(days=30)),
        (True, NOW - timedelta(hours=2), NOW - timedelta(hours=2)),
        (True, "2026-05-31T22:00:00Z", NOW - timedelta(hours=2)),
        (True, NOW - timedelta(days=90), NOW - timedelta(days=30)),
    ],
)
def test_result_fanout_cursor_and_time_filters(
    transport: Transport, manager: MagicMock, incremental: bool, watermark: object, expected_from: datetime
) -> None:
    transport.add([{"id": "check-a"}, {"id": "check-b"}])
    transport.add({"entries": [{"id": "result-a", "created_at": "2026-05-31T23:00:00Z"}], "nextId": "cursor-a"})
    transport.add({"entries": [], "nextId": None})
    transport.add({"entries": [{"id": "result-a", "created_at": "2026-05-31T22:00:00Z"}], "nextId": None})
    transport.add([])
    response = checkly_source(CONFIG, manager, inputs("check_results", incremental=incremental, watermark=watermark))
    pages = materialize(response)
    assert [row["checkId"] for page in pages for row in page] == ["check-a", "check-b"]
    assert pages[0][0]["created_at"] == NOW - timedelta(hours=1)
    assert response.primary_keys == ["checkId", "id"]
    assert response.sort_mode == "desc"
    assert transport.paths() == [
        "/v2/checks",
        "/v2/check-results/check-a",
        "/v2/check-results/check-a",
        "/v2/check-results/check-b",
        "/v2/checks",
    ]
    for i in (1, 2, 3):
        assert transport.params(i)["from"] == [str(int(expected_from.timestamp()))]
        assert transport.params(i)["to"] == [str(int(NOW.timestamp()))]
        assert transport.params(i)["resultType"] == ["ALL"]
        fields = transport.params(i)["fields"][0].split(",")
        assert {"id", "checkId", "created_at", "responseTime", "hasFailures"} <= set(fields)
        assert "apiCheckResult" not in fields
        assert "browserCheckResult" not in fields
        assert "checkId" not in transport.params(i)
        assert "page" not in transport.params(i)
    assert "nextId" not in transport.params(1)
    assert transport.params(2)["nextId"] == ["cursor-a"]
    assert "nextId" not in transport.params(3)
    states = [call.args[0] for call in manager.save_state.call_args_list]
    assert states[0].paginator_state["child_state"] == {"cursor": "cursor-a"}
    assert states[-1].paginator_state["completed"] == ["/v2/check-results/check-a", "/v2/check-results/check-b"]
    assert all(state.to_timestamp == int(NOW.timestamp()) for state in states)


@time_machine.travel(NOW, tick=False)
def test_result_resume_preserves_window_and_skips_completed_checks(transport: Transport, manager: MagicMock) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = ChecklyResumeConfig(
        paginator_state={
            "completed": ["/v2/check-results/check-a"],
            "current": "/v2/check-results/check-b",
            "child_state": {"cursor": "saved-cursor"},
        },
        from_timestamp=1700000000,
        to_timestamp=1700010000,
    )
    transport.add([{"id": "check-a"}, {"id": "check-b"}])
    transport.add({"entries": [{"id": "last"}], "nextId": None})
    transport.add([])
    pages = materialize(checkly_source(CONFIG, manager, inputs("check_results")))
    assert pages == [[{"id": "last", "checkId": "check-b"}]]
    assert transport.paths() == ["/v2/checks", "/v2/check-results/check-b", "/v2/checks"]
    assert transport.params(1)["from"] == ["1700000000"]
    assert transport.params(1)["to"] == ["1700010000"]
    assert transport.params(1)["nextId"] == ["saved-cursor"]


@time_machine.travel(NOW, tick=False)
@pytest.mark.parametrize("watermark", [NOW, NOW + timedelta(hours=1)])
def test_no_requests_for_future_or_empty_window(transport: Transport, manager: MagicMock, watermark: datetime) -> None:
    assert (
        materialize(checkly_source(CONFIG, manager, inputs("check_results", incremental=True, watermark=watermark)))
        == []
    )
    assert transport.requests == []


@pytest.mark.parametrize(
    "name,watermark,error",
    [("unknown", None, "Unknown Checkly table"), ("check_results", "bad", "timestamp is invalid")],
)
def test_rejects_invalid_pipeline_inputs(manager: MagicMock, name: str, watermark: object, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        checkly_source(CONFIG, manager, inputs(name, incremental=True, watermark=watermark))


@pytest.mark.parametrize(
    "status,schema,valid,message,path",
    [
        (200, None, True, None, "/v2/checks"),
        (401, None, False, "rejected your API key", "/v2/checks"),
        (403, None, True, None, "/v2/checks"),
        (403, "checks", False, "key permissions", "/v2/checks"),
        (401, "check_results", False, "rejected your API key", "/v2/checks"),
        (200, "alert_channels", True, None, "/v1/alert-channels"),
        (200, "check_groups", True, None, "/v1/check-groups"),
        (200, "check_statuses", True, None, "/v1/check-statuses"),
    ],
)
def test_credential_probe_and_auth_errors(
    transport: Transport, status: int, schema: str | None, valid: bool, message: str | None, path: str
) -> None:
    transport.add([] if status == 200 else {"statusCode": status, "error": "Unauthorized"}, status)
    result, reason = validate_credentials(CONFIG, schema, "v2")
    assert result is valid
    assert reason is None if message is None else message in (reason or "")
    assert transport.paths() == [path]
    assert transport.params(0) == ({} if schema == "check_statuses" else {"limit": ["1"]})
    assert transport.requests[0].headers["Authorization"] == "Bearer fake-checkly-key"
    if not valid:
        assert reason in ChecklySource().get_non_retryable_errors().values()


@pytest.mark.parametrize("status", [401, 403, 404])
def test_sync_http_errors_are_terminal(transport: Transport, manager: MagicMock, status: int) -> None:
    transport.add({"statusCode": status, "error": "Unauthorized"}, status)
    with pytest.raises(HTTPError) as raised:
        materialize(checkly_source(CONFIG, manager, inputs("checks")))
    assert len(transport.requests) == 1
    matches = [value for key, value in ChecklySource().get_non_retryable_errors().items() if key in str(raised.value)]
    assert len(matches) == (0 if status == 404 else 1)


@pytest.mark.parametrize("status", [429, 500])
def test_transient_errors_use_framework_retries(transport: Transport, manager: MagicMock, status: int) -> None:
    transport.add({"statusCode": status}, status)
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.DEFAULT_RETRY_ATTEMPTS", 1
    ):
        with pytest.raises(RESTClientRetryableError):
            materialize(checkly_source(CONFIG, manager, inputs("checks")))
    assert len(transport.requests) == 1


def test_unknown_schema_probe_makes_no_request(transport: Transport) -> None:
    assert validate_credentials(CONFIG, "unknown", "v2") == (False, "Unknown Checkly table: unknown")
    assert transport.requests == []


def test_credential_probe_preserves_unexpected_errors(transport: Transport) -> None:
    transport.add({"statusCode": 404}, 404)
    with pytest.raises(HTTPError):
        validate_credentials(CONFIG, None, "v2")


def test_unsupported_version_makes_no_request(transport: Transport, manager: MagicMock) -> None:
    source_inputs = inputs("checks")
    source_inputs.api_version = "v1"
    with pytest.raises(ValueError, match="API version is not supported"):
        checkly_source(CONFIG, manager, source_inputs)
    assert transport.requests == []
