import json
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
import time_machine
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.kernel.kernel import (
    AUDIT_LOG_MAX_WINDOW,
    PAGE_SIZE,
    KernelRetryableError,
    KernelUnexpectedResponseError,
    _extract_items,
    _next_page,
    _redact_sensitive_fields,
    get_audit_log_rows,
    get_rows,
    kernel_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kernel.settings import ENDPOINTS, KERNEL_ENDPOINTS

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.kernel.kernel"


def _response(
    items: Any, *, status_code: int = 200, has_more: bool | None = None, next_offset: int | None = None
) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = items
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 400
    resp.text = "error"
    headers: dict[str, str] = {}
    if has_more is not None:
        headers["X-Has-More"] = "true" if has_more else "false"
    if next_offset is not None:
        headers["X-Next-Offset"] = str(next_offset)
    resp.headers = headers
    return resp


class TestExtractItems:
    @pytest.mark.parametrize(
        "body, expected",
        [
            ([{"id": "a"}], [{"id": "a"}]),
            ([], []),
            ({"data": [{"id": "b"}]}, [{"id": "b"}]),
            ({"items": [{"id": "c"}]}, [{"id": "c"}]),
            ({"results": [{"id": "d"}]}, [{"id": "d"}]),
            ({"data": []}, []),
        ],
    )
    def test_recognized_shapes(self, body: Any, expected: list[dict]) -> None:
        assert _extract_items(body) == expected

    @pytest.mark.parametrize("body", [{"unexpected": [{"id": "e"}]}, {}, None, "oops", 42])
    def test_unexpected_shape_raises(self, body: Any) -> None:
        # A body we can't parse must fail loudly - returning [] would let a full refresh
        # overwrite the table with zero rows.
        with pytest.raises(KernelUnexpectedResponseError):
            _extract_items(body)


class TestRedactSensitiveFields:
    def test_strips_credential_bearing_keys_case_insensitively(self) -> None:
        item = {
            "id": "b1",
            "env_vars": {"SECRET": "x"},
            "CDP_WS_URL": "wss://token@example",
            "webdriver_ws_url": "wss://jwt@example",
            "browser_live_view_url": "https://token@example",
            "region": "us",
        }
        assert _redact_sensitive_fields(item) == {"id": "b1", "region": "us"}


class TestNextPage:
    @pytest.mark.parametrize(
        "headers, page_len, expected",
        [
            # Header wins over offset math.
            ({"X-Has-More": "true", "X-Next-Offset": "300"}, 100, (True, 300)),
            ({"X-Has-More": "false"}, 100, (False, 100)),
            # No header: keep paging only while a full page came back.
            ({}, PAGE_SIZE, (True, PAGE_SIZE)),
            ({}, 5, (False, 5)),
            # Malformed next-offset falls back to offset + page_len.
            ({"X-Has-More": "true", "X-Next-Offset": "not-a-number"}, 100, (True, 100)),
        ],
    )
    def test_next_page(self, headers: dict[str, str], page_len: int, expected: tuple[bool, int]) -> None:
        assert _next_page(headers, current_offset=0, page_len=page_len) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_ok",
        [(200, True), (401, False), (403, False), (500, False)],
    )
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_status_mapping(self, mock_session: Any, status_code: int, expected_ok: bool) -> None:
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        ok, status = validate_credentials("sk_test")
        assert ok is expected_ok
        assert status == status_code

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_sends_bearer_auth(self, mock_session: Any) -> None:
        response = mock.MagicMock()
        response.status_code = 200
        mock_session.return_value.get.return_value = response

        validate_credentials("sk_test")

        headers = mock_session.return_value.get.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer sk_test"
        # Kernel responses carry secrets the generic sampler can't scrub, so capture must be off.
        assert mock_session.call_args.kwargs["capture"] is False

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_transport_failure_returns_none_status(self, mock_session: Any) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("sk_test") == (False, None)


