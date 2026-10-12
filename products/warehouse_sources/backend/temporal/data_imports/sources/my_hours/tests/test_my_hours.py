import json
from datetime import datetime
from typing import Any

import pytest
import time_machine
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.my_hours import my_hours
from products.warehouse_sources.backend.temporal.data_imports.sources.my_hours.my_hours import (
    MY_HOURS_BASE_URL,
    MyHoursApiKeyAuth,
    check_access,
    my_hours_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.my_hours.settings import (
    ENDPOINTS,
    MY_HOURS_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# Client retry attempts default; lowered to 1 so a retryable response surfaces at once (no backoff sleep).
RETRY_ATTEMPTS_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.DEFAULT_RETRY_ATTEMPTS"
)


def _response(body: Any, *, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp.url = f"{MY_HOURS_BASE_URL}/Clients"
    if body is not None:
        resp._content = json.dumps(body).encode()
    return resp


def _wire(responses: list[Response]) -> tuple[requests.Session, list[Any]]:
    """Real session whose prepare_request runs for real (so auth + URL are built) but whose send is
    canned. Returns the session and a list that captures each PreparedRequest at send time."""
    session = requests.Session()
    sent: list[Any] = []

    def _send(prepared: Any, **_kwargs: Any) -> Response:
        sent.append(prepared)
        return responses[len(sent) - 1]

    session.send = mock.MagicMock(side_effect=_send)  # type: ignore[method-assign]
    return session, sent


def _pages(source_response: Any) -> list[list[dict[str, Any]]]:
    return list(source_response.items())


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in _pages(source_response) for row in page]


class TestSync:
    @parameterized.expand([("clients", "/Clients"), ("projects", "/Projects/getAll"), ("users", "/Users/getAll")])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_request_targets_the_expected_url(self, endpoint: str, path: str, mock_session: mock.MagicMock) -> None:
        session, sent = _wire([_response([])])
        mock_session.return_value = session

        _rows(my_hours_source(api_key="mh-key", endpoint=endpoint, team_id=1, job_id="j"))

        assert sent[0].url == f"{MY_HOURS_BASE_URL}{path}"

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch(RETRY_ATTEMPTS_PATCH, 1)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_raise_retryable_error(
        self, _name: str, status: int, mock_session: mock.MagicMock
    ) -> None:
        session, _sent = _wire([_response(None, status=status)])
        mock_session.return_value = session

        with pytest.raises(RESTClientRetryableError):
            _rows(my_hours_source(api_key="mh-key", endpoint="clients", team_id=1, job_id="j"))

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(RETRY_ATTEMPTS_PATCH, 1)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_raise_for_status(self, _name: str, status: int, mock_session: mock.MagicMock) -> None:
        session, _sent = _wire([_response({"error": "nope"}, status=status)])
        mock_session.return_value = session

        with pytest.raises(requests.HTTPError):
            _rows(my_hours_source(api_key="mh-key", endpoint="clients", team_id=1, job_id="j"))

    @mock.patch(RETRY_ATTEMPTS_PATCH, 1)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_is_retryable(self, mock_session: mock.MagicMock) -> None:
        # A 200 whose body isn't the expected bare array is treated as transient and reissued.
        session, _sent = _wire([_response({"error": "nope"})])
        mock_session.return_value = session

        with pytest.raises(RESTClientRetryableError):
            _rows(my_hours_source(api_key="mh-key", endpoint="clients", team_id=1, job_id="j"))


class TestAuth:
    def test_declares_raw_key_as_secret_for_redaction(self) -> None:
        assert MyHoursApiKeyAuth("mh-key").secret_values() == ("mh-key",)


class TestCheckAccess:
    def _patch_session(self, monkeypatch: Any, response: Any) -> mock.MagicMock:
        session = mock.MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        monkeypatch.setattr(my_hours, "make_tracked_session", lambda **kwargs: session)
        return session

    @parameterized.expand(
        [
            ("reachable", 200, True, 200, None),
            ("unauthorized", 401, False, 401, None),
            ("forbidden", 403, False, 403, None),
            ("server_error", 500, False, 500, "My Hours returned HTTP 500"),
        ]
    )
    def test_status_mapping(
        self, _name: str, status: int, ok: bool, expected_status: int, expected_message: str | None
    ) -> None:
        response = mock.MagicMock()
        response.status_code = status
        response.ok = ok
        with pytest.MonkeyPatch().context() as mp:
            self._patch_session(mp, response)
            assert check_access("mh-key") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self, monkeypatch: Any) -> None:
        self._patch_session(monkeypatch, requests.ConnectionError("boom"))
        status, message = check_access("mh-key")
        assert status == 0
        assert message is not None and "boom" in message


class TestMyHoursSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(self, endpoint: str, mock_session: mock.MagicMock) -> None:
        mock_session.return_value = mock.MagicMock()
        response = my_hours_source(api_key="mh-key", endpoint=endpoint, team_id=1, job_id="j")
        assert response.name == endpoint
        assert response.primary_keys == MY_HOURS_ENDPOINTS[endpoint].primary_keys
        # The list endpoints carry no stable timestamp, so we don't partition.
        assert response.partition_mode is None


class TestTimeLogs:
    @parameterized.expand(
        [
            ("full_refresh", False, None, [("2010-01-01", "2010-01-31"), ("2010-02-01", "2010-02-21")]),
            ("incremental_from_watermark", True, datetime(2010, 2, 5), [("2010-02-05", "2010-02-21")]),
            ("incremental_watermark_after_today", True, datetime(2010, 3, 10), [("2010-02-21", "2010-02-21")]),
        ]
    )
    @time_machine.travel("2010-02-20 12:00:00", tick=False)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_walks_date_windows(
        self,
        _name: str,
        incremental: bool,
        last_value: datetime | None,
        expected_windows: list[tuple[str, str]],
        mock_session: mock.MagicMock,
    ) -> None:
        session, sent = _wire([_response({"data": []}) for _ in expected_windows])
        mock_session.return_value = session

        _rows(
            my_hours_source(
                api_key="mh-key",
                endpoint="time_logs",
                team_id=1,
                job_id="j",
                should_use_incremental_field=incremental,
                db_incremental_field_last_value=last_value,
            )
        )

        assert all(p.method == "PUT" and p.url == f"{MY_HOURS_BASE_URL}/Reports/activitydx" for p in sent)
        options = [json.loads(p.body)["options"] for p in sent]
        assert [(o["dateFrom"], o["dateTo"]) for o in options] == expected_windows

    @time_machine.travel("2010-02-20 12:00:00", tick=False)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_yields_each_non_empty_window_sorted_by_date(self, mock_session: mock.MagicMock) -> None:
        session, _sent = _wire(
            [
                _response(
                    {
                        "data": [
                            {"logId": 2, "date": "2010-01-20T00:00:00"},
                            {"logId": 1, "date": "2010-01-03T00:00:00"},
                        ],
                        "totalCount": -1,
                    }
                ),
                _response({"data": [], "totalCount": -1}),
            ]
        )
        mock_session.return_value = session

        pages = _pages(my_hours_source(api_key="mh-key", endpoint="time_logs", team_id=1, job_id="j"))

        assert pages == [[{"logId": 1, "date": "2010-01-03T00:00:00"}, {"logId": 2, "date": "2010-01-20T00:00:00"}]]


class TestProjectFanout:
    @mock.patch(RETRY_ATTEMPTS_PATCH, 1)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_project_tasks_flattens_every_task_list(self, mock_session: mock.MagicMock) -> None:
        session, sent = _wire(
            [
                _response([{"id": 11}, {"id": 12}]),
                _response(
                    [
                        {
                            "listName": "Task list",
                            "listNo": 0,
                            "incompletedTasks": [{"id": 1}],
                            "completedTasks": [{"id": 2}],
                            "archivedTasks": [{"id": 3}],
                        }
                    ]
                ),
                _response([]),
            ]
        )
        mock_session.return_value = session

        rows = _rows(my_hours_source(api_key="mh-key", endpoint="project_tasks", team_id=1, job_id="j"))

        assert [p.url for p in sent] == [
            f"{MY_HOURS_BASE_URL}/Projects/getAll",
            f"{MY_HOURS_BASE_URL}/Projects/11/tasklist",
            f"{MY_HOURS_BASE_URL}/Projects/12/tasklist",
        ]
        assert rows == [
            {"id": task_id, "projectId": 11, "taskListName": "Task list", "taskListNo": 0} for task_id in (1, 2, 3)
        ]

    @mock.patch(RETRY_ATTEMPTS_PATCH, 1)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_project_members_carry_project_id_and_skip_deleted_projects(self, mock_session: mock.MagicMock) -> None:
        session, sent = _wire(
            [
                _response([{"id": 11}, {"id": 12}]),
                _response([{"id": 5, "userId": 5, "userName": "A"}]),
                _response({"error": "not found"}, status=404),
            ]
        )
        mock_session.return_value = session

        rows = _rows(my_hours_source(api_key="mh-key", endpoint="project_members", team_id=1, job_id="j"))

        assert sent[1].url == f"{MY_HOURS_BASE_URL}/Projects/11/userlist"
        assert rows == [{"id": 5, "userId": 5, "userName": "A", "projectId": 11}]
