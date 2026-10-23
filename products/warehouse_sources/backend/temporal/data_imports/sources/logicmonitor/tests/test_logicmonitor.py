from typing import Any

import pytest

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
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
from products.warehouse_sources.backend.temporal.data_imports.sources.logicmonitor.settings import FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.logicmonitor.source import LogicmonitorSource

BASE_PATH = "/santaba/rest/device/devices"


def config() -> LogicmonitorSourceConfig:
    return LogicmonitorSourceConfig(portal_url="https://example.logicmonitor.com", bearer_token="fake-bearer-token")


def driver() -> SourceDriver:
    return SourceDriver(LogicmonitorSource(), config())


def test_alert_windows_split_and_keep_both_statuses() -> None:
    result = driver().run(
        "alerts",
        [
            ScriptedResponse(json={"items": [{"id": "must-not-yield"}], "total": 10001}),
            ScriptedResponse(json={"items": [{"id": "early", "startEpoch": 3, "cleared": False}], "total": 1}),
            ScriptedResponse(json={"items": [{"id": "later", "startEpoch": 4, "cleared": True}], "total": 1}),
        ],
        resume_state=LogicMonitorResumeConfig(window_start=0, window_end=8, sync_end=8),
    )

    assert result.raised is None
    assert [row["id"] for row in result.rows] == ["early", "later"]
    assert result.params("filter") == [
        'cleared:"*",startEpoch>:0,startEpoch<8',
        'cleared:"*",startEpoch>:0,startEpoch<4',
        'cleared:"*",startEpoch>:4,startEpoch<8',
    ]
    assert result.params("sort") == ["startEpoch"] * 3
    assert result.params("offset") == ["0"] * 3
    assert result.saved_states[0] == LogicMonitorResumeConfig(window_start=0, window_end=4, sync_end=8)
    assert result.saved_states[1] == LogicMonitorResumeConfig(window_start=4, window_end=8, sync_end=8)
    assert result.saved_states[2].complete
    assert result.committed_states[0] == result.saved_states[0]


@pytest.mark.parametrize("total", [10000, 10001, None, -1])
def test_alert_single_second_limit(total: int | None) -> None:
    if total == 10000:
        script = [
            ScriptedResponse(json={"items": [{"id": i} for i in range(offset, offset + 1000)], "total": total})
            for offset in range(0, total, 1000)
        ]
    else:
        script = [ScriptedResponse(json={"items": [], "total": total})]

    result = driver().run(
        "alerts",
        script,
        resume_state=LogicMonitorResumeConfig(window_start=0, window_end=1, sync_end=1),
    )

    if total == 10000:
        assert result.raised is None
        assert [row["id"] for row in result.rows] == list(range(total))
        assert len(result.requests) == 10
        assert result.params("offset")[-1] == "9000"
    else:
        assert isinstance(result.raised, ValueError)
        assert ("too many alerts" if total == 10001 else "valid alert count") in str(result.raised)
        assert len(result.requests) == 1


def test_alert_growth_after_a_page_fails_without_replaying() -> None:
    result = driver().run(
        "alerts",
        [
            ScriptedResponse(json={"items": [{"id": i} for i in range(1000)], "total": 10000}),
            ScriptedResponse(json={"items": [{"id": "extra"}], "total": 10001}),
        ],
        resume_state=LogicMonitorResumeConfig(window_start=0, window_end=101, sync_end=101),
    )

    assert isinstance(result.raised, ValueError)
    assert "counts changed" in str(result.raised)
    assert len(result.requests) == 2


