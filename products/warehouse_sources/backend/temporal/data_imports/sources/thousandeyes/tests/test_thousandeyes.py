import json
from collections.abc import Callable, Iterator
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
import time_machine
from unittest.mock import MagicMock, patch

from requests import HTTPError, PreparedRequest, Response, Session

from products.warehouse_sources.backend.facade.types import IncrementalFieldType
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.thousandeyes import (
    ThousandeyesSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.thousandeyes.source import ThousandeyesSource
from products.warehouse_sources.backend.temporal.data_imports.sources.thousandeyes.thousandeyes import (
    ThousandeyesResumeConfig,
)

BASE = "https://api.thousandeyes.com/v7/"


def inputs(name: str, incremental: bool = False, watermark: str | None = None) -> SourceInputs:
    return SourceInputs(
        schema_name=name,
        schema_id="schema",
        source_id="source",
        team_id=1,
        job_id="job",
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
        db_incremental_field_earliest_value=None,
        incremental_field="date" if incremental else None,
        incremental_field_type=IncrementalFieldType.DateTime if incremental else None,
        reset_pipeline=False,
        logger=MagicMock(),
    )


def manager(resume: ThousandeyesResumeConfig | None = None) -> MagicMock:
    value = MagicMock(spec=ResumableSourceManager)
    value.can_resume.return_value = resume is not None
    value.load_state.return_value = resume
    return value


@pytest.fixture
def transport() -> Iterator[tuple[list[PreparedRequest], Callable[[dict[str, Any], int], None]]]:
    pending: list[tuple[dict[str, Any], int]] = []
    sent: list[PreparedRequest] = []

    def enqueue(body: dict[str, Any], status: int = 200) -> None:
        pending.append((body, status))

    def send(_session: Session, request: PreparedRequest, **kwargs: Any) -> Response:
        sent.append(request)
        assert kwargs["allow_redirects"] is False
        assert kwargs["timeout"] == 60
        body, status = pending.pop(0)
        response = Response()
        response.status_code = status
        response.reason = {401: "Unauthorized", 403: "Forbidden"}.get(status, "OK")
        response.url = request.url or ""
        response.request = request
        response._content = json.dumps(body).encode()
        response.headers["Content-Type"] = "application/json"
        return response

    with patch.object(Session, "send", send):
        yield sent, enqueue
    assert not pending


def read(name: str, state: MagicMock, incremental: bool = False, watermark: str | None = None) -> list[dict[str, Any]]:
    response = ThousandeyesSource().source_for_pipeline(
        ThousandeyesSourceConfig(api_token="fake-token", account_group_id="123"),
        state,
        inputs(name, incremental, watermark),
    )
    return [row for page in cast(Iterator[list[dict[str, Any]]], response.items()) for row in page]


@pytest.mark.parametrize(
    ("name", "selector", "path", "key"),
    [
        ("tests", "tests", "tests", "testId"),
        ("agents", "agents", "agents", "agentId"),
        ("alert_rules", "alertRules", "alerts/rules", "ruleId"),
    ],
)
@pytest.mark.parametrize("empty_terminal", [False, True])
def test_list_pagination_and_auth(
    transport: Any, name: str, selector: str, path: str, key: str, empty_terminal: bool
) -> None:
    sent, enqueue = transport
    next_url = BASE + path + "?aid=123&cursor=page-2"
    enqueue({selector: [{key: "one"}], "_links": {"next": {"href": next_url}}})
    last = [] if empty_terminal else [{key: "two"}]
    enqueue({selector: last})
    state = manager()
    assert read(name, state) == [{key: "one"}, *last]
    assert len(sent) == 2
    assert sent[0].url == BASE + path + "?aid=123"
    assert sent[1].url == next_url
    assert all(request.headers["Authorization"] == "Bearer fake-token" for request in sent)
    assert state.save_state.call_args_list[0].args[0].paginator_state == {"next_url": next_url}


@pytest.mark.parametrize(("table", "alert_state"), [("active_alerts", "trigger"), ("cleared_alerts", "clear")])
@time_machine.travel("2026-06-01T12:00:00Z", tick=False)
def test_alert_states_and_window(transport: Any, table: str, alert_state: str) -> None:
    sent, enqueue = transport
    enqueue({"alerts": [{"id": "alert-1"}]})
    assert read(table, manager()) == [{"id": "alert-1"}]
    assert parse_qs(urlsplit(sent[0].url).query) == {
        "aid": ["123"],
        "state": [alert_state],
        "startDate": ["2026-05-02T12:00:00Z"],
        "endDate": ["2026-06-01T12:00:00Z"],
    }


@pytest.mark.parametrize(
    ("incremental", "watermark", "expected_start"),
    [
        (False, "2026-05-31T12:00:00Z", "2026-05-02T12:00:00Z"),
        (True, None, "2026-05-02T12:00:00Z"),
        (True, "2026-05-31T12:00:00Z", "2026-05-31T11:55:00Z"),
        (True, "2026-01-01T00:00:00Z", "2026-05-02T12:00:00Z"),
    ],
)
@time_machine.travel("2026-06-01T12:00:00Z", tick=False)
def test_results_fanout_keys_and_time_filter(
    transport: Any, incremental: bool, watermark: str | None, expected_start: str
) -> None:
    sent, enqueue = transport
    enqueue({"tests": [{"testId": "1"}, {"testId": "snapshot", "savedEvent": True}, {"testId": "2"}]})
    row = {"roundId": 1780272000, "date": "2026-06-01T00:00:00Z", "agent": {"agentId": "5"}, "responseTime": 200}
    enqueue({"results": [row]})
    enqueue({"results": [row]})
    state = manager()
    rows = read("http_server_results", state, incremental, watermark)
    assert rows == [{**row, "testId": "1", "agentId": "5"}, {**row, "testId": "2", "agentId": "5"}]
    assert [urlsplit(request.url).path for request in sent] == [
        "/v7/tests/http-server",
        "/v7/test-results/1/http-server",
        "/v7/test-results/2/http-server",
    ]
    for request in sent[1:]:
        assert parse_qs(urlsplit(request.url).query) == {
            "aid": ["123"],
            "startDate": [expected_start],
            "endDate": ["2026-06-01T12:00:00Z"],
        }
    assert state.save_state.call_args.args[0].paginator_state["completed"] == [
        "test-results/1/http-server",
        "test-results/2/http-server",
    ]
    response = ThousandeyesSource().source_for_pipeline(
        ThousandeyesSourceConfig(api_token="fake-token"),
        manager(),
        inputs("http_server_results", True),
    )
    assert response.sort_mode == "desc"
    assert response.primary_keys == ["testId", "agentId", "roundId"]


@time_machine.travel("2026-06-02T12:00:00Z", tick=False)
def test_resume_child_page_keeps_original_window_and_skips_completed_tests(transport: Any) -> None:
    sent, enqueue = transport
    next_url = BASE + "test-results/2/http-server?aid=123&cursor=next"
    resume = ThousandeyesResumeConfig(
        start_date="2026-05-01T00:00:00Z",
        end_date="2026-05-31T00:00:00Z",
        paginator_state={
            "completed": ["test-results/1/http-server"],
            "current": "test-results/2/http-server",
            "child_state": {"next_url": next_url},
        },
    )
    enqueue({"tests": [{"testId": "1"}, {"testId": "2"}, {"testId": "3"}]})
    enqueue({"results": [{"roundId": 2, "agent": {"agentId": "5"}}]})
    enqueue({"results": []})
    state = manager(resume)
    assert read("http_server_results", state)[0]["testId"] == "2"
    assert len(sent) == 3
    assert sent[1].url == next_url
    assert parse_qs(urlsplit(sent[2].url).query)["startDate"] == [resume.start_date]
    assert parse_qs(urlsplit(sent[2].url).query)["endDate"] == [resume.end_date]
    assert len(state.save_state.call_args.args[0].paginator_state["completed"]) == 3


@pytest.mark.parametrize("account_group_id", [None, "123"])
@pytest.mark.parametrize("status", [200, 401, 403])
def test_credential_validation_and_errors(transport: Any, account_group_id: str | None, status: int) -> None:
    sent, enqueue = transport
    enqueue({"alerts": [], "_links": {"next": {"href": BASE + "alerts?cursor=unused"}}}, status)
    source = ThousandeyesSource()
    valid, message = source.validate_credentials(
        ThousandeyesSourceConfig(api_token="fake-token", account_group_id=account_group_id), 1
    )
    assert valid is (status == 200)
    assert len(sent) == 1
    assert sent[0].headers["Authorization"] == "Bearer fake-token"
    assert parse_qs(urlsplit(sent[0].url).query) == (
        {"max": ["1"], "aid": ["123"]} if account_group_id else {"max": ["1"]}
    )
    if status != 200:
        assert message == source.get_non_retryable_errors()[f"{status} Client Error"]
        enqueue({}, status)
        with pytest.raises(HTTPError, match=f"{status} Client Error"):
            read("tests", manager())


def test_resume_list_starts_at_saved_page(transport: Any) -> None:
    sent, enqueue = transport
    next_url = BASE + "tests?aid=123&cursor=page-2"
    state = manager(
        ThousandeyesResumeConfig(
            paginator_state={"next_url": next_url},
            start_date="2026-05-01T00:00:00Z",
            end_date="2026-05-31T00:00:00Z",
        )
    )
    enqueue({"tests": [{"testId": "two"}]})
    assert read("tests", state) == [{"testId": "two"}]
    assert [request.url for request in sent] == [next_url]


def test_child_pagination_then_next_parent(transport: Any) -> None:
    sent, enqueue = transport
    next_url = BASE + "test-results/1/http-server?aid=123&cursor=page-2"
    enqueue({"tests": [{"testId": "1"}, {"testId": "2"}]})
    row = {"roundId": 1, "agent": {"agentId": "5"}}
    enqueue({"results": [row], "_links": {"next": {"href": next_url}}})
    enqueue({"results": [{**row, "roundId": 2}]})
    enqueue({"results": []})
    state = manager()
    rows = read("http_server_results", state)
    assert [(row["testId"], row["roundId"]) for row in rows] == [("1", 1), ("1", 2)]
    assert sent[2].url == next_url
    assert urlsplit(sent[3].url).path == "/v7/test-results/2/http-server"
    saved = state.save_state.call_args_list[0].args[0]
    assert saved.paginator_state["child_state"] == {"next_url": next_url}


@pytest.mark.parametrize("next_url", ["https://example.com/steal", "http://api.thousandeyes.com/v7/tests"])
def test_rejects_pagination_outside_api_origin(transport: Any, next_url: str) -> None:
    sent, enqueue = transport
    enqueue({"tests": [{"testId": "1"}], "_links": {"next": {"href": next_url}}})
    with pytest.raises(ValueError, match="Refusing to send request"):
        read("tests", manager())
    assert len(sent) == 1


def test_invalid_watermark_fails_before_request(transport: Any) -> None:
    sent, _ = transport
    with pytest.raises(ValueError, match="Invalid ThousandEyes result timestamp"):
        read("http_server_results", manager(), True, "not-a-date")
    assert sent == []
