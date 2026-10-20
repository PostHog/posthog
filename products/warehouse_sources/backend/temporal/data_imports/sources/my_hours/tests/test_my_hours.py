from datetime import datetime

import time_machine

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.myhours import (
    MyHoursSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.my_hours.my_hours import (
    MY_HOURS_BASE_URL,
    MyHoursApiKeyAuth,
    check_access,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.my_hours.settings import (
    ENDPOINTS,
    MY_HOURS_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.my_hours.source import MyHoursSource


def _driver() -> SourceDriver:
    return SourceDriver(MyHoursSource(), MyHoursSourceConfig(api_key="mh-key"))


class TestSync:
    @parameterized.expand([("clients", "/Clients"), ("projects", "/Projects/getAll"), ("users", "/Users/getAll")])
    def test_request_targets_the_expected_url(self, endpoint: str, path: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=[])])

        assert result.raised is None
        assert result.urls == [f"{MY_HOURS_BASE_URL}{path}"]

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        result = _driver().run("clients", always(ScriptedResponse(status=status)))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert set(result.paths) == {"/api/Clients"}

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        result = _driver().run("clients", [ScriptedResponse(status=status, json={"error": "nope"})])

        assert isinstance(result.raised, requests.HTTPError)

    def test_non_list_body_is_retryable(self) -> None:
        # A 200 whose body isn't the expected bare array is treated as transient and reissued.
        result = _driver().run("clients", always(ScriptedResponse(json={"error": "nope"})))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert set(result.paths) == {"/api/Clients"}


class TestAuth:
    def test_declares_raw_key_as_secret_for_redaction(self) -> None:
        assert MyHoursApiKeyAuth("mh-key").secret_values() == ("mh-key",)


class TestCheckAccess:
    @parameterized.expand(
        [
            ("reachable", 200, True, 200, None),
        ]
    )
    def test_status_mapping(
        self, _name: str, status: int, _ok: bool, expected_status: int, expected_message: str | None
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            assert check_access("mh-key") == (expected_status, expected_message)

        assert network.requests_log[0].path == "/api/Clients"
        assert network.requests_log[0].headers["authorization"] == "apikey mh-key"

    def test_connection_error_maps_to_zero(self) -> None:
        with scripted_network(always(requests.ConnectionError("boom"))) as network:
            status, message = check_access("mh-key")

        assert status == 0
        assert message is not None and "boom" in message
        assert {request.path for request in network.requests_log} == {"/api/Clients"}


def _empty_answer(request: RecordedRequest) -> ScriptedResponse:
    return ScriptedResponse(json={"data": []} if request.path.endswith("/Reports/activitydx") else [])


class TestMyHoursSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    @time_machine.travel("2010-02-20 12:00:00", tick=False)
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _driver().run(endpoint, _empty_answer)

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == MY_HOURS_ENDPOINTS[endpoint].primary_keys
        # The list endpoints carry no stable timestamp, so we don't partition.
        assert result.response.partition_mode is None


class TestTimeLogs:
    @parameterized.expand(
        [
            ("full_refresh", False, None, [("2010-01-01", "2010-01-31"), ("2010-02-01", "2010-02-21")]),
            ("incremental_from_watermark", True, datetime(2010, 2, 5), [("2010-02-05", "2010-02-21")]),
            ("incremental_watermark_after_today", True, datetime(2010, 3, 10), [("2010-02-21", "2010-02-21")]),
        ]
    )
    @time_machine.travel("2010-02-20 12:00:00", tick=False)
    def test_walks_date_windows(
        self,
        _name: str,
        incremental: bool,
        last_value: datetime | None,
        expected_windows: list[tuple[str, str]],
    ) -> None:
        inputs = {"incremental_field": "date", "db_incremental_field_last_value": last_value} if incremental else {}

        result = _driver().run("time_logs", [ScriptedResponse(json={"data": []}) for _ in expected_windows], **inputs)

        assert result.raised is None
        assert all(r.method == "PUT" and r.url == f"{MY_HOURS_BASE_URL}/Reports/activitydx" for r in result.requests)
        options = [r.json()["options"] for r in result.requests]
        assert [(o["dateFrom"], o["dateTo"]) for o in options] == expected_windows

    @time_machine.travel("2010-02-20 12:00:00", tick=False)
    def test_yields_each_non_empty_window_sorted_by_date(self) -> None:
        result = _driver().run(
            "time_logs",
            [
                ScriptedResponse(
                    json={
                        "data": [
                            {"logId": 2, "date": "2010-01-20T00:00:00"},
                            {"logId": 1, "date": "2010-01-03T00:00:00"},
                        ],
                        "totalCount": -1,
                    }
                ),
                ScriptedResponse(json={"data": [], "totalCount": -1}),
            ],
        )

        assert result.raised is None
        assert result.items == [
            [{"logId": 1, "date": "2010-01-03T00:00:00"}, {"logId": 2, "date": "2010-01-20T00:00:00"}]
        ]


class TestProjectFanout:
    def test_project_tasks_flattens_every_task_list(self) -> None:
        result = _driver().run(
            "project_tasks",
            [
                ScriptedResponse(json=[{"id": 11}, {"id": 12}]),
                ScriptedResponse(
                    json=[
                        {
                            "listName": "Task list",
                            "listNo": 0,
                            "incompletedTasks": [{"id": 1}],
                            "completedTasks": [{"id": 2}],
                            "archivedTasks": [{"id": 3}],
                        }
                    ]
                ),
                ScriptedResponse(json=[]),
            ],
        )

        assert result.raised is None
        assert result.urls == [
            f"{MY_HOURS_BASE_URL}/Projects/getAll",
            f"{MY_HOURS_BASE_URL}/Projects/11/tasklist",
            f"{MY_HOURS_BASE_URL}/Projects/12/tasklist",
        ]
        assert result.rows == [
            {"id": task_id, "projectId": 11, "taskListName": "Task list", "taskListNo": 0} for task_id in (1, 2, 3)
        ]

    def test_project_members_carry_project_id_and_skip_deleted_projects(self) -> None:
        result = _driver().run(
            "project_members",
            [
                ScriptedResponse(json=[{"id": 11}, {"id": 12}]),
                ScriptedResponse(json=[{"id": 5, "userId": 5, "userName": "A"}]),
                ScriptedResponse(status=404, json={"error": "not found"}),
            ],
        )

        assert result.raised is None
        assert result.urls[1] == f"{MY_HOURS_BASE_URL}/Projects/11/userlist"
        assert result.rows == [{"id": 5, "userId": 5, "userName": "A", "projectId": 11}]
