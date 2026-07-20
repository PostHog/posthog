from datetime import UTC, date, datetime
from typing import Any, cast
from urllib.parse import parse_qsl, urlsplit

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.deno_deploy import deno_deploy
from products.warehouse_sources.backend.temporal.data_imports.sources.deno_deploy.deno_deploy import (
    DENO_DEPLOY_ENDPOINTS,
    DenoDeployResumeConfig,
    _format_rfc3339,
    _initial_child_url,
    _log_row_id,
    _logs_next_url,
    _parse_next_link,
    _require_deno_deploy_url,
    _reshape_analytics,
    _shape_log,
    _time_window_params,
    deno_deploy_source,
    get_rows,
    validate_credentials,
)


class FakeResponse:
    def __init__(
        self,
        json_data: Any,
        headers: dict[str, str] | None = None,
        status_code: int = 200,
        url: str = "https://api.deno.com/v2/apps",
    ) -> None:
        self._json = json_data
        self.headers = headers or {}
        self.status_code = status_code
        self.ok = status_code < 400
        self.url = url
        self.text = "" if json_data is None else str(json_data)

    def json(self) -> Any:
        return self._json

    def raise_for_status(self) -> None:
        if not self.ok:
            raise requests.HTTPError(f"{self.status_code} Client Error", response=cast(requests.Response, self))


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)
        self.urls: list[str] = []

    def get(self, url: str, headers: dict[str, str] | None = None, timeout: int | None = None) -> FakeResponse:
        self.urls.append(url)
        return self._responses.pop(0)


