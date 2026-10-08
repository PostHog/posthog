from collections.abc import Iterable
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

import requests_mock
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.logicmonitor import (
    LogicmonitorSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.logicmonitor.logicmonitor import (
    AUTH_ERROR,
    PERMISSION_ERROR,
    LogicMonitorClient,
    LogicMonitorResumeConfig,
    portal_url,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.logicmonitor.source import LogicmonitorSource

BASE = "https://example.logicmonitor.com/santaba/rest/"
MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.logicmonitor.logicmonitor"


def config() -> LogicmonitorSourceConfig:
    return LogicmonitorSourceConfig(portal_url="https://example.logicmonitor.com", bearer_token="fake-bearer-token")


def inputs(table: str) -> SourceInputs:
    return SourceInputs(
        schema_name=table,
        schema_id="test-schema",
        source_id="test-source",
        team_id=1,
        job_id="test-job",
        should_use_incremental_field=False,
        db_incremental_field_last_value=999,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        logger=MagicMock(),
        reset_pipeline=False,
    )


@pytest.fixture
def manager() -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = False
    return manager


def rows(client: LogicMonitorClient, table: str, manager: MagicMock) -> list[dict[str, Any]]:
    response = client.source_response(inputs(table), manager)
    return [row for page in cast(Iterable[list[dict[str, Any]]], response.items()) for row in page]


def test_alert_windows_split_and_keep_both_statuses(manager: MagicMock) -> None:
    with requests_mock.Mocker() as http, patch(f"{MODULE}.time.time", return_value=7):
        http.get(
            BASE + "alert/alerts",
            [
                {"json": {"items": [{"id": "must-not-yield"}], "total": 10001}},
                {"json": {"items": [{"id": "early", "startEpoch": 3, "cleared": False}], "total": 1}},
                {"json": {"items": [{"id": "later", "startEpoch": 4, "cleared": True}], "total": 1}},
            ],
        )
        assert [row["id"] for row in rows(LogicMonitorClient(config()), "alerts", manager)] == ["early", "later"]
        params = [parse_qs(urlsplit(request.url).query) for request in http.request_history]
        assert [p["filter"] for p in params] == [
            ['cleared:"*",startEpoch>:0,startEpoch<8'],
            ['cleared:"*",startEpoch>:0,startEpoch<4'],
            ['cleared:"*",startEpoch>:4,startEpoch<8'],
        ]
        assert all(p["sort"] == ["startEpoch"] and p["offset"] == ["0"] for p in params)
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved[0] == LogicMonitorResumeConfig(window_start=0, window_end=4, sync_end=8)
        assert saved[1] == LogicMonitorResumeConfig(window_start=4, window_end=8, sync_end=8)
        assert saved[2].complete
        manager.safe_point.assert_called_once()


@pytest.mark.parametrize("total", [10000, 10001, None, -1])
def test_alert_single_second_limit(manager: MagicMock, total: int | None) -> None:
    with requests_mock.Mocker() as http, patch(f"{MODULE}.time.time", return_value=0):
        if total == 10000:
            http.get(
                BASE + "alert/alerts",
                [
                    {"json": {"items": [{"id": i} for i in range(offset, offset + 1000)], "total": total}}
                    for offset in range(0, total, 1000)
                ],
            )
            result = rows(LogicMonitorClient(config()), "alerts", manager)
            assert [row["id"] for row in result] == list(range(total))
            assert http.call_count == 10
            assert http.last_request.qs["offset"] == ["9000"]
        else:
            http.get(BASE + "alert/alerts", json={"items": [], "total": total})
            with pytest.raises(ValueError, match="too many alerts" if total == 10001 else "valid alert count"):
                rows(LogicMonitorClient(config()), "alerts", manager)
            assert http.call_count == 1


def test_alert_growth_after_a_page_fails_without_replaying(manager: MagicMock) -> None:
    with requests_mock.Mocker() as http, patch(f"{MODULE}.time.time", return_value=100):
        http.get(
            BASE + "alert/alerts",
            [
                {"json": {"items": [{"id": i} for i in range(1000)], "total": 10000}},
                {"json": {"items": [{"id": "extra"}], "total": 10001}},
            ],
        )
        with pytest.raises(ValueError, match="counts changed"):
            rows(LogicMonitorClient(config()), "alerts", manager)
        assert http.call_count == 2


@pytest.mark.parametrize("status", [401, 403, 404])
def test_error_mapping(manager: MagicMock, status: int) -> None:
    with requests_mock.Mocker() as http:
        http.get(BASE + "device/devices", status_code=status, json={"errorCode": status, "errorMessage": "fake error"})
        client = LogicMonitorClient(config())
        if status in (401, 403):
            assert client.validate_credentials() == (False, AUTH_ERROR if status == 401 else PERMISSION_ERROR)
        else:
            with pytest.raises(HTTPError):
                client.validate_credentials()
        with pytest.raises(HTTPError) as error:
            rows(client, "devices", manager)
        if status in (401, 403):
            assert any(pattern in str(error.value) for pattern in LogicmonitorSource().get_non_retryable_errors())
        assert http.call_count == 2


def test_credential_probe_uses_one_small_request() -> None:
    with requests_mock.Mocker() as http:
        http.get(BASE + "device/devices", json={"items": [], "total": 0})
        assert LogicMonitorClient(config()).validate_credentials() == (True, None)
        assert http.call_count == 1
        assert http.last_request.qs == {"size": ["1"], "fields": ["id"]}
        assert http.last_request.headers["Authorization"] == "Bearer fake-bearer-token"
        assert http.last_request.headers["X-Version"] == "3"


@pytest.mark.parametrize("body", [{}, {"errorCode": 1000}, {"data": {"items": []}}])
def test_malformed_success_fails(manager: MagicMock, body: dict[str, Any]) -> None:
    with requests_mock.Mocker() as http:
        http.get(BASE + "device/devices", json=body)
        with pytest.raises(ValueError, match="data_selector"):
            rows(LogicMonitorClient(config()), "devices", manager)


def test_redirect_does_not_receive_token(manager: MagicMock) -> None:
    with requests_mock.Mocker() as http:
        http.get(BASE + "device/devices", status_code=302, headers={"Location": "https://example.com/"})
        with pytest.raises(ValueError, match="redirect"):
            rows(LogicMonitorClient(config()), "devices", manager)
        assert http.call_count == 1


@pytest.mark.parametrize(
    "value",
    [
        "http://example.logicmonitor.com",
        "https://localhost",
        "https://127.0.0.1",
        "https://example.logicmonitor.com.example.com",
        "https://example.com",
        "https://user@example.logicmonitor.com",
        "https://example.logicmonitor.com:444",
        "https://example.logicmonitor.com/path",
        "https://example.logicmonitor.com?a=1",
        "https://example.logicmonitor.com#fragment",
        "https://example.logicmonitor.com:invalid",
        "https://-example.logicmonitor.com",
        "https://example-.logicmonitor.com",
    ],
)
def test_reject_invalid_portal(value: str) -> None:
    with pytest.raises(ValueError, match="HTTPS LogicMonitor"):
        portal_url(value)


def test_unknown_table(manager: MagicMock) -> None:
    with pytest.raises(ValueError, match="Unknown LogicMonitor table"):
        LogicMonitorClient(config()).source_response(inputs("unknown"), manager)