@pytest.mark.parametrize(
    "table, child_path",
    [("device_datasources", "devicedatasources"), ("device_datasource_instances", "instances")],
)
@pytest.mark.parametrize("resume", [False, True])
def test_device_fanout_pages_each_device_and_resumes(table: str, child_path: str, resume: bool) -> None:
    devices = ScriptedResponse(json={"items": [{"id": 7}, {"id": 9}], "total": 2})
    first_device = [
        ScriptedResponse(json={"items": [{"id": i, "deviceId": 7} for i in range(1000)], "total": 1001}),
        ScriptedResponse(json={"items": [{"id": 1000, "deviceId": 7}], "total": 1001}),
    ]
    second_device = ScriptedResponse(json={"items": [{"id": 1, "deviceId": 9}], "total": 1})
    first_path = f"device/devices/7/{child_path}"

    result = driver().run(
        table,
        [devices, second_device] if resume else [devices, *first_device, second_device],
        resume_state=LogicMonitorResumeConfig(fanout_state={"completed": [first_path], "current": None})
        if resume
        else None,
    )

    assert result.raised is None
    assert result.response is not None and result.response.primary_keys == ["deviceId", "id"]
    expected_rows = [(9, 1)] if resume else [*((7, i) for i in range(1001)), (9, 1)]
    assert [(row["deviceId"], row["id"]) for row in result.rows] == expected_rows
    child_paths = [f"/santaba/rest/device/devices/9/{child_path}"]
    if not resume:
        child_paths = [f"/santaba/rest/{first_path}"] * 2 + child_paths
    assert result.paths == [BASE_PATH, *child_paths]
    assert result.params("fields") == ["id"] + [FIELDS[table]] * len(child_paths)
    assert result.params("offset") == ["0"] + (["0"] if resume else ["0", "1000", "0"])
    assert result.final_state is not None and result.final_state.fanout_state["completed"] == [
        first_path,
        f"device/devices/9/{child_path}",
    ]
    assert result.completed_state is None


@pytest.mark.parametrize("table", ["device_datasources", "device_datasource_instances"])
def test_device_fanout_skips_device_deleted_mid_sync(table: str) -> None:
    result = driver().run(
        table,
        [
            ScriptedResponse(json={"items": [{"id": 7}, {"id": 9}], "total": 2}),
            ScriptedResponse(status=404, json={"errorCode": 1404, "errorMessage": "fake not found"}),
            ScriptedResponse(json={"items": [{"id": 1, "deviceId": 9}], "total": 1}),
        ],
    )

    assert result.raised is None
    assert [(row["deviceId"], row["id"]) for row in result.rows] == [(9, 1)]
    assert len(result.requests) == 3


@pytest.mark.parametrize("status", [401, 403, 404])
def test_error_mapping(status: int) -> None:
    answer = ScriptedResponse(status=status, json={"errorCode": status, "errorMessage": "fake error"})
    client = LogicMonitorClient(config())
    with scripted_network([answer]) as network:
        if status in (401, 403):
            assert client.validate_credentials() == (False, AUTH_ERROR if status == 401 else PERMISSION_ERROR)
        else:
            with pytest.raises(HTTPError):
                client.validate_credentials()
    assert len(network.requests_log) == 1

    result = driver().run("devices", [answer])
    assert isinstance(result.raised, HTTPError)
    if status in (401, 403):
        assert any(pattern in str(result.raised) for pattern in LogicmonitorSource().get_non_retryable_errors())
    assert len(result.requests) == 1


def test_credential_probe_uses_one_small_request() -> None:
    with scripted_network([ScriptedResponse(json={"items": [], "total": 0})]) as network:
        assert LogicMonitorClient(config()).validate_credentials() == (True, None)

    assert len(network.requests_log) == 1
    request = network.requests_log[0]
    assert request.path == BASE_PATH
    assert request.param("size") == "1"
    assert request.param("fields") == "id"
    assert request.headers["authorization"] == "Bearer fake-bearer-token"
    assert request.headers["x-version"] == "3"


@pytest.mark.parametrize("body", [{}, {"errorCode": 1000}, {"data": {"items": []}}])
def test_malformed_success_fails(body: dict[str, Any]) -> None:
    result = driver().run("devices", [ScriptedResponse(json=body)])

    assert isinstance(result.raised, ValueError)
    assert "data_selector" in str(result.raised)


def test_redirect_does_not_receive_token() -> None:
    result = driver().run("devices", [ScriptedResponse(status=302, headers={"Location": "https://example.com/"})])

    assert isinstance(result.raised, ValueError)
    assert "redirect" in str(result.raised)
    assert len(result.requests) == 1


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


def test_unknown_table() -> None:
    result = driver().run("unknown", [])

    assert isinstance(result.raised, ValueError)
    assert "Unknown LogicMonitor table" in str(result.raised)