class TestGetRows:
    def _collect(self, endpoint: str) -> list[dict]:
        rows: list[dict] = []
        for table in get_rows("sk_test", endpoint, mock.MagicMock()):
            rows.extend(table.to_pylist())
        return rows

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_single_page_full_refresh(self, mock_session: Any) -> None:
        mock_session.return_value.get.return_value = _response([{"id": "a1"}, {"id": "a2"}], has_more=False)

        rows = self._collect("apps")

        assert rows == [{"id": "a1"}, {"id": "a2"}]
        assert mock_session.return_value.get.call_count == 1
        # Kernel responses carry secrets the generic sampler can't scrub, so capture must be off.
        assert mock_session.call_args.kwargs["capture"] is False

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_offset_pagination_follows_next_offset_header(self, mock_session: Any) -> None:
        mock_session.return_value.get.side_effect = [
            _response([{"id": "a1"}], has_more=True, next_offset=100),
            _response([{"id": "a2"}], has_more=False),
        ]

        rows = self._collect("deployments")

        assert rows == [{"id": "a1"}, {"id": "a2"}]
        urls = [call.kwargs.get("url") or call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert "offset=0" in urls[0]
        assert "offset=100" in urls[1]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_empty_first_page_yields_nothing(self, mock_session: Any) -> None:
        mock_session.return_value.get.return_value = _response([], has_more=False)
        assert self._collect("profiles") == []

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_empty_page_with_more_pages_keeps_paging(self, mock_session: Any) -> None:
        # An empty page that still reports X-Has-More must not end the sync early.
        mock_session.return_value.get.side_effect = [
            _response([], has_more=True, next_offset=100),
            _response([{"id": "a1"}], has_more=False),
        ]
        assert self._collect("apps") == [{"id": "a1"}]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_empty_page_without_advancing_offset_terminates(self, mock_session: Any) -> None:
        # Empty page claiming more pages but with no way to advance the offset must stop,
        # not loop forever re-fetching the same request.
        mock_session.return_value.get.return_value = _response([], has_more=True)
        assert self._collect("apps") == []
        assert mock_session.return_value.get.call_count == 1

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_browsers_requests_all_statuses(self, mock_session: Any) -> None:
        mock_session.return_value.get.return_value = _response([{"id": "b1"}], has_more=False)

        self._collect("browsers")

        url = mock_session.return_value.get.call_args.args[0]
        assert "status=all" in url

    @pytest.mark.parametrize(
        "endpoint, item, expected",
        [
            (
                "browsers",
                {"id": "b1", "browser_live_view_url": "https://token@example", "region": "us"},
                {"id": "b1", "region": "us"},
            ),
            (
                "proxies",
                {
                    "id": "p1",
                    "type": "custom",
                    "config": {"host": "proxy.example.com", "port": 8080, "username": "user", "password": "x"},
                },
                # The batcher stores nested objects as JSON strings.
                {"id": "p1", "type": "custom", "config": '{"host":"proxy.example.com","port":8080}'},
            ),
        ],
    )
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_sensitive_fields_are_stripped_from_rows(
        self, mock_session: Any, endpoint: str, item: dict[str, Any], expected: dict[str, Any]
    ) -> None:
        mock_session.return_value.get.return_value = _response([item], has_more=False)

        rows = self._collect(endpoint)

        assert rows == [expected]

    @pytest.mark.parametrize(
        "error_code, expect_error",
        [("projects_disabled", False), ("not_found", True)],
    )
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_projects_404_is_empty_only_when_projects_are_disabled(
        self, mock_session: Any, error_code: str, expect_error: bool
    ) -> None:
        response = _response({"code": error_code, "message": "nope"}, status_code=404)
        response.raise_for_status.side_effect = requests.HTTPError("404 Client Error", response=response)
        mock_session.return_value.get.return_value = response

        if expect_error:
            with pytest.raises(requests.HTTPError):
                self._collect("projects")
        else:
            assert self._collect("projects") == []

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_unexpected_response_shape_raises(self, mock_session: Any) -> None:
        mock_session.return_value.get.return_value = _response({"unexpected": [{"id": "a1"}]}, has_more=False)

        with pytest.raises(KernelUnexpectedResponseError):
            self._collect("apps")

    @mock.patch("time.sleep")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_retries_retryable_status_then_succeeds(self, mock_session: Any, _sleep: Any) -> None:
        mock_session.return_value.get.side_effect = [
            _response(None, status_code=500),
            _response(None, status_code=429),
            _response([{"id": "a1"}], has_more=False),
        ]

        rows = self._collect("apps")

        assert rows == [{"id": "a1"}]
        assert mock_session.return_value.get.call_count == 3

    @mock.patch("time.sleep")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_retries_exhausted_raises(self, mock_session: Any, _sleep: Any) -> None:
        mock_session.return_value.get.return_value = _response(None, status_code=503)

        with pytest.raises(KernelRetryableError):
            self._collect("apps")

        assert mock_session.return_value.get.call_count == 5


class TestBrowserTelemetryEvents:
    def _collect(self, responses: dict[str, list[mock.MagicMock]]) -> tuple[list[dict], list[str]]:
        requested: list[str] = []

        def _get(url: str, **_kwargs: Any) -> mock.MagicMock:
            requested.append(url)
            return responses[urlparse(url).path].pop(0)

        with mock.patch(f"{_MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = _get
            rows: list[dict] = []
            for table in get_rows("sk_test", "browser_telemetry_events", mock.MagicMock()):
                rows.extend(table.to_pylist())
        return rows, requested

    def test_fans_out_over_browsers_within_retention(self) -> None:
        now = datetime.now(UTC)
        browsers = [
            {"session_id": "active"},
            {"session_id": "recently_deleted", "deleted_at": (now - timedelta(days=2)).isoformat()},
            {"session_id": "expired", "deleted_at": (now - timedelta(days=45)).isoformat()},
        ]
        network_event = {
            "category": "network",
            "type": "network_request",
            "ts": 1700000000000000,
            "data": {
                "url": "https://example.com/api",
                "headers": {"Authorization": "Bearer secret"},
                "post_data": "password=secret",
                "body": '{"access_token": "secret"}',
            },
        }
        screenshot_event = {
            "category": "screenshot",
            "type": "monitor_screenshot",
            "ts": 1700000000000001,
            "data": {"png": "aGk="},
        }
        rows, requested = self._collect(
            {
                "/browsers": [_response(browsers, has_more=False)],
                "/browsers/active/telemetry/events": [
                    _response([{"seq": 1, "event": network_event}], has_more=True, next_offset=987),
                    _response([{"seq": 2, "event": screenshot_event}], has_more=False, next_offset=0),
                ],
                "/browsers/recently_deleted/telemetry/events": [_response([], has_more=False)],
            }
        )

        assert [{**row, "data": json.loads(row["data"])} for row in rows] == [
            {
                "browser_session_id": "active",
                "seq": 1,
                "category": "network",
                "type": "network_request",
                "ts": 1700000000000000,
                "data": {"url": "https://example.com/api"},
            },
            {
                "browser_session_id": "active",
                "seq": 2,
                "category": "screenshot",
                "type": "monitor_screenshot",
                "ts": 1700000000000001,
                "data": {},
            },
        ]
        assert parse_qs(urlparse(requested[0]).query)["status"] == ["all"]
        assert not any("/browsers/expired/" in url for url in requested)

        first_page, second_page = (parse_qs(urlparse(url).query) for url in requested[1:3])
        # Without `since` Kernel only returns the last 5 minutes of events.
        since = datetime.fromisoformat(first_page["since"][0])
        assert now - timedelta(days=31) < since < now - timedelta(days=29)
        assert "offset" not in first_page
        assert second_page["offset"] == ["987"]

    @pytest.mark.parametrize(
        "has_more, next_offset",
        [
            (True, None),
            (True, 0),
            (False, 50),
        ],
    )
    def test_stops_when_cursor_cannot_advance(self, has_more: bool, next_offset: int | None) -> None:
        event = {"category": "page", "type": "page_load", "ts": 1}
        rows, requested = self._collect(
            {
                "/browsers": [_response([{"session_id": "b1"}], has_more=False)],
                "/browsers/b1/telemetry/events": [
                    _response([{"seq": 1, "event": event}], has_more=has_more, next_offset=next_offset)
                ],
            }
        )

        assert [row["seq"] for row in rows] == [1]
        assert len(requested) == 2

    def test_skips_browser_purged_after_listing(self) -> None:
        event = {"category": "console", "type": "console_log", "ts": 1, "data": {"text": "hello"}}
        rows, _ = self._collect(
            {
                "/browsers": [_response([{"session_id": "gone"}, {"session_id": "b2"}], has_more=False)],
                "/browsers/gone/telemetry/events": [_response({"code": "not_found"}, status_code=404)],
                "/browsers/b2/telemetry/events": [_response([{"seq": 7, "event": event}], has_more=False)],
            }
        )

        assert [(row["browser_session_id"], row["seq"]) for row in rows] == [("b2", 7)]


class TestKernelSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = KERNEL_ENDPOINTS[endpoint]
        response = kernel_source("sk_test", endpoint, mock.MagicMock())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if endpoint == "audit_logs":
            assert response.partition_mode == "datetime"
            assert response.partition_keys == ["timestamp"]
        else:
            # Partitioning is left to the pipeline's auto-detection for this alpha release.
            assert response.partition_mode is None
            assert response.partition_keys is None


_NOW = datetime(2026, 6, 1, tzinfo=UTC)


def _audit_record(at: datetime, path: str = "/browsers") -> dict[str, Any]:
    return {
        "timestamp": at.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "auth_strategy": "api_key",
        "user_id": "user_1",
        "email": "user@example.com",
        "method": "GET",
        "path": path,
        "route": path,
        "status": 200,
        "domain": "api.example.com",
        "duration_ms": 12,
        "client_ip": "192.0.2.1",
        "user_agent": "test-agent",
    }


def _fake_audit_log_api(records: list[dict[str, Any]], requested_windows: list[timedelta]) -> Any:
    def get(url: str, headers: dict[str, str], timeout: int) -> mock.MagicMock:
        query = parse_qs(urlparse(url).query)
        start = datetime.fromisoformat(query["start"][0])
        end = datetime.fromisoformat(query["end"][0])
        requested_windows.append(end - start)
        in_window = sorted(
            (r for r in records if start <= datetime.fromisoformat(r["timestamp"]) < end),
            key=lambda r: r["timestamp"],
            reverse=True,
        )
        offset = int(query.get("page_token", ["0"])[0])
        page = [dict(r) for r in in_window[offset : offset + PAGE_SIZE]]
        has_more = offset + PAGE_SIZE < len(in_window)
        response = _response(page, has_more=has_more)
        if has_more:
            response.headers["X-Next-Page-Token"] = str(offset + PAGE_SIZE)
        return response

    return get


class TestAuditLogRows:
    def _collect(self, last_value: Any = None) -> list[dict]:
        rows: list[dict] = []
        for table in get_audit_log_rows("sk_test", mock.MagicMock(), db_incremental_field_last_value=last_value):
            rows.extend(table.to_pylist())
        return rows

    @time_machine.travel(_NOW, tick=False)
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_returns_every_record_once_oldest_first(self, mock_session: Any) -> None:
        busy_hour = _NOW - timedelta(days=3)
        records = [
            _audit_record(_NOW - timedelta(days=300)),
            _audit_record(_NOW - timedelta(days=40)),
            *(_audit_record(busy_hour + timedelta(seconds=i)) for i in range(PAGE_SIZE + 50)),
            # Two indistinguishable requests in the same instant must stay two rows.
            _audit_record(_NOW - timedelta(hours=2), path="/apps"),
            _audit_record(_NOW - timedelta(hours=2), path="/apps"),
        ]
        requested_windows: list[timedelta] = []
        mock_session.return_value.get.side_effect = _fake_audit_log_api(records, requested_windows)

        rows = self._collect()

        assert len(rows) == len(records)
        timestamps = [datetime.fromisoformat(r["timestamp"]) for r in rows]
        assert timestamps == sorted(timestamps)
        assert len({r["id"] for r in rows}) == len(records)
        assert max(requested_windows) <= AUDIT_LOG_MAX_WINDOW

        # A later incremental sync re-reads records at the watermark; they must keep their ids
        # so merge dedupes them.
        mock_session.return_value.get.side_effect = _fake_audit_log_api(records, [])
        rerun = self._collect(last_value=_NOW - timedelta(hours=2))
        assert {r["id"] for r in rerun} == {r["id"] for r in rows[-2:]}

    @pytest.mark.parametrize(
        "last_value, expected_start",
        [
            (None, _NOW - timedelta(days=365)),
            (_NOW - timedelta(days=2), _NOW - timedelta(days=2)),
            ("2026-05-30T00:00:00Z", datetime(2026, 5, 30, tzinfo=UTC)),
            # Kernel keeps one year of audit logs, so an older watermark starts at the retention edge.
            (_NOW - timedelta(days=500), _NOW - timedelta(days=365)),
        ],
    )
    @time_machine.travel(_NOW, tick=False)
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_search_starts_at_watermark_or_retention_edge(
        self, mock_session: Any, last_value: Any, expected_start: datetime
    ) -> None:
        mock_session.return_value.get.return_value = _response([], has_more=False)

        self._collect(last_value=last_value)

        first_query = parse_qs(urlparse(mock_session.return_value.get.call_args_list[0].args[0]).query)
        assert datetime.fromisoformat(first_query["start"][0]) == expected_start
        last_query = parse_qs(urlparse(mock_session.return_value.get.call_args_list[-1].args[0]).query)
        assert datetime.fromisoformat(last_query["end"][0]) == _NOW
