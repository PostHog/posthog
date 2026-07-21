import json
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from freezegun import freeze_time
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.deno_deploy.deno_deploy import (
    DENO_DEPLOY_ENDPOINTS,
    DenoDeployResumeConfig,
    _as_utc_datetime,
    _format_rfc3339,
    _log_row_id,
    _reshape_analytics,
    _time_window_params,
    deno_deploy_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the deno_deploy module.
DENO_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.deno_deploy.deno_deploy.make_tracked_session"
)


def _response(
    body: Any,
    *,
    status: int = 200,
    link: str | None = None,
    location: str | None = None,
) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    if link:
        resp.headers["Link"] = link
    if location:
        resp.headers["Location"] = location
    return resp


def _make_manager(resume_state: DenoDeployResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session; return a list capturing each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so a copy is snapshotted when
    each request is prepared. The prepared stand-in carries the request URL so the SSRF host check
    (which reads ``prepared.url``) sees the real target host.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> SimpleNamespace:
        param_snapshots.append(dict(request.params or {}))
        return SimpleNamespace(url=request.url)

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any) -> Any:
    return deno_deploy_source(
        access_token="ddo_test",
        endpoint=endpoint,
        team_id=1,
        job_id="job",
        resumable_source_manager=manager,
        **kwargs,
    )


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestPureHelpers:
    @parameterized.expand(
        [
            ("utc", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_treated_as_utc", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format_rfc3339(self, _name: str, value: datetime, expected: str) -> None:
        result = _format_rfc3339(value)
        assert result == expected
        assert "+00:00" not in result

    def test_log_row_id_stable_and_content_addressed(self) -> None:
        log = {"timestamp": "2026-01-01T00:00:00Z", "level": "info", "message": "hi", "trace_id": "t1"}
        first = _log_row_id("app-1", log)
        assert first == _log_row_id("app-1", dict(log))  # same content -> same id
        assert first != _log_row_id("app-2", log)  # different app -> different id
        assert first != _log_row_id("app-1", {**log, "message": "bye"})  # different content -> different id

    def test_reshape_analytics_columnar_to_rows(self) -> None:
        body = {
            "fields": [{"name": "time", "type": "time"}, {"name": "request_count", "type": "number"}],
            "values": [["2026-01-01T00:00:00Z", 5], ["2026-01-01T00:15:00Z", 9]],
        }
        assert _reshape_analytics(body, "app-1", "my-app") == [
            {"time": "2026-01-01T00:00:00Z", "request_count": 5, "app_id": "app-1", "app_slug": "my-app"},
            {"time": "2026-01-01T00:15:00Z", "request_count": 9, "app_id": "app-1", "app_slug": "my-app"},
        ]

    def test_reshape_analytics_empty_values(self) -> None:
        assert _reshape_analytics({"fields": [{"name": "time"}], "values": []}, "a", "s") == []

    @freeze_time("2026-06-01T12:00:00Z")
    def test_time_window_first_sync_uses_lookback(self) -> None:
        start, end = _time_window_params(DENO_DEPLOY_ENDPOINTS["logs"], True, None)
        assert start == "2026-05-25T12:00:00Z"  # now - 7d default lookback
        assert end == "2026-06-01T12:00:00Z"

    @freeze_time("2026-06-01T12:00:00Z")
    def test_time_window_incremental_subtracts_lookback(self) -> None:
        start, _ = _time_window_params(DENO_DEPLOY_ENDPOINTS["logs"], True, datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC))
        assert start == "2026-06-01T09:55:00Z"  # watermark - 5min lookback

    @freeze_time("2026-06-01T12:00:00Z")
    def test_time_window_future_watermark_clamped(self) -> None:
        start, end = _time_window_params(DENO_DEPLOY_ENDPOINTS["analytics"], True, datetime(2027, 1, 1, tzinfo=UTC))
        assert start == "2026-06-01T11:30:00Z"  # min(future, now) - 30min lookback
        assert end == "2026-06-01T12:00:00Z"

    @parameterized.expand([("date", date(2026, 1, 1), True), ("string", "cursor", False)])
    def test_as_utc_datetime(self, _name: str, value: Any, coerces: bool) -> None:
        result = _as_utc_datetime(value)
        if coerces:
            assert result is not None and result.tzinfo is UTC
        else:
            assert result is None


class TestListEndpoint:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_apps_follows_link_header_and_checkpoints(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(
                    [{"id": "a1", "slug": "one"}],
                    link='<https://api.deno.com/v2/apps?cursor=p2&limit=100>; rel="next"',
                ),
                _response([{"id": "a2", "slug": "two"}]),
            ],
        )
        manager = _make_manager()
        rows = _rows(_source("apps", manager))

        assert [r["id"] for r in rows] == ["a1", "a2"]  # rows used as-is, both pages
        # Checkpoint saved after the first page points at the not-yet-fetched next URL.
        manager.save_state.assert_called_once_with(
            DenoDeployResumeConfig(next_url="https://api.deno.com/v2/apps?cursor=p2&limit=100")
        )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_apps_resumes_from_saved_url(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "a2", "slug": "two"}])])
        manager = _make_manager(DenoDeployResumeConfig(next_url="https://api.deno.com/v2/apps?cursor=p2"))

        rows = _rows(_source("apps", manager))
        assert [r["id"] for r in rows] == ["a2"]
        assert params[0] == {}  # resumed via the seeded next URL, not the default first page params

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_apps_single_short_page_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "a1", "slug": "one"}])])
        manager = _make_manager()

        _rows(_source("apps", manager))
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()


class TestFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_revisions_inject_parent_app_context(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response([{"id": "a1", "slug": "one"}, {"id": "a2", "slug": "two"}]),  # /v2/apps
                _response([{"id": "r1", "status": "success"}]),  # a1 revisions
                _response([{"id": "r2", "status": "failed"}]),  # a2 revisions
            ],
        )
        rows = _rows(_source("revisions", _make_manager()))

        assert rows == [
            {"id": "r1", "status": "success", "app_id": "a1", "app_slug": "one"},
            {"id": "r2", "status": "failed", "app_id": "a2", "app_slug": "two"},
        ]
        assert params[1]["limit"] == 100  # child list uses the default page size

    @freeze_time("2026-06-01T12:00:00Z")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_logs_paginate_via_next_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response([{"id": "a1", "slug": "one"}]),  # /v2/apps
                _response({"logs": [{"timestamp": "2026-06-01T10:00:00Z", "message": "m1"}], "next_cursor": "c2"}),
                _response({"logs": [{"timestamp": "2026-06-01T11:00:00Z", "message": "m2"}], "next_cursor": None}),
            ],
        )
        manager = _make_manager()
        rows = _rows(_source("logs", manager, should_use_incremental_field=True, db_incremental_field_last_value=None))

        assert [r["message"] for r in rows] == ["m1", "m2"]
        assert all(len(r["id"]) == 64 and r["app_id"] == "a1" and r["app_slug"] == "one" for r in rows)
        # First logs page carries the bounded window; the second follows the body cursor.
        assert params[1]["start"] and params[1]["end"] and params[1]["limit"] == 1000 and "cursor" not in params[1]
        assert params[2]["cursor"] == "c2"
        # Checkpoint persists the fan-out resume snapshot carrying the cursor.
        saved = [c.args[0] for c in manager.save_state.call_args_list]
        assert any(s.fanout_state and s.fanout_state.get("child_state") == {"cursor": "c2"} for s in saved)

    @freeze_time("2026-06-01T12:00:00Z")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_analytics_columnar_explode_with_window(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response([{"id": "a1", "slug": "one"}]),  # /v2/apps
                _response(
                    {
                        "fields": [{"name": "time"}, {"name": "request_count"}],
                        "values": [["2026-06-01T00:00:00Z", 5], ["2026-06-01T00:15:00Z", 9]],
                    }
                ),
            ],
        )
        rows = _rows(_source("analytics", _make_manager(), should_use_incremental_field=True))

        assert rows == [
            {"time": "2026-06-01T00:00:00Z", "request_count": 5, "app_id": "a1", "app_slug": "one"},
            {"time": "2026-06-01T00:15:00Z", "request_count": 9, "app_id": "a1", "app_slug": "one"},
        ]
        assert params[1]["since"] and params[1]["until"]  # server-side time filters present

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fanout_resumes_and_skips_completed_app(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": "a1", "slug": "one"}, {"id": "a2", "slug": "two"}]),  # /v2/apps
                _response([{"id": "r2", "status": "success"}]),  # a2 revisions only
            ],
        )
        manager = _make_manager(
            DenoDeployResumeConfig(
                fanout_state={"completed": ["/v2/apps/a1/revisions"], "current": None, "child_state": None}
            )
        )
        rows = _rows(_source("revisions", manager))

        assert [r["id"] for r in rows] == ["r2"]  # a1 skipped, resumed at a2
        assert rows[0]["app_id"] == "a2"
        assert session.send.call_count == 2  # apps list + a2 only

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_legacy_resume_state_restarts_fanout(self, MockSession) -> None:
        # A pre-migration state carrying only the legacy app_id bookmark must still parse and simply
        # restart the fan-out (merge dedupes the re-pulled rows).
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": "a1", "slug": "one"}]),  # /v2/apps
                _response([{"id": "r1", "status": "success"}]),  # a1 revisions
            ],
        )
        manager = _make_manager(DenoDeployResumeConfig(next_url=None, app_id="a2"))
        rows = _rows(_source("revisions", manager))
        assert [r["id"] for r in rows] == ["r1"]  # fresh full walk, a1 not skipped


class TestSsrfGuards:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_off_host_link_is_rejected(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(
                    [{"id": "a1", "slug": "one"}], link='<https://evil.example.com/v2/apps?cursor=p2>; rel="next"'
                ),
                _response([{"id": "a2", "slug": "two"}]),
            ],
        )
        with pytest.raises(ValueError, match="disallowed host"):
            _rows(_source("apps", _make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_redirect_is_rejected(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({}, status=302, location="https://evil.example.com")])
        with pytest.raises(ValueError, match="[Rr]edirect"):
            _rows(_source("apps", _make_manager()))


class TestSourceResponse:
    @parameterized.expand(
        [
            ("apps", ["id"], "created_at", False),
            ("revisions", ["app_id", "id"], "created_at", False),
            ("domains", ["id"], "created_at", False),
            ("analytics", ["app_id", "time"], "time", True),
            ("logs", ["id"], "timestamp", True),
        ]
    )
    def test_response_shape(self, endpoint: str, pk: list[str], partition: str, incremental: bool) -> None:
        response = _source(endpoint, _make_manager(), should_use_incremental_field=incremental)
        assert response.name == endpoint
        assert response.primary_keys == pk
        assert response.partition_keys == [partition]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "week"
        assert response.sort_mode == "asc"


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    @mock.patch(DENO_SESSION_PATCH)
    def test_status_mapping(self, _name: str, status: int, expected_ok: bool, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        ok, error = validate_credentials("ddo_test")
        assert ok is expected_ok
        assert (error is None) is expected_ok

    @mock.patch(DENO_SESSION_PATCH)
    def test_network_error_is_swallowed(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        ok, error = validate_credentials("ddo_test")
        assert ok is False
        assert error is not None