class FakeManager:
    """Stand-in for ResumableSourceManager that records saved state and can seed a resume state."""

    def __init__(self, state: DenoDeployResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[DenoDeployResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> DenoDeployResumeConfig | None:
        return self._state

    def save_state(self, state: DenoDeployResumeConfig) -> None:
        self.saved.append(state)


def _run(endpoint: str, session: FakeSession, manager: FakeManager, **kwargs: Any) -> list[dict[str, Any]]:
    with patch.object(deno_deploy, "make_tracked_session", return_value=session):
        rows: list[dict[str, Any]] = []
        for batch in get_rows(
            access_token="ddo_test",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            **kwargs,
        ):
            rows.extend(batch)
        return rows


class TestParseNextLink:
    @parameterized.expand(
        [
            (
                "absolute",
                '<https://api.deno.com/v2/apps?cursor=abc&limit=30>; rel="next"',
                "https://api.deno.com/v2/apps?cursor=abc&limit=30",
            ),
            ("relative", '</v2/apps?cursor=abc>; rel="next"', "https://api.deno.com/v2/apps?cursor=abc"),
            ("empty", "", None),
            ("no_next_rel", '<https://api.deno.com/v2/apps?cursor=abc>; rel="prev"', None),
        ]
    )
    def test_parse_next_link(self, _name: str, header: str, expected: str | None) -> None:
        assert _parse_next_link(header) == expected


class TestFormatRfc3339:
    @parameterized.expand(
        [
            ("utc", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_treated_as_utc", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format(self, _name: str, value: datetime, expected: str) -> None:
        result = _format_rfc3339(value)
        assert result == expected
        assert "+00:00" not in result


class TestLogRowId:
    def test_stable_and_content_addressed(self) -> None:
        log = {"timestamp": "2026-01-01T00:00:00Z", "level": "info", "message": "hi", "trace_id": "t1"}
        first = _log_row_id("app-1", log)
        # Same content -> same id (idempotent merge on re-pull of the boundary window).
        assert first == _log_row_id("app-1", dict(log))
        # Different app or content -> different id.
        assert first != _log_row_id("app-2", log)
        assert first != _log_row_id("app-1", {**log, "message": "bye"})


class TestReshapeAnalytics:
    def test_columnar_to_rows(self) -> None:
        body = {
            "fields": [{"name": "time", "type": "time"}, {"name": "request_count", "type": "number"}],
            "values": [["2026-01-01T00:00:00Z", 5], ["2026-01-01T00:15:00Z", 9]],
        }
        rows = _reshape_analytics(body, "app-1", "my-app")
        assert rows == [
            {"time": "2026-01-01T00:00:00Z", "request_count": 5, "app_id": "app-1", "app_slug": "my-app"},
            {"time": "2026-01-01T00:15:00Z", "request_count": 9, "app_id": "app-1", "app_slug": "my-app"},
        ]

    def test_empty_values(self) -> None:
        assert _reshape_analytics({"fields": [{"name": "time", "type": "time"}], "values": []}, "a", "s") == []


class TestShapeLog:
    def test_injects_context_and_id(self) -> None:
        row = _shape_log({"timestamp": "2026-01-01T00:00:00Z", "message": "hi"}, "app-1", "my-app")
        assert row["app_id"] == "app-1"
        assert row["app_slug"] == "my-app"
        assert row["message"] == "hi"
        assert isinstance(row["id"], str) and len(row["id"]) == 64  # sha256 hexdigest


class TestTimeWindowParams:
    @freeze_time("2026-06-01T12:00:00Z")
    def test_first_sync_uses_lookback(self) -> None:
        # No watermark -> start = now - default_lookback_days (7 for logs).
        start, end = _time_window_params(
            DENO_DEPLOY_ENDPOINTS["logs"], should_use_incremental_field=True, db_incremental_field_last_value=None
        )
        assert end == "2026-06-01T12:00:00Z"
        assert start == "2026-05-25T12:00:00Z"

    @freeze_time("2026-06-01T12:00:00Z")
    def test_incremental_subtracts_lookback(self) -> None:
        # Watermark present -> start = watermark - incremental_lookback (5 min for logs).
        start, _ = _time_window_params(
            DENO_DEPLOY_ENDPOINTS["logs"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC),
        )
        assert start == "2026-06-01T09:55:00Z"

    @freeze_time("2026-06-01T12:00:00Z")
    def test_future_watermark_clamped_to_now(self) -> None:
        # A future-dated watermark can't push start past now.
        start, end = _time_window_params(
            DENO_DEPLOY_ENDPOINTS["analytics"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2027, 1, 1, tzinfo=UTC),
        )
        # start = min(future, now) - 30min lookback = now - 30min
        assert start == "2026-06-01T11:30:00Z"
        assert end == "2026-06-01T12:00:00Z"


class TestInitialChildUrl:
    @freeze_time("2026-06-01T12:00:00Z")
    def test_logs_url_has_bounded_window(self) -> None:
        url = _initial_child_url(DENO_DEPLOY_ENDPOINTS["logs"], "app-1", True, None)
        assert url.startswith("https://api.deno.com/v2/apps/app-1/logs?")
        # end must always be present (omitting it switches the endpoint to real-time streaming).
        assert "start=" in url and "end=" in url and "limit=1000" in url

    @freeze_time("2026-06-01T12:00:00Z")
    def test_analytics_url_uses_since_until(self) -> None:
        url = _initial_child_url(DENO_DEPLOY_ENDPOINTS["analytics"], "app-1", True, None)
        assert "since=" in url and "until=" in url

    def test_revisions_url_uses_limit(self) -> None:
        url = _initial_child_url(DENO_DEPLOY_ENDPOINTS["revisions"], "app-1", False, None)
        assert url == "https://api.deno.com/v2/apps/app-1/revisions?limit=100"


class TestLogsNextUrl:
    def test_swaps_cursor_preserving_window(self) -> None:
        current = "https://api.deno.com/v2/apps/app-1/logs?start=2026-01-01T00%3A00%3A00Z&end=2026-01-02T00%3A00%3A00Z&limit=1000&cursor=old"
        nxt = _logs_next_url(current, "new")
        assert "cursor=new" in nxt
        assert "cursor=old" not in nxt
        assert "start=" in nxt and "end=" in nxt and "limit=1000" in nxt
        # The already-encoded start/end must be encoded exactly once, not doubled (`%253A`); parsing the
        # rebuilt URL must recover the original timestamps.
        assert "%253A" not in nxt
        params = dict(parse_qsl(urlsplit(nxt).query))
        assert params["start"] == "2026-01-01T00:00:00Z"
        assert params["end"] == "2026-01-02T00:00:00Z"


class TestRequireDenoDeployUrl:
    @parameterized.expand(
        [
            ("https_apex", "https://api.deno.com/v2/apps?limit=1", True),
            ("http_scheme_rejected", "http://api.deno.com/v2/apps", False),
            ("other_host_rejected", "https://evil.example.com/v2/apps", False),
            ("subdomain_rejected", "https://api.deno.com.evil.com/v2/apps", False),
            ("host_as_userinfo_rejected", "https://api.deno.com@evil.com/v2/apps", False),
        ]
    )
    def test_only_https_deno_host_allowed(self, _name: str, url: str, allowed: bool) -> None:
        if allowed:
            assert _require_deno_deploy_url(url) == url
        else:
            with pytest.raises(ValueError):
                _require_deno_deploy_url(url)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_ok: bool) -> None:
        session = MagicMock()
        session.get.return_value = FakeResponse({"message": "x"}, status_code=status)
        with patch.object(deno_deploy, "make_tracked_session", return_value=session):
            ok, error = validate_credentials("ddo_test")
        assert ok is expected_ok
        assert (error is None) is expected_ok

    def test_network_error(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(deno_deploy, "make_tracked_session", return_value=session):
            ok, error = validate_credentials("ddo_test")
        assert ok is False
        assert error is not None


class TestListEndpointPagination:
    def test_apps_follows_link_header_and_checkpoints(self) -> None:
        session = FakeSession(
            [
                FakeResponse(
                    [{"id": "a1", "slug": "one"}],
                    headers={"Link": '<https://api.deno.com/v2/apps?cursor=p2&limit=100>; rel="next"'},
                ),
                FakeResponse([{"id": "a2", "slug": "two"}], headers={}),
            ]
        )
        manager = FakeManager()
        rows = _run("apps", session, manager)
        assert [r["id"] for r in rows] == ["a1", "a2"]
        # Saved state points at the not-yet-yielded next page (checkpoint after yielding page one).
        assert manager.saved == [DenoDeployResumeConfig(next_url="https://api.deno.com/v2/apps?cursor=p2&limit=100")]

    def test_apps_resumes_from_saved_url(self) -> None:
        session = FakeSession([FakeResponse([{"id": "a2", "slug": "two"}], headers={})])
        manager = FakeManager(state=DenoDeployResumeConfig(next_url="https://api.deno.com/v2/apps?cursor=p2"))
        rows = _run("apps", session, manager)
        assert [r["id"] for r in rows] == ["a2"]
        # It resumed from the saved URL rather than the default first page.
        assert session.urls[0] == "https://api.deno.com/v2/apps?cursor=p2"


class TestFanOut:
    def test_revisions_inject_parent_app_context(self) -> None:
        session = FakeSession(
            [
                FakeResponse([{"id": "a1", "slug": "one"}, {"id": "a2", "slug": "two"}], headers={}),  # /v2/apps
                FakeResponse([{"id": "r1", "status": "success"}], headers={}),  # a1 revisions
                FakeResponse([{"id": "r2", "status": "failed"}], headers={}),  # a2 revisions
            ]
        )
        rows = _run("revisions", session, FakeManager())
        assert rows == [
            {"id": "r1", "status": "success", "app_id": "a1", "app_slug": "one"},
            {"id": "r2", "status": "failed", "app_id": "a2", "app_slug": "two"},
        ]

    @freeze_time("2026-06-01T12:00:00Z")
    def test_logs_paginate_via_next_cursor(self) -> None:
        session = FakeSession(
            [
                FakeResponse([{"id": "a1", "slug": "one"}], headers={}),  # /v2/apps
                FakeResponse(
                    {"logs": [{"timestamp": "2026-06-01T10:00:00Z", "message": "m1"}], "next_cursor": "c2"},
                    url="https://api.deno.com/v2/apps/a1/logs?start=x&end=y&limit=1000",
                ),
                FakeResponse(
                    {"logs": [{"timestamp": "2026-06-01T11:00:00Z", "message": "m2"}], "next_cursor": None},
                    url="https://api.deno.com/v2/apps/a1/logs?start=x&end=y&limit=1000&cursor=c2",
                ),
            ]
        )
        manager = FakeManager()
        rows = _run("logs", session, manager, should_use_incremental_field=True, db_incremental_field_last_value=None)
        assert [r["message"] for r in rows] == ["m1", "m2"]
        assert all("id" in r and r["app_id"] == "a1" for r in rows)
        # Second logs fetch followed the body cursor.
        assert "cursor=c2" in session.urls[-1]
        # Checkpoint carried the app id for mid-fan-out resume.
        assert manager.saved[0].app_id == "a1"

    def test_fanout_resumes_from_saved_app(self) -> None:
        session = FakeSession(
            [
                FakeResponse([{"id": "a1", "slug": "one"}, {"id": "a2", "slug": "two"}], headers={}),  # /v2/apps
                FakeResponse([{"id": "r2", "status": "success"}], headers={}),  # a2 revisions only
            ]
        )
        manager = FakeManager(state=DenoDeployResumeConfig(next_url=None, app_id="a2"))
        rows = _run("revisions", session, manager)
        # a1 skipped: resume started at a2.
        assert [r["id"] for r in rows] == ["r2"]
        assert rows[0]["app_id"] == "a2"


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
        response = deno_deploy_source(
            access_token="ddo_test",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=None,
        )
        assert response.name == endpoint
        assert response.primary_keys == pk
        assert response.partition_keys == [partition]
        assert response.partition_mode == "datetime"
        assert response.sort_mode == "asc"

    @parameterized.expand([("date", date(2026, 1, 1)), ("string", "cursor")])
    def test_format_rfc3339_non_datetime_paths(self, _name: str, value: Any) -> None:
        # _time_window_params only calls _format_rfc3339 on datetimes it resolves, so exercise the
        # _as_utc_datetime coercion directly to lock in date handling.
        from products.warehouse_sources.backend.temporal.data_imports.sources.deno_deploy.deno_deploy import (
            _as_utc_datetime,
        )

        result = _as_utc_datetime(value)
        if isinstance(value, date):
            assert result is not None and result.tzinfo is UTC
        else:
            assert result is None
