import json
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.firecrawl.firecrawl import (
    FirecrawlResumeConfig,
    firecrawl_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.firecrawl.settings import FIRECRAWL_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the firecrawl module.
FIRECRAWL_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.firecrawl.firecrawl.make_tracked_session"
)


def _response(selector: str, items: list[dict[str, Any]] | None, *, extra: dict[str, Any] | None = None) -> Response:
    body: dict[str, Any] = {selector: items if items is not None else []}
    if extra:
        body.update(extra)
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _status_response(status_code: int, *, reason: str = "", body: Any = None) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp.reason = reason
    resp.url = "https://api.firecrawl.dev/v2/team/activity"
    resp._content = json.dumps(body if body is not None else {}).encode()
    return resp


def _make_manager(resume_state: FirecrawlResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire_sequence(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Drive the session with an ordered list of responses; capture each request's params at send time.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
    request is prepared instead of inspecting it after the run.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        prepared = mock.MagicMock()
        prepared.url = request.url
        param_snapshots.append(dict(request.params or {}))
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _wire_by_url(session: mock.MagicMock, handler: Any) -> list[str]:
    """Drive the session by dispatching each prepared request's URL through ``handler`` (url -> Response)."""
    session.headers = {}
    requested: list[str] = []

    def _prepare(request: Any) -> mock.MagicMock:
        prepared = mock.MagicMock()
        prepared.url = request.url
        requested.append(request.url)
        return prepared

    def _send(prepared: Any, **_: Any) -> Response:
        return handler(prepared.url)

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = _send
    return requested


def _source(endpoint: str, manager: mock.MagicMock):
    return firecrawl_source(
        api_key="fc-test",
        endpoint=endpoint,
        team_id=1,
        job_id="job-1",
        resumable_source_manager=manager,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestCursorPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_cursor_until_cursor_empty(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire_sequence(
            session,
            [
                _response("data", [{"id": "a"}], extra={"cursor": "c1", "has_more": True}),
                _response("data", [{"id": "b"}], extra={"cursor": "c2", "has_more": True}),
                _response("data", [{"id": "c"}], extra={"cursor": None, "has_more": False}),
            ],
        )
        manager = _make_manager()

        rows = _rows(_source("team_activity", manager))

        assert [r["id"] for r in rows] == ["a", "b", "c"]
        # limit is sent on every page; the cursor is injected only from the second page on.
        assert params[0] == {"limit": 100}
        assert params[1]["cursor"] == "c1"
        assert params[2]["cursor"] == "c2"
        # Checkpoint is saved only while a next cursor remains, and it points at the NEXT page.
        saved = [c.args[0] for c in manager.save_state.call_args_list]
        assert [s.cursor for s in saved] == ["c1", "c2"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire_sequence(session, [_response("data", [{"id": "b"}], extra={"cursor": None, "has_more": False})])
        manager = _make_manager(FirecrawlResumeConfig(cursor="c1"))

        rows = _rows(_source("team_activity", manager))

        assert [r["id"] for r in rows] == ["b"]
        # The resumed cursor is applied to the very first request; the earlier page is never re-fetched.
        assert params[0]["cursor"] == "c1"
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_when_cursor_missing(self, MockSession) -> None:
        # No next cursor terminates the walk even though the body claims has_more=true.
        session = MockSession.return_value
        _wire_sequence(session, [_response("data", [{"id": "a"}], extra={"cursor": None, "has_more": True})])
        manager = _make_manager()

        rows = _rows(_source("team_activity", manager))

        assert [r["id"] for r in rows] == ["a"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()


class TestOffsetPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_pages_until_short_page(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"id": str(i)} for i in range(100)]
        params = _wire_sequence(session, [_response("data", full_page), _response("data", [{"id": "last"}])])
        manager = _make_manager()

        rows = _rows(_source("monitors", manager))

        assert len(rows) == 101
        assert params[0]["offset"] == 0
        assert params[0]["limit"] == 100
        assert params[1]["offset"] == 100
        # One checkpoint after the first full page (points at the next offset); the short page ends it.
        saved = [c.args[0] for c in manager.save_state.call_args_list]
        assert [s.offset for s in saved] == [100]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_short_page_makes_one_request_and_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire_sequence(session, [_response("data", [{"id": "x"}])])
        manager = _make_manager()

        rows = _rows(_source("monitors", manager))

        assert [r["id"] for r in rows] == ["x"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire_sequence(session, [_response("data", [{"id": "m_201"}])])
        manager = _make_manager(FirecrawlResumeConfig(offset=200))

        _rows(_source("monitors", manager))

        assert params[0]["offset"] == 200


class TestUnpaginated:
    @parameterized.expand(
        [
            ("credit_usage_historical", "periods"),
            ("token_usage_historical", "periods"),
            ("active_crawls", "crawls"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_request_reads_the_endpoint_selector(self, endpoint: str, selector: str, MockSession) -> None:
        session = MockSession.return_value
        _wire_sequence(session, [_response(selector, [{"id": "1"}, {"id": "2"}])])
        manager = _make_manager()

        rows = _rows(_source(endpoint, manager))

        assert rows == [{"id": "1"}, {"id": "2"}]
        assert session.send.call_count == 1  # unpaginated: exactly one request

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_selector_raises_loudly(self, MockSession) -> None:
        # A 200 body without the expected selector means the response shape changed — fail loud rather
        # than silently replacing warehouse data with zero rows on a full refresh.
        session = MockSession.return_value
        _wire_sequence(session, [_response("something_else", [{"id": "1"}])])
        manager = _make_manager()

        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_source("active_crawls", manager))


class TestMonitorChecksFanOut:
    def test_config_is_opt_in_fan_out(self) -> None:
        cfg = FIRECRAWL_ENDPOINTS["monitor_checks"]
        assert cfg.fan_out_over_monitors is True
        assert cfg.should_sync_default is False
        assert "{monitor_id}" in cfg.path

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fans_out_over_every_monitor(self, MockSession) -> None:
        session = MockSession.return_value

        def handler(url: str) -> Response:
            if url.endswith("/v2/monitor"):
                return _response("data", [{"id": "m1"}, {"id": "m2"}])
            if "/v2/monitor/m1/checks" in url:
                return _response("data", [{"id": "chk1", "monitorId": "m1"}])
            if "/v2/monitor/m2/checks" in url:
                return _response("data", [{"id": "chk2", "monitorId": "m2"}])
            raise AssertionError(f"unexpected url {url}")

        _wire_by_url(session, handler)
        manager = _make_manager()

        rows = _rows(_source("monitor_checks", manager))

        # Each check row is yielded as the API returns it (it already carries monitorId), in monitor order.
        assert rows == [
            {"id": "chk1", "monitorId": "m1"},
            {"id": "chk2", "monitorId": "m2"},
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_past_completed_monitor(self, MockSession) -> None:
        session = MockSession.return_value

        def handler(url: str) -> Response:
            if url.endswith("/v2/monitor"):
                return _response("data", [{"id": "m1"}, {"id": "m2"}])
            if "/v2/monitor/m2/checks" in url:
                return _response("data", [{"id": "chk2", "monitorId": "m2"}])
            raise AssertionError(f"unexpected url {url}")

        requested = _wire_by_url(session, handler)
        # m1's checks are already checkpointed as complete, so the resume skips straight to m2.
        manager = _make_manager(
            FirecrawlResumeConfig(fanout_state={"completed": ["/v2/monitor/m1/checks"], "current": None})
        )

        rows = _rows(_source("monitor_checks", manager))

        assert rows == [{"id": "chk2", "monitorId": "m2"}]
        assert not any("/v2/monitor/m1/checks" in url for url in requested)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stale_completed_path_does_not_skip_live_monitor(self, MockSession) -> None:
        session = MockSession.return_value

        def handler(url: str) -> Response:
            if url.endswith("/v2/monitor"):
                return _response("data", [{"id": "m1"}])
            if "/v2/monitor/m1/checks" in url:
                return _response("data", [{"id": "chk1", "monitorId": "m1"}])
            raise AssertionError(f"unexpected url {url}")

        _wire_by_url(session, handler)
        # A checkpoint for a monitor that no longer exists must not suppress the live monitor.
        manager = _make_manager(
            FirecrawlResumeConfig(fanout_state={"completed": ["/v2/monitor/DELETED/checks"], "current": None})
        )

        rows = _rows(_source("monitor_checks", manager))

        assert rows == [{"id": "chk1", "monitorId": "m1"}]


class TestRetryClassification:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 502)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_retry_then_succeed(self, _name: str, status_code: int, MockSession) -> None:
        # 429 (plan rate/concurrency limit) and 5xx must retry rather than fail the sync outright.
        session = MockSession.return_value
        session.headers = {}
        session.prepare_request.side_effect = lambda request: mock.MagicMock(url=request.url)
        session.send.side_effect = [_status_response(status_code), _response("data", [{"id": "a"}])]
        manager = _make_manager()

        with mock.patch.object(RESTClient._send_request.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            rows = _rows(_source("team_activity", manager))

        assert [r["id"] for r in rows] == ["a"]
        assert session.send.call_count == 2

    @parameterized.expand([("unauthorized", 401, "Unauthorized"), ("forbidden", 403, "Forbidden")])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_surface_immediately(self, _name: str, status_code: int, reason: str, MockSession) -> None:
        # A 4xx credential/permission error can never be fixed by retrying, so it must surface at once
        # (and carries the status text get_non_retryable_errors matches on).
        session = MockSession.return_value
        session.headers = {}
        session.prepare_request.side_effect = lambda request: mock.MagicMock(url=request.url)
        session.send.side_effect = [_status_response(status_code, reason=reason)]
        manager = _make_manager()

        with pytest.raises(requests.HTTPError):
            _rows(_source("team_activity", manager))
        assert session.send.call_count == 1


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("server_error", 500, False)])
    @mock.patch(FIRECRAWL_SESSION_PATCH)
    def test_status_maps_to_bool(self, _name: str, status_code: int, expected: bool, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("fc-test") is expected

    @mock.patch(FIRECRAWL_SESSION_PATCH)
    def test_network_failure_is_false(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        assert validate_credentials("fc-test") is False


class TestSourceResponseShape:
    @parameterized.expand(
        [
            ("team_activity", ["id"], "created_at", "week"),
            ("credit_usage_historical", ["startDate"], None, None),
            ("token_usage_historical", ["startDate"], None, None),
            ("active_crawls", ["id"], None, None),
            ("monitors", ["id"], "createdAt", "week"),
            ("monitor_checks", ["id"], "createdAt", "week"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_primary_keys_and_partitioning(
        self,
        endpoint: str,
        expected_pk: list[str],
        partition_key: str | None,
        partition_format: str | None,
        MockSession,
    ) -> None:
        # Locks the primary key + a STABLE (creation-time) partition field per endpoint. A non-unique
        # key or an updated_at partition would rewrite partitions every sync and accumulate duplicates.
        response = _source(endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == expected_pk
        assert response.sort_mode == "asc"
        if partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
            assert response.partition_format == partition_format
