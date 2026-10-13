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


@pytest.mark.parametrize("incremental,watermark", [(False, NOW), (True, None), (True, NOW), (True, NOW.isoformat())])
def test_resource_filter_and_resume(incremental: bool, watermark: datetime | str | None) -> None:
    result = driver().run(
        "resources",
        [ScriptedResponse(json={"count": 101, "next": None, "results": [{"id": 101}]})],
        resume_state=GcoreCheckpoint(offset=100),
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
    )

    assert result.raised is None
    assert result.items == [[{"id": 101}]]
    assert result.params("offset") == ["100"]
    assert result.params("min_updated") == [NOW.isoformat() if incremental and watermark else None]
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


@pytest.mark.parametrize("status", [200, 401, 403, 429, 500])
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


def test_unknown_table_fails_before_network() -> None:
    result = driver().run("unknown", [])

    assert isinstance(result.raised, ValueError)
    assert "Unknown Gcore table" in str(result.raised)
    assert result.requests == []


def test_origin_credentials_are_excluded() -> None:
    body: dict[str, Any] = {
        "count": 1,
        "results": [
            {
                "id": 1,
                "auth": {"secret_access_key": "fake-secret"},
                "sources": [{"source": "origin.example.com", "enabled": True, "config": {"secret_key": "fake-secret"}}],
            }
        ],
    }
    result = driver().run("origin_groups", [ScriptedResponse(json=body)])

    assert result.raised is None
    assert result.items == [[{"id": 1, "sources": [{"source": "origin.example.com", "enabled": True}]}]]


def test_malformed_statistics_do_not_advance_checkpoint() -> None:
    resume = GcoreCheckpoint(window_start="2026-01-05T10:00:00+00:00", window_end="2026-01-05T12:00:00+00:00")
    result = driver().run("cdn_requests", [ScriptedResponse(json={"unexpected": []})], resume_state=resume)

    assert isinstance(result.raised, ValueError)
    assert "does not contain resource groups" in str(result.raised)
    assert result.saved_states == []
    assert result.final_state == resume
