from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import AsyncMock, Mock, patch

import pyarrow as pa
import requests_mock
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.browse_ai.browse_ai import (
    BrowseAIResumeConfig,
    browse_ai_source,
    validate_credentials,
    webhook_table,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.browse_ai.settings import BASE_URL
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClient,
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse


def sync_items(response: SourceResponse) -> Iterable[Any]:
    items = response.items()
    assert isinstance(items, Iterable)
    return items


@pytest.fixture
def inputs() -> SourceInputs:
    return SourceInputs(
        schema_name="tasks",
        schema_id="schema",
        source_id="source",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job",
        logger=Mock(),
        reset_pipeline=False,
    )


@pytest.fixture
def manager() -> Mock:
    return Mock(can_resume=Mock(return_value=False))


@pytest.fixture
def webhook_manager() -> Mock:
    return Mock(webhook_enabled=AsyncMock(return_value=False))


def task_page(items: list[dict[str, Any]], has_more: bool) -> dict[str, Any]:
    return {"result": {"robotTasks": {"items": items, "hasMore": has_more}}}


@pytest.mark.parametrize("endpoint,envelope", [("tasks", "result.robotTasks"), ("bulk_runs", "result")])
def test_pages_fan_out_and_resume_after_yield(
    inputs: SourceInputs,
    manager: Mock,
    webhook_manager: Mock,
    endpoint: str,
    envelope: str,
) -> None:
    inputs.schema_name = endpoint
    inputs.db_incremental_field_last_value = 9999999999999
    child_path = "tasks" if endpoint == "tasks" else "bulk-runs"

    def page(identifier: str, more: bool) -> dict[str, Any]:
        body: dict[str, Any] = {
            "items": [{"id": identifier, "createdAt": 1700000000123, "capturedLists": {"products": [{"price": "10"}]}}],
            "hasMore": more,
        }
        for key in reversed(envelope.split(".")):
            body = {key: body}
        return body

    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/robots", json={"robots": {"items": [{"id": "r1"}, {"id": "r2"}]}})
        http.get(
            f"{BASE_URL}/robots/r1/{child_path}", [{"json": page("same-id", True)}, {"json": page("second", False)}]
        )
        http.get(f"{BASE_URL}/robots/r2/{child_path}", json=page("same-id", False))
        response = browse_ai_source("fake-key", inputs, manager, webhook_manager)
        rows = iter(sync_items(response))
        first = next(rows)
        manager.save_state.assert_not_called()
        second = next(rows)
        saved = manager.save_state.call_args.args[0].paginator_state
        assert saved == {"completed": [], "current": f"robots/r1/{child_path}", "child_state": {"page": 2}}
        remaining = list(rows)
        assert [first[0]["id"], second[0]["id"], remaining[0][0]["id"]] == ["same-id", "second", "same-id"]
        assert first[0]["createdAt"] == datetime.fromtimestamp(1700000000.123, UTC)
        assert first[0]["capturedLists"] == {"products": [{"price": "10"}]}
        assert [first[0]["robotId"], remaining[0][0]["robotId"]] == ["r1", "r2"]
        assert response.primary_keys == ["robotId", "id"]
        assert [request.qs["page"] for request in http.request_history[1:]] == [["1"], ["2"], ["1"]]
        for request in http.request_history:
            assert request.headers["Authorization"] == "Bearer fake-key"
            assert "fromdate" not in request.qs
        if endpoint == "tasks":
            assert all(request.qs["pagesize"] == ["10"] for request in http.request_history[1:])
            assert all(request.qs["sort"] == ["createdat"] for request in http.request_history[1:])
        else:
            assert all("pagesize" not in request.qs for request in http.request_history)


def test_resume_skips_completed_robot_and_resumes_child_page(
    inputs: SourceInputs, manager: Mock, webhook_manager: Mock
) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = BrowseAIResumeConfig(
        paginator_state={
            "completed": ["robots/r1/tasks"],
            "current": "robots/r2/tasks",
            "child_state": {"page": 3},
        }
    )
    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/robots", json={"robots": {"items": [{"id": "r1"}, {"id": "r2"}, {"id": "r3"}]}})
        http.get(f"{BASE_URL}/robots/r2/tasks", json=task_page([{"id": "last"}], False))
        http.get(f"{BASE_URL}/robots/r3/tasks", json=task_page([], False))
        assert list(sync_items(browse_ai_source("fake-key", inputs, manager, webhook_manager))) == [
            [{"id": "last", "robotId": "r2"}]
        ]
        assert [request.qs.get("page") for request in http.request_history] == [None, ["3"], ["1"]]
        assert manager.save_state.call_args.args[0].paginator_state["completed"] == [
            "robots/r1/tasks",
            "robots/r2/tasks",
            "robots/r3/tasks",
        ]


@pytest.mark.parametrize("endpoint", ["robots", "monitors"])
def test_unpaginated_lists_and_empty_results(
    inputs: SourceInputs, manager: Mock, webhook_manager: Mock, endpoint: str
) -> None:
    inputs.schema_name = endpoint
    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/robots", json={"robots": {"items": [{"id": "r1"}]}})
        if endpoint == "monitors":
            http.get(f"{BASE_URL}/robots/r1/monitors", json={"monitors": {"items": []}})
        rows = list(sync_items(browse_ai_source("fake-key", inputs, manager, webhook_manager)))
        assert rows == ([[{"id": "r1"}]] if endpoint == "robots" else [])
        assert all(request.qs == {} for request in http.request_history)


@pytest.mark.parametrize("body", [{"unexpected": []}, {"result": {"robotTasks": {"items": [], "hasMore": "false"}}}])
def test_malformed_response_fails_instead_of_erasing_table(
    inputs: SourceInputs, manager: Mock, webhook_manager: Mock, body: dict[str, Any]
) -> None:
    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/robots", json={"robots": {"items": [{"id": "r1"}]}})
        http.get(f"{BASE_URL}/robots/r1/tasks", json=body)
        with pytest.raises(ValueError):
            list(sync_items(browse_ai_source("fake-key", inputs, manager, webhook_manager)))


@pytest.mark.parametrize(
    "status,expected", [(200, (True, None)), (401, (False, "invalid or expired")), (403, (False, "permissions"))]
)
def test_credential_status_messages(status: int, expected: tuple[bool, str | None]) -> None:
    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/robots", status_code=status, json={"robots": {"items": []}})
        success, message = validate_credentials("fake-key")
        expected_success, expected_message = expected
        assert success == expected_success
        if expected_message is None:
            assert message is None
        else:
            assert message is not None
            assert expected_message in message


@pytest.mark.parametrize(
    "status,error_type,attempts",
    [(401, HTTPError, 1), (403, HTTPError, 1), (429, RESTClientRetryableError, 5), (503, RESTClientRetryableError, 5)],
)
def test_http_failure_classification(status: int, error_type: type[Exception], attempts: int) -> None:
    with requests_mock.Mocker() as http, patch.object(RESTClient._send_request.retry, "sleep"):  # type: ignore[attr-defined]
        http.get(f"{BASE_URL}/robots", status_code=status, json={"messageCode": "test_error"})
        with pytest.raises(error_type):
            validate_credentials("fake-key") if status not in (401, 403) else next(
                RESTClient(base_url=BASE_URL).paginate("robots")
            )
        assert http.call_count == attempts


def test_webhook_rows_deduplicate_by_robot_and_keep_latest_result() -> None:
    rows = [
        {
            "task": {
                "id": "same",
                "robotId": robot,
                "createdAt": 1700000000123,
                "finishedAt": finished,
                "capturedTexts": {"value": value},
            }
        }
        for robot, finished, value in [("r1", 30, "new"), ("r1", 20, "old"), ("r2", 10, "other")]
    ]
    result = webhook_table(pa.Table.from_pylist(rows)).to_pylist()
    assert [(row["robotId"], row["finishedAt"]) for row in result] == [("r1", 30), ("r2", 10)]
    assert result[0]["createdAt"] == datetime.fromtimestamp(1700000000.123, UTC)


def test_webhook_mode_uses_buffer_without_polling(inputs: SourceInputs, manager: Mock, webhook_manager: Mock) -> None:
    webhook_manager.webhook_enabled.return_value = True
    response = browse_ai_source("fake-key", inputs, manager, webhook_manager)
    assert response.items() is webhook_manager.get_items.return_value
    manager.can_resume.assert_not_called()
    assert not response.supports_resume


def test_empty_intermediate_page_advances(inputs: SourceInputs, manager: Mock, webhook_manager: Mock) -> None:
    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/robots", json={"robots": {"items": [{"id": "r1"}]}})
        http.get(
            f"{BASE_URL}/robots/r1/tasks",
            [
                {"json": task_page([], True)},
                {"json": task_page([{"id": "t1"}], False)},
            ],
        )
        assert list(sync_items(browse_ai_source("fake-key", inputs, manager, webhook_manager))) == [
            [{"id": "t1", "robotId": "r1"}]
        ]
        assert [request.qs["page"] for request in http.request_history[1:]] == [["1"], ["2"]]
