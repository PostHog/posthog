import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

from requests import HTTPError, PreparedRequest, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.gcore.gcore import (
    GcoreCheckpoint,
    gcore_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gcore.source import GcoreSource

TRANSPORT = "products.warehouse_sources.backend.temporal.data_imports.sources.gcore.gcore"
NOW = datetime(2026, 1, 5, 12, 30, tzinfo=UTC)


def inputs_for(name: str, incremental: bool = False, watermark: datetime | str | None = None) -> SourceInputs:
    inputs = MagicMock(spec=SourceInputs)
    inputs.schema_name = name
    inputs.team_id = 1
    inputs.job_id = "test-gcore"
    inputs.should_use_incremental_field = incremental
    inputs.db_incremental_field_last_value = watermark
    return inputs


def manager_for(resume: GcoreCheckpoint | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def items_for(response: SourceResponse) -> Iterable[Any]:
    return cast(Iterable[Any], response.items())


def response_for(request: PreparedRequest, body: object, status: int = 200) -> Response:
    response = Response()
    response.status_code = status
    assert request.url is not None
    response.url = request.url
    response.request = request
    response._content = json.dumps(body).encode()
    response.headers["Content-Type"] = "application/json"
    return response


@pytest.mark.parametrize(
    "name,path", [("resources", "resources"), ("origin_groups", "origin_groups"), ("ssl_certificates", "sslData")]
)
@pytest.mark.parametrize("last_page", [[], [{"id": 3}]])
def test_list_pagination(name: str, path: str, last_page: list[dict[str, int]]) -> None:
    requests: list[PreparedRequest] = []
    manager = manager_for()

    def send(request: PreparedRequest, **kwargs: Any) -> Response:
        requests.append(request)
        query = parse_qs(urlsplit(request.url or "").query)
        offset = int(query["offset"][0])
        rows = [{"id": 1}, {"id": 2}] if offset == 0 else last_page
        return response_for(request, {"count": 3, "next": None if offset else "unused", "results": rows})

    with patch(f"{TRANSPORT}.PAGE_SIZE", 2), patch("requests.Session.send", side_effect=send):
        response = gcore_source("fake-token", inputs_for(name), manager)
        rows = [row for page in items_for(response) for row in page]

    assert rows == [{"id": 1}, {"id": 2}, *last_page]
    assert [parse_qs(urlsplit(request.url or "").query) for request in requests] == [
        {"limit": ["2"], "offset": ["0"]},
        {"limit": ["2"], "offset": ["2"]},
    ]
    assert all(urlsplit(request.url or "").path == f"/cdn/{path}" for request in requests)
    assert all(request.headers["Authorization"] == "APIKey fake-token" for request in requests)
    manager.save_state.assert_called_once_with(GcoreCheckpoint(offset=2))


@pytest.mark.parametrize("incremental,watermark", [(False, NOW), (True, None), (True, NOW), (True, NOW.isoformat())])
def test_resource_filter_and_resume(incremental: bool, watermark: datetime | str | None) -> None:
    requests: list[PreparedRequest] = []

    def send(request: PreparedRequest, **kwargs: Any) -> Response:
        requests.append(request)
        return response_for(request, {"count": 101, "next": None, "results": [{"id": 101}]})

    with patch("requests.Session.send", side_effect=send):
        response = gcore_source(
            "fake-token", inputs_for("resources", incremental, watermark), manager_for(GcoreCheckpoint(offset=100))
        )
        assert list(items_for(response)) == [[{"id": 101}]]
    query = parse_qs(urlsplit(requests[0].url or "").query)
    assert query["offset"] == ["100"]
    assert query.get("min_updated") == ([NOW.isoformat()] if incremental and watermark else None)
    assert response.sort_mode == "desc"


@pytest.mark.parametrize("name,metric", [("cdn_requests", "requests"), ("cdn_traffic", "sent_bytes")])
@pytest.mark.parametrize("incremental", [False, True])
@patch(f"{TRANSPORT}.datetime", wraps=datetime)
def test_statistics_windows_and_rows(clock: MagicMock, name: str, metric: str, incremental: bool) -> None:
    clock.now.return_value = NOW
    requests: list[PreparedRequest] = []
    manager = manager_for()
    watermark = datetime(2026, 1, 4, 10, tzinfo=UTC)

    def send(request: PreparedRequest, **kwargs: Any) -> Response:
        requests.append(request)
        query = parse_qs(urlsplit(request.url or "").query)
        start = datetime.fromisoformat(query["from"][0])
        end = datetime.fromisoformat(query["to"][0])
        assert manager.save_state.call_count >= len(requests) - 1
        return response_for(
            request, {"resource": {"42": {"metrics": {metric: [[start.timestamp(), 0], [end.timestamp(), 99]]}}}}
        )

    with patch(f"{TRANSPORT}.HISTORY_DAYS", 2), patch("requests.Session.send", side_effect=send):
        response = gcore_source("fake-token", inputs_for(name, incremental, watermark), manager)
        rows = [row for page in items_for(response) for row in page]
    expected_start = watermark if incremental else datetime(2026, 1, 3, 13, tzinfo=UTC)
    queries = [parse_qs(urlsplit(request.url or "").query) for request in requests]
    assert datetime.fromisoformat(queries[0]["from"][0]) == expected_start
    assert datetime.fromisoformat(queries[-1]["to"][0]) == NOW.replace(minute=0)
    assert len(requests) == 2
    for query, request in zip(queries, requests):
        assert datetime.fromisoformat(query["to"][0]) - datetime.fromisoformat(query["from"][0]) <= timedelta(days=1)
        assert query["metrics"] == [metric]
        assert query["granularity"] == ["1h"]
        assert query["group_by"] == ["resource"]
        assert query["service"] == ["CDN"]
        assert request.headers["Authorization"] == "APIKey fake-token"
    assert rows == [
        {"resource_id": "42", "timestamp": expected_start, "metric": metric, "value": 0},
        {"resource_id": "42", "timestamp": expected_start + timedelta(days=1), "metric": metric, "value": 0},
    ]
    assert response.primary_keys == ["resource_id", "timestamp", "metric"]
    assert response.sort_mode == "desc"
    assert manager.safe_point.call_count == 2
    assert manager.save_state.call_args.args[0].window_start == NOW.replace(minute=0).isoformat()


@pytest.mark.parametrize("status", [200, 401, 403, 429, 500])
def test_credentials_status_mapping(status: int) -> None:
    requests: list[PreparedRequest] = []

    def send(request: PreparedRequest, **kwargs: Any) -> Response:
        requests.append(request)
        return response_for(request, {"message": "Authentication credentials were not provided."}, status)

    with patch("requests.Session.send", side_effect=send):
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
    assert len(requests) == 1
    assert requests[0].headers["Authorization"] == "APIKey fake-token"
    assert parse_qs(urlsplit(requests[0].url or "").query) == {"limit": ["1"]}


@pytest.mark.parametrize("status", [401, 403])
def test_sync_authentication_errors_are_terminal(status: int) -> None:
    with patch(
        "requests.Session.send", side_effect=lambda request, **kwargs: response_for(request, {}, status)
    ) as send:
        with pytest.raises(Exception) as error:
            response = gcore_source("fake-token", inputs_for("resources"), manager_for())
            list(items_for(response))
    assert send.call_count == 1
    messages = [
        message for pattern, message in GcoreSource().get_non_retryable_errors().items() if pattern in str(error.value)
    ]
    assert messages and all(messages)


def test_unknown_table_fails_before_network() -> None:
    with patch("requests.Session.send") as send:
        with pytest.raises(ValueError, match="Unknown Gcore table"):
            gcore_source("fake-token", inputs_for("unknown"), manager_for())
    send.assert_not_called()


def test_origin_credentials_are_excluded() -> None:
    body = {
        "count": 1,
        "results": [
            {
                "id": 1,
                "auth": {"secret_access_key": "fake-secret"},
                "sources": [{"source": "origin.example.com", "enabled": True, "config": {"secret_key": "fake-secret"}}],
            }
        ],
    }
    with patch("requests.Session.send", side_effect=lambda request, **kwargs: response_for(request, body)):
        response = gcore_source("fake-token", inputs_for("origin_groups"), manager_for())
        rows = list(items_for(response))
    assert rows == [[{"id": 1, "sources": [{"source": "origin.example.com", "enabled": True}]}]]


@patch(f"{TRANSPORT}.datetime", wraps=datetime)
def test_malformed_statistics_do_not_advance_checkpoint(clock: MagicMock) -> None:
    clock.now.return_value = NOW
    manager = manager_for(
        GcoreCheckpoint(window_start="2026-01-05T10:00:00+00:00", window_end="2026-01-05T12:00:00+00:00")
    )
    with patch(
        "requests.Session.send", side_effect=lambda request, **kwargs: response_for(request, {"unexpected": []})
    ):
        with pytest.raises(ValueError, match="does not contain resource groups"):
            response = gcore_source("fake-token", inputs_for("cdn_requests"), manager)
            list(items_for(response))
    manager.save_state.assert_not_called()
