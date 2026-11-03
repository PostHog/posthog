from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import time_machine
from unittest import mock

import requests

from products.warehouse_sources.sources.kernel._config import KernelSourceConfig
from products.warehouse_sources.sources.kernel.kernel import (
    AUDIT_LOG_MAX_WINDOW,
    PAGE_SIZE,
    KernelResumeConfig,
    KernelRetryableError,
    KernelUnexpectedResponseError,
    _extract_items,
    _next_page,
    kernel_source,
    validate_credentials,
)
from products.warehouse_sources.sources.kernel.settings import ENDPOINTS, KERNEL_ENDPOINTS
from products.warehouse_sources.sources.kernel.source import KernelSource
from products.warehouse_sources.sources.sdk.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)


def _driver() -> SourceDriver:
    return SourceDriver(KernelSource(), KernelSourceConfig(api_key="sk_test"))


def _response(
    items: Any, *, status_code: int = 200, has_more: bool | None = None, next_offset: int | None = None
) -> ScriptedResponse:
    headers: dict[str, str] = {}
    if has_more is not None:
        headers["X-Has-More"] = "true" if has_more else "false"
    if next_offset is not None:
        headers["X-Next-Offset"] = str(next_offset)
    return ScriptedResponse(status=status_code, json=items, headers=headers)


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
    def test_sends_bearer_auth(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_credentials("sk_test") == (True, 200)

        assert network.requests_log[0].headers["authorization"] == "Bearer sk_test"
        # Kernel responses carry secrets the generic sampler can't scrub, so capture must be off.
        assert network.session_options[0]["capture"] is False

    def test_transport_failure_returns_none_status(self) -> None:
        with scripted_network([ConnectionResetError("boom")]):
            assert validate_credentials("sk_test") == (False, None)


class TestGetRows:
    def test_offset_pagination_follows_next_offset_header(self) -> None:
        result = _driver().run(
            "deployments",
            [
                _response([{"id": "a1"}], has_more=True, next_offset=100),
                _response([{"id": "a2"}], has_more=False),
            ],
        )

        assert result.raised is None
        # Row lists, not tables, so the pipeline batches pages together.
        assert result.items == [[{"id": "a1"}], [{"id": "a2"}]]
        assert result.params("offset") == ["0", "100"]
        # The last page carries a terminal cursor, so a hand-off after it reads nothing again.
        assert result.committed_states == [KernelResumeConfig(offset=100), KernelResumeConfig(completed=True)]

    def test_empty_first_page_yields_nothing(self) -> None:
        result = _driver().run("profiles", [_response([], has_more=False)])
        assert result.raised is None
        assert result.rows == []

    def test_empty_page_with_more_pages_keeps_paging(self) -> None:
        # An empty page that still reports X-Has-More must not end the sync early.
        result = _driver().run(
            "apps",
            [
                _response([], has_more=True, next_offset=100),
                _response([{"id": "a1"}], has_more=False),
            ],
        )
        assert result.raised is None
        assert result.rows == [{"id": "a1"}]
        assert result.params("offset") == ["0", "100"]

    @pytest.mark.parametrize(
        "error_code, expect_error",
        [("projects_disabled", False), ("not_found", True)],
    )
    def test_projects_404_is_empty_only_when_projects_are_disabled(self, error_code: str, expect_error: bool) -> None:
        result = _driver().run("projects", [_response({"code": error_code, "message": "nope"}, status_code=404)])

        if expect_error:
            assert isinstance(result.raised, requests.HTTPError)
        else:
            assert result.raised is None
            assert result.rows == []

    def test_unexpected_response_shape_raises(self) -> None:
        result = _driver().run("apps", [_response({"unexpected": [{"id": "a1"}]}, has_more=False)])

        assert isinstance(result.raised, KernelUnexpectedResponseError)

    @pytest.mark.parametrize(
        "endpoint, saved, responses, expected_paths, expected_offsets, row_key, expected_keys",
        [
            pytest.param(
                "deployments",
                KernelResumeConfig(offset=100),
                {"/deployments": [_response([{"id": "a2"}], has_more=False)]},
                ["/deployments"],
                ["100"],
                "id",
                ["a2"],
                id="list_starts_at_saved_offset",
            ),
            pytest.param(
                "browser_telemetry_events",
                KernelResumeConfig(telemetry_session_id="b2", telemetry_cursor=987),
                {
                    "/browsers": [_response([{"session_id": "b3"}, {"session_id": "b1"}, {"session_id": "b2"}])],
                    "/browsers/b2/telemetry/events": [_response([{"seq": 2, "event": {}}], has_more=False)],
                    "/browsers/b3/telemetry/events": [_response([{"seq": 3, "event": {}}], has_more=False)],
                },
                ["/browsers", "/browsers/b2/telemetry/events", "/browsers/b3/telemetry/events"],
                ["0", "987", None],
                "seq",
                [2, 3],
                id="telemetry_skips_finished_sessions_and_resumes_the_saved_one",
            ),
            pytest.param(
                "deployments",
                KernelResumeConfig(completed=True),
                {},
                [],
                [],
                "id",
                [],
                id="list_after_its_last_page_reads_nothing",
            ),
            pytest.param(
                "browser_telemetry_events",
                KernelResumeConfig(completed=True),
                {},
                [],
                [],
                "seq",
                [],
                id="telemetry_after_its_last_page_reads_nothing",
            ),
        ],
    )
    def test_resumes_from_saved_state(
        self,
        endpoint: str,
        saved: KernelResumeConfig,
        responses: dict[str, list[ScriptedResponse]],
        expected_paths: list[str],
        expected_offsets: list[str | None],
        row_key: str,
        expected_keys: list[Any],
    ) -> None:
        result = _driver().run(endpoint, route(responses), resume_state=saved)

        assert result.raised is None
        assert result.paths == expected_paths
        assert result.params("offset") == expected_offsets
        assert [row[row_key] for row in result.rows] == expected_keys

    def test_retries_exhausted_raises(self) -> None:
        result = _driver().run("apps", always(_response(None, status_code=503)))

        assert isinstance(result.raised, KernelRetryableError)
        assert set(result.paths) == {"/apps"}
        assert len(result.requests) >= 5


class TestBrowserTelemetryEvents:
    def _collect(self, responses: dict[str, list[ScriptedResponse]]) -> DriveResult:
        return _driver().run("browser_telemetry_events", route(responses))

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
        result = self._collect(
            {
                "/browsers": [_response(browsers, has_more=False)],
                "/browsers/active/telemetry/events": [
                    _response([{"seq": 1, "event": network_event}], has_more=True, next_offset=987),
                    _response([{"seq": 2, "event": screenshot_event}], has_more=False, next_offset=0),
                ],
                "/browsers/recently_deleted/telemetry/events": [_response([], has_more=False)],
            }
        )

        assert result.raised is None
        assert result.rows == [
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
        assert result.requests[0].param("status") == "all"
        assert not any("/browsers/expired/" in path for path in result.paths)

        first_page, second_page = result.requests[1:3]
        # Without `since` Kernel only returns the last 5 minutes of events.
        since = datetime.fromisoformat(first_page.param("since") or "")
        assert now - timedelta(days=31) < since < now - timedelta(days=29)
        assert first_page.param("offset") is None
        assert second_page.param("offset") == "987"

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
        result = self._collect(
            {
                "/browsers": [_response([{"session_id": "b1"}], has_more=False)],
                "/browsers/b1/telemetry/events": [
                    _response([{"seq": 1, "event": event}], has_more=has_more, next_offset=next_offset)
                ],
            }
        )

        assert result.raised is None
        assert [row["seq"] for row in result.rows] == [1]
        assert len(result.requests) == 2

    def test_skips_browser_purged_after_listing(self) -> None:
        event = {"category": "console", "type": "console_log", "ts": 1, "data": {"text": "hello"}}
        result = self._collect(
            {
                "/browsers": [_response([{"session_id": "gone"}, {"session_id": "b2"}], has_more=False)],
                "/browsers/gone/telemetry/events": [_response({"code": "not_found"}, status_code=404)],
                "/browsers/b2/telemetry/events": [_response([{"seq": 7, "event": event}], has_more=False)],
            }
        )

        assert result.raised is None
        assert [(row["browser_session_id"], row["seq"]) for row in result.rows] == [("b2", 7)]


class TestKernelSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = KERNEL_ENDPOINTS[endpoint]
        response = kernel_source("sk_test", endpoint, mock.MagicMock(), resumable_source_manager=mock.MagicMock())

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


def _fake_audit_log_api(records: list[dict[str, Any]]) -> Callable[[RecordedRequest], ScriptedResponse]:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        start = datetime.fromisoformat(request.param("start") or "")
        end = datetime.fromisoformat(request.param("end") or "")
        in_window = sorted(
            (r for r in records if start <= datetime.fromisoformat(r["timestamp"]) < end),
            key=lambda r: r["timestamp"],
            reverse=True,
        )
        offset = int(request.param("page_token") or "0")
        page = [dict(r) for r in in_window[offset : offset + PAGE_SIZE]]
        has_more = offset + PAGE_SIZE < len(in_window)
        headers = {"X-Has-More": "true" if has_more else "false"}
        if has_more:
            headers["X-Next-Page-Token"] = str(offset + PAGE_SIZE)
        return ScriptedResponse(json=page, headers=headers)

    return respond


class TestAuditLogRows:
    @time_machine.travel(_NOW, tick=False)
    def test_returns_every_record_once_oldest_first(self) -> None:
        busy_hour = _NOW - timedelta(days=3)
        records = [
            _audit_record(_NOW - timedelta(days=300)),
            _audit_record(_NOW - timedelta(days=40)),
            *(_audit_record(busy_hour + timedelta(seconds=i)) for i in range(PAGE_SIZE + 50)),
            # Two indistinguishable requests in the same instant must stay two rows.
            _audit_record(_NOW - timedelta(hours=2), path="/apps"),
            _audit_record(_NOW - timedelta(hours=2), path="/apps"),
        ]
        result = _driver().run("audit_logs", _fake_audit_log_api(records))
        rows = result.rows

        assert result.raised is None
        assert len(rows) == len(records)
        timestamps = [datetime.fromisoformat(r["timestamp"]) for r in rows]
        assert timestamps == sorted(timestamps)
        assert len({r["id"] for r in rows}) == len(records)
        assert (
            max(
                datetime.fromisoformat(request.param("end") or "")
                - datetime.fromisoformat(request.param("start") or "")
                for request in result.requests
            )
            <= AUDIT_LOG_MAX_WINDOW
        )

        # A later incremental sync re-reads records at the watermark; they must keep their ids
        # so merge dedupes them.
        rerun = _driver().run(
            "audit_logs",
            _fake_audit_log_api(records),
            incremental_field="timestamp",
            db_incremental_field_last_value=_NOW - timedelta(hours=2),
        )
        assert rerun.raised is None
        assert {r["id"] for r in rerun.rows} == {r["id"] for r in rows[-2:]}

    @pytest.mark.parametrize(
        "last_value, resume_start, expected_start",
        [
            (None, None, _NOW - timedelta(days=365)),
            (_NOW - timedelta(days=2), None, _NOW - timedelta(days=2)),
            ("2026-05-30T00:00:00Z", None, datetime(2026, 5, 30, tzinfo=UTC)),
            # Kernel keeps one year of audit logs, so an older watermark starts at the retention edge.
            (_NOW - timedelta(days=500), None, _NOW - timedelta(days=365)),
            # A resumed run starts after the last window it handed on.
            (None, "2026-05-10T00:00:00.000000Z", datetime(2026, 5, 10, tzinfo=UTC)),
            (_NOW - timedelta(days=2), "2026-05-10T00:00:00.000000Z", _NOW - timedelta(days=2)),
        ],
    )
    @time_machine.travel(_NOW, tick=False)
    def test_search_starts_at_watermark_or_retention_edge(
        self, last_value: Any, resume_start: str | None, expected_start: datetime
    ) -> None:
        result = _driver().run(
            "audit_logs",
            always(_response([], has_more=False)),
            resume_state=KernelResumeConfig(audit_log_start=resume_start) if resume_start else None,
            incremental_field="timestamp" if last_value is not None else None,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert datetime.fromisoformat(result.requests[0].param("start") or "") == expected_start
        assert datetime.fromisoformat(result.requests[-1].param("end") or "") == _NOW
