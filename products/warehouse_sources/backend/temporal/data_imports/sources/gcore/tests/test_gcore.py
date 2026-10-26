from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gcore.gcore import (
    GcoreCheckpoint,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gcore.source import GcoreSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gcore import GcoreSourceConfig

TRANSPORT = "products.warehouse_sources.backend.temporal.data_imports.sources.gcore.gcore"
NOW = datetime(2026, 1, 5, 12, 30, tzinfo=UTC)


def driver() -> SourceDriver:
    return SourceDriver(GcoreSource(), GcoreSourceConfig(api_key="fake-token"))


@pytest.mark.parametrize(
    "name,path", [("resources", "resources"), ("origin_groups", "origin_groups"), ("ssl_certificates", "sslData")]
)
@pytest.mark.parametrize("last_page", [[], [{"id": 3}]])
def test_list_pagination(name: str, path: str, last_page: list[dict[str, int]]) -> None:
    def answer(request: RecordedRequest) -> ScriptedResponse:
        offset = request.param("offset")
        rows = [{"id": 1}, {"id": 2}] if offset == "0" else last_page
        return ScriptedResponse(json={"count": 3, "next": None if offset != "0" else "unused", "results": rows})

    with patch(f"{TRANSPORT}.PAGE_SIZE", 2):
        result = driver().run(name, answer)

    assert result.raised is None
    assert result.rows == [{"id": 1}, {"id": 2}, *last_page]
    assert result.queries == [
        {"limit": ("2",), "offset": ("0",)},
        {"limit": ("2",), "offset": ("2",)},
    ]
    assert result.paths == [f"/cdn/{path}", f"/cdn/{path}"]
    assert all(request.headers["authorization"] == "APIKey fake-token" for request in result.requests)
    assert result.saved_states == [GcoreCheckpoint(offset=2)]
    assert result.committed_states == [GcoreCheckpoint(offset=2)]


@pytest.mark.parametrize(
    "name,filter_param",
    [("resources", "min_updated"), ("activity_logs", "min_requested_at"), ("purge_statuses", "from_created")],
)
@pytest.mark.parametrize("incremental,watermark", [(False, NOW), (True, None), (True, NOW), (True, NOW.isoformat())])
def test_list_filter_and_resume(
    name: str, filter_param: str, incremental: bool, watermark: datetime | str | None
) -> None:
    result = driver().run(
        name,
        [ScriptedResponse(json={"count": 101, "next": None, "results": [{"id": 101}]})],
        resume_state=GcoreCheckpoint(offset=100),
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
    )

    assert result.raised is None
    assert result.items == [[{"id": 101}]]
    assert result.params("offset") == ["100"]
    assert result.params(filter_param) == [NOW.isoformat() if incremental and watermark else None]
    assert result.response is not None
    assert result.response.sort_mode == "desc"


@pytest.mark.parametrize("name,metric", [("cdn_requests", "requests"), ("cdn_traffic", "sent_bytes")])
@pytest.mark.parametrize("incremental", [False, True])
@patch(f"{TRANSPORT}.datetime", wraps=datetime)
def test_statistics_windows_and_rows(clock: MagicMock, name: str, metric: str, incremental: bool) -> None:
    clock.now.return_value = NOW
    watermark = datetime(2026, 1, 4, 10, tzinfo=UTC)

    def answer(request: RecordedRequest) -> ScriptedResponse:
        start_value = request.param("from")
        end_value = request.param("to")
        assert start_value is not None and end_value is not None
        start = datetime.fromisoformat(start_value)
        end = datetime.fromisoformat(end_value)
        return ScriptedResponse(
            json={"resource": {"42": {"metrics": {metric: [[start.timestamp(), 0], [end.timestamp(), 99]]}}}}
        )

    with patch(f"{TRANSPORT}.HISTORY_DAYS", 2):
        result = driver().run(
            name,
            answer,
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=watermark,
        )

    expected_start = watermark if incremental else datetime(2026, 1, 3, 13, tzinfo=UTC)
    assert result.raised is None
    assert datetime.fromisoformat(result.requests[0].param("from") or "") == expected_start
    assert datetime.fromisoformat(result.requests[-1].param("to") or "") == NOW.replace(minute=0)
    assert len(result.requests) == 2
    for request in result.requests:
        assert datetime.fromisoformat(request.param("to") or "") - datetime.fromisoformat(
            request.param("from") or ""
        ) <= timedelta(days=1)
        assert request.param("metrics") == metric
        assert request.param("granularity") == "1h"
        assert request.param("group_by") == "resource"
        assert request.param("service") == "CDN"
        assert request.headers["authorization"] == "APIKey fake-token"
    assert result.rows == [
        {"resource_id": "42", "timestamp": expected_start, "metric": metric, "value": 0},
        {"resource_id": "42", "timestamp": expected_start + timedelta(days=1), "metric": metric, "value": 0},
    ]
    assert result.response is not None
    assert result.response.primary_keys == ["resource_id", "timestamp", "metric"]
    assert result.response.sort_mode == "desc"
    assert result.committed_states == [
        GcoreCheckpoint(
            window_start=(expected_start + timedelta(days=1)).isoformat(),
            window_end=NOW.replace(minute=0).isoformat(),
        ),
        GcoreCheckpoint(
            window_start=NOW.replace(minute=0).isoformat(),
            window_end=NOW.replace(minute=0).isoformat(),
        ),
    ]
    assert result.saved_states[-1].window_start == NOW.replace(minute=0).isoformat()


@pytest.mark.parametrize("status", [429, 500])
def test_credentials_status_mapping(status: int) -> None:
    response = ScriptedResponse(status=status, json={"message": "Authentication credentials were not provided."})
    script = always(response) if status in (429, 500) else [response]

    with scripted_network(script) as network:
        if status in (429, 500):
            with pytest.raises(HTTPError):
                validate_credentials("fake-token")
        else:
            valid, error = validate_credentials("fake-token")
            assert valid is (status == 200)
            if status == 200:
                assert error is None
            else:
                assert error and "token" in error

    assert network.requests_log
    assert all(request.headers["authorization"] == "APIKey fake-token" for request in network.requests_log)
    assert all(request.param("limit") == "1" for request in network.requests_log)


@pytest.mark.parametrize("status", [401, 403])
def test_sync_authentication_errors_are_terminal(status: int) -> None:
    result = driver().run("resources", [ScriptedResponse(status=status, json={})])

    assert isinstance(result.raised, Exception)
    assert len(result.requests) == 1
    messages = [
        message
        for pattern, message in GcoreSource().get_non_retryable_errors().items()
        if pattern in str(result.raised)
    ]
    assert messages and all(messages)


@pytest.mark.parametrize(
    "name,row,expected",
    [
        (
            "origin_groups",
            {
                "id": 1,
                "auth": {"secret_access_key": "fake-secret"},
                "sources": [{"source": "origin.example.com", "enabled": True, "config": {"secret_key": "fake-secret"}}],
            },
            {"id": 1, "sources": [{"source": "origin.example.com", "enabled": True}]},
        ),
        (
            "activity_logs",
            {
                "id": 1,
                "path": "/origin_groups/7",
                "method": "PUT",
                "data": {"auth": {"secret_access_key": "fake-secret"}},
                "actions": [{"state_after_request": {"auth": {"secret_access_key": "fake-secret"}}}],
            },
            {"id": 1, "path": "/origin_groups/7", "method": "PUT"},
        ),
    ],
)
def test_credentials_are_excluded(name: str, row: dict[str, Any], expected: dict[str, Any]) -> None:
    result = driver().run(name, [ScriptedResponse(json={"count": 1, "results": [row]})])

    assert result.raised is None
    assert result.items == [[expected]]


def test_malformed_statistics_do_not_advance_checkpoint() -> None:
    resume = GcoreCheckpoint(window_start="2026-01-05T10:00:00+00:00", window_end="2026-01-05T12:00:00+00:00")
    result = driver().run("cdn_requests", [ScriptedResponse(json={"unexpected": []})], resume_state=resume)

    assert isinstance(result.raised, ValueError)
    assert "does not contain resource groups" in str(result.raised)
    assert result.saved_states == []
    assert result.final_state == resume


def _window(request: RecordedRequest) -> tuple[datetime, datetime]:
    start, end = request.param("from"), request.param("to")
    assert start is not None and end is not None
    return datetime.fromisoformat(start), datetime.fromisoformat(end)


@pytest.mark.parametrize(
    "mode,expected_windows",
    [
        ("full", [(datetime(2026, 1, 5, 0, tzinfo=UTC), 6), (datetime(2026, 1, 5, 6, tzinfo=UTC), 5)]),
        ("incremental", [(datetime(2026, 1, 5, 4, tzinfo=UTC), 6), (datetime(2026, 1, 5, 10, tzinfo=UTC), 1)]),
        ("resume", [(datetime(2026, 1, 5, 6, tzinfo=UTC), 5)]),
    ],
)
@patch(f"{TRANSPORT}.datetime", wraps=datetime)
def test_logs_windows_pages_and_resume(
    clock: MagicMock, mode: str, expected_windows: list[tuple[datetime, int]]
) -> None:
    clock.now.return_value = NOW

    def answer(request: RecordedRequest) -> ScriptedResponse:
        start, end = _window(request)
        first = int(start.timestamp())
        rows = [{"timestamp": first, "status": 200}, {"timestamp": first + 1, "status": 404}]
        rows.append({"timestamp": int(end.timestamp()), "status": 200})
        offset = int(request.param("offset") or 0)
        return ScriptedResponse(json={"data": rows[offset : offset + 2], "meta": {"count": len(rows)}})

    end = datetime(2026, 1, 5, 11, tzinfo=UTC)
    resume = (
        GcoreCheckpoint(offset=1, window_start=expected_windows[0][0].isoformat(), window_end=end.isoformat())
        if mode == "resume"
        else None
    )
    with patch(f"{TRANSPORT}.LOGS_PAGE_SIZE", 2), patch(f"{TRANSPORT}.LOGS_HISTORY_DAYS", 0):
        result = driver().run(
            "cdn_logs",
            answer,
            resume_state=resume,
            should_use_incremental_field=mode == "incremental",
            db_incremental_field_last_value=datetime(2026, 1, 5, 3, 59, 59, tzinfo=UTC),
        )

    assert result.raised is None
    assert sorted({_window(request) for request in result.requests}) == [
        (start, start + timedelta(hours=hours)) for start, hours in expected_windows
    ]
    assert result.params("offset") == (["1"] if mode == "resume" else ["0", "2"] * len(expected_windows))
    assert set(result.params("ordering")) == {"timestamp"}
    expected_rows = []
    for start, _ in expected_windows:
        if mode != "resume":
            expected_rows.append({"timestamp": start, "status": 200})
        expected_rows.append({"timestamp": start + timedelta(seconds=1), "status": 404})
    assert result.rows == expected_rows
    assert result.final_state == GcoreCheckpoint(window_start=end.isoformat(), window_end=end.isoformat())


@pytest.mark.parametrize(
    "now,incremental,expected_days",
    [
        (NOW, False, [datetime(2026, 1, 3, tzinfo=UTC), datetime(2026, 1, 4, tzinfo=UTC)]),
        (NOW, True, [datetime(2026, 1, 4, tzinfo=UTC)]),
        (datetime(2026, 1, 5, 1, 30, tzinfo=UTC), False, [datetime(2026, 1, 3, tzinfo=UTC)]),
    ],
)
@patch(f"{TRANSPORT}.datetime", wraps=datetime)
def test_daily_statistics_rows_and_days(
    clock: MagicMock, now: datetime, incremental: bool, expected_days: list[datetime]
) -> None:
    clock.now.return_value = now
    body = {
        "resource": {
            "42": {
                "region": {
                    "eu": {"metrics": {"requests": 10, "responses_5xx": 1, "95_percentile": 300}},
                    "na": {"metrics": {"requests": 5}},
                }
            }
        }
    }

    def answer(request: RecordedRequest) -> ScriptedResponse:
        start, _ = _window(request)
        return ScriptedResponse(json=body) if start == expected_days[0] else ScriptedResponse(status=204)

    with patch(f"{TRANSPORT}.HISTORY_DAYS", 2):
        result = driver().run(
            "cdn_daily_statistics",
            answer,
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=datetime(2026, 1, 4, 6, tzinfo=UTC),
        )

    assert result.raised is None
    assert [_window(request) for request in result.requests] == [
        (day, day + timedelta(days=1) - timedelta(seconds=1)) for day in expected_days
    ]
    assert all(query["group_by"] == ("resource", "region") for query in result.queries)
    eu, na = result.rows
    assert (eu["resource_id"], eu["region"], eu["date"]) == ("42", "eu", expected_days[0])
    assert (eu["requests"], eu["responses_5xx"], eu["bandwidth_95_percentile"]) == (10, 1, 300)
    assert (na["region"], na["requests"], na["responses_5xx"]) == ("na", 5, None)
    assert "95_percentile" not in eu
