import json
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.mux import mux
from products.warehouse_sources.backend.temporal.data_imports.sources.mux.mux import (
    MuxResumeConfig,
    _normalize_row,
    _strip_sensitive_fields,
    get_validation_status,
    mux_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mux.settings import MUX_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# tenacity sleeps between retries — patch its clock so retry paths don't actually block.
TENACITY_SLEEP_PATCH = "tenacity.nap.time.sleep"


def _response(body: dict[str, Any] | None, status: int = 200, *, reason: str = "OK") -> Response:
    resp = Response()
    resp.status_code = status
    resp.reason = reason
    resp.url = "https://api.mux.com/video/v1/list"
    resp._content = json.dumps(body if body is not None else {}).encode()
    return resp


def _make_manager(resume_state: MuxResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _run(endpoint: str, manager: mock.MagicMock) -> list[dict[str, Any]]:
    response = mux_source(
        access_token_id="id",
        secret_key="secret",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )
    return [row for page in response.items() for row in page]


class TestNormalizeRow:
    @parameterized.expand(
        [
            ("digit_string_to_int", "assets", {"id": "a", "created_at": "1609869152"}, 1609869152),
            ("already_int_unchanged", "assets", {"id": "a", "created_at": 1609869152}, 1609869152),
            ("non_digit_string_unchanged", "assets", {"id": "a", "created_at": "not-a-ts"}, "not-a-ts"),
        ]
    )
    def test_created_at_coercion(self, _name: str, endpoint: str, item: dict, expected: Any) -> None:
        result = _normalize_row(item, MUX_ENDPOINTS[endpoint])
        assert result["created_at"] == expected

    def test_endpoint_without_partition_key_is_untouched(self) -> None:
        # Uploads have no created_at partition key, so the row passes through verbatim.
        item = {"id": "u1", "status": "waiting"}
        assert _normalize_row(item, MUX_ENDPOINTS["uploads"]) == item

    def test_missing_created_at_is_untouched(self) -> None:
        item = {"id": "a1"}
        assert _normalize_row(item, MUX_ENDPOINTS["assets"]) == item


class TestStripSensitiveFields:
    def test_live_stream_stream_key_is_dropped(self) -> None:
        item = {"id": "ls1", "created_at": "1", "stream_key": "super-secret", "status": "idle"}
        cleaned = _strip_sensitive_fields(item, MUX_ENDPOINTS["live_streams"])
        assert "stream_key" not in cleaned
        assert cleaned == {"id": "ls1", "created_at": "1", "status": "idle"}

    def test_live_stream_simulcast_target_stream_keys_are_dropped(self) -> None:
        item = {
            "id": "ls1",
            "simulcast_targets": [
                {"id": "t1", "url": "rtmp://example", "stream_key": "secret", "status": "idle"},
            ],
        }
        cleaned = _strip_sensitive_fields(item, MUX_ENDPOINTS["live_streams"])
        assert cleaned["simulcast_targets"] == [{"id": "t1", "url": "rtmp://example", "status": "idle"}]

    def test_upload_url_is_dropped(self) -> None:
        item = {"id": "u1", "url": "https://storage.googleapis.com/upload?signature=secret", "status": "waiting"}
        cleaned = _strip_sensitive_fields(item, MUX_ENDPOINTS["uploads"])
        assert "url" not in cleaned
        assert cleaned == {"id": "u1", "status": "waiting"}

    def test_endpoint_without_sensitive_fields_is_untouched(self) -> None:
        item = {"id": "a1", "status": "ready"}
        assert _strip_sensitive_fields(item, MUX_ENDPOINTS["assets"]) is item

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_never_yields_stripped_fields(self, MockSession) -> None:
        # End-to-end guard: a secret in the API response must not survive into batched rows, and
        # created_at is still coerced to int.
        session = MockSession.return_value
        _wire(session, [_response({"data": [{"id": "ls1", "created_at": "1609869152", "stream_key": "leak"}]})])

        rows = _run("live_streams", _make_manager())
        assert rows == [{"id": "ls1", "created_at": 1609869152}]
        assert all("stream_key" not in row for row in rows)


class TestGetValidationStatus:
    def test_returns_status_code(self, monkeypatch: Any) -> None:
        for status_code in (200, 401, 403):
            session = mock.MagicMock()
            session.get.return_value = mock.MagicMock(status_code=status_code)
            monkeypatch.setattr(mux, "_make_session", lambda *a, _s=session, **k: _s)
            assert get_validation_status("id", "secret", "/video/v1/assets") == status_code

    def test_transport_error_returns_none(self, monkeypatch: Any) -> None:
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        monkeypatch.setattr(mux, "_make_session", lambda *a, **k: session)
        assert get_validation_status("id", "secret", "/video/v1/assets") is None


class TestOffsetPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_walks_pages_until_short_page(self, MockSession) -> None:
        # live_streams uses page pagination with page_size 100; a page shorter than the limit ends it.
        session = MockSession.return_value
        full_page = [{"id": str(i), "created_at": "1609869152"} for i in range(100)]
        params = _wire(
            session, [_response({"data": full_page}), _response({"data": [{"id": "100", "created_at": "1609869152"}]})]
        )

        manager = _make_manager()
        rows = _run("live_streams", manager)

        assert len(rows) == 101
        assert params[0]["limit"] == 100
        assert params[0]["page"] == 1
        assert params[1]["page"] == 2
        assert session.send.call_count == 2
        # created_at coerced to int for partitioning.
        assert rows[0]["created_at"] == 1609869152
        # Checkpoint saved after the first full page (points at the next page); short page ends it.
        manager.save_state.assert_called_once_with(MuxResumeConfig(page=2))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"data": []})])

        manager = _make_manager()
        rows = _run("live_streams", manager)

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_final_page_triggers_one_more_empty_fetch(self, MockSession) -> None:
        # An exact-multiple final page can't be distinguished from a full page, so we fetch once more.
        session = MockSession.return_value
        full_page = [{"id": str(i), "created_at": "1609869152"} for i in range(100)]
        _wire(session, [_response({"data": full_page}), _response({"data": []})])

        manager = _make_manager()
        rows = _run("live_streams", manager)

        assert len(rows) == 100
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response({"data": [{"id": "x", "created_at": "1609869152"}]})])

        manager = _make_manager(MuxResumeConfig(page=3))
        rows = _run("live_streams", manager)

        assert rows == [{"id": "x", "created_at": 1609869152}]
        assert params[0]["page"] == 3
        assert session.send.call_count == 1


class TestCursorPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_assets_walk_via_next_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response({"data": [{"id": "a1", "created_at": "1609869152"}], "next_cursor": "CURSOR2"}),
                _response({"data": [{"id": "a2", "created_at": "1609869152"}], "next_cursor": None}),
            ],
        )

        manager = _make_manager()
        rows = _run("assets", manager)

        assert [r["id"] for r in rows] == ["a1", "a2"]
        assert "cursor" not in params[0]
        assert params[1]["cursor"] == "CURSOR2"
        manager.save_state.assert_called_once_with(MuxResumeConfig(cursor="CURSOR2"))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_assets_stop_when_next_cursor_null(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"data": [{"id": "a1", "created_at": "1609869152"}], "next_cursor": None})])

        manager = _make_manager()
        rows = _run("assets", manager)

        assert [r["id"] for r in rows] == ["a1"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_assets_resume_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response({"data": [{"id": "a9", "created_at": "1609869152"}], "next_cursor": None})])

        manager = _make_manager(MuxResumeConfig(cursor="SAVED"))
        rows = _run("assets", manager)

        assert [r["id"] for r in rows] == ["a9"]
        assert params[0]["cursor"] == "SAVED"


class TestRetryableErrors:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 502)])
    @mock.patch(TENACITY_SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_is_retried_then_succeeds(self, _name: str, status_code: int, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(None, status=status_code, reason="err"),
                _response({"data": [{"id": "ok", "created_at": "1609869152"}]}),
            ],
        )

        rows = _run("live_streams", _make_manager())

        assert [r["id"] for r in rows] == ["ok"]
        assert session.send.call_count == 2

    @mock.patch(TENACITY_SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_eventually_raises(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        session.headers = {}
        session.prepare_request.side_effect = lambda request: mock.MagicMock()
        session.send.return_value = _response(None, status=500, reason="err")

        with pytest.raises(Exception):
            _run("live_streams", _make_manager())
        # Default of 5 attempts, no early success.
        assert session.send.call_count == 5

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_raises_without_retry(self, MockSession) -> None:
        # A 403 (missing scope) is a permanent client error — raised on the first response, not retried.
        session = MockSession.return_value
        _wire(session, [_response(None, status=403, reason="Forbidden")])

        with pytest.raises(requests.HTTPError):
            _run("live_streams", _make_manager())
        assert session.send.call_count == 1


class TestMuxSourceResponse:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_partitioned_endpoint_sets_datetime_partitioning(self, _MockSession) -> None:
        response = mux_source("id", "secret", "assets", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        assert response.name == "assets"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]
        assert response.partition_format == "month"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unpartitioned_endpoint_has_no_partitioning(self, _MockSession) -> None:
        response = mux_source(
            "id", "secret", "uploads", team_id=1, job_id="j", resumable_source_manager=_make_manager()
        )
        assert response.name == "uploads"
        assert response.partition_mode is None
        assert response.partition_keys is None
