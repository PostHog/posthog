import json
import threading
from typing import Any, Optional, cast

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.fusionauth import fusionauth as fusionauth_module
from products.warehouse_sources.backend.temporal.data_imports.sources.fusionauth.fusionauth import (
    HTTP_NOT_ALLOWED_ERROR,
    FusionAuthOffsetPaginator,
    FusionAuthResponseTimeoutError,
    FusionAuthResponseTooLargeError,
    FusionAuthResumeConfig,
    _build_search_body,
    _read_bounded,
    fusionauth_source,
    normalize_base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fusionauth.settings import FUSIONAUTH_ENDPOINTS

# The sync path runs through a bounded session built by `_make_bounded_session`; patch that so the
# pagination tests can drive `session.send` directly (RESTClient uses the session it's handed).
CLIENT_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.fusionauth.fusionauth._make_bounded_session"
)


def _response(body: dict[str, Any], *, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _redirect_response(status_code: int = 302, location: str = "https://internal.example/") -> Response:
    resp = Response()
    resp.status_code = status_code
    resp.headers["Location"] = location
    resp._content = b""
    return resp


def _make_manager(resume_state: Optional[FusionAuthResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's url + json body AT PREPARE TIME.

    ``request.json`` is a single dict mutated in place across pages, so snapshot a deep copy
    when each request is prepared rather than inspecting the shared dict after the run.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "json": json.loads(json.dumps(request.json or {}))})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestNormalizeBaseUrl:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("auth.example.com", "https://auth.example.com"),
            ("https://auth.example.com", "https://auth.example.com"),
            ("https://auth.example.com/", "https://auth.example.com"),
            ("http://auth.example.com/", "http://auth.example.com"),
            ("  auth.example.com  ", "https://auth.example.com"),
            ("https://auth.example.com/api", "https://auth.example.com"),
        ],
    )
    def test_normalize(self, raw, expected):
        assert normalize_base_url(raw) == expected


class TestBuildSearchBody:
    def test_users_has_query_string_and_sort_fields(self):
        body = _build_search_body(FUSIONAUTH_ENDPOINTS["Users"], {})
        assert body["search"]["queryString"] == "*"
        assert body["search"]["sortFields"] == [{"name": "insertInstant", "order": "asc"}]

    @pytest.mark.parametrize("endpoint", ["AuditLogs", "EventLogs"])
    def test_ascending_endpoints_request_explicit_order(self, endpoint):
        body = _build_search_body(FUSIONAUTH_ENDPOINTS[endpoint], {})
        assert body["search"]["orderBy"] == "insertInstant ASC"

    def test_login_records_has_no_order_by(self):
        # LoginRecords documents no orderBy field, so it must never be sent.
        body = _build_search_body(FUSIONAUTH_ENDPOINTS["LoginRecords"], {})
        assert "orderBy" not in body["search"]

    def test_search_extra_merges_in(self):
        body = _build_search_body(FUSIONAUTH_ENDPOINTS["AuditLogs"], {"start": 123})
        assert body["search"]["start"] == 123


class TestFusionAuthOffsetPaginator:
    def _request(self):
        return mock.MagicMock(json=None)

    def test_init_sets_first_page(self):
        paginator = FusionAuthOffsetPaginator(limit=100)
        request = self._request()
        paginator.init_request(request)
        assert request.json == {"search": {"startRow": 0, "numberOfResults": 100}}

    def test_full_page_advances_offset(self):
        paginator = FusionAuthOffsetPaginator(limit=2)
        response = _response({"total": 10})
        paginator.update_state(response, data=[{"id": 1}, {"id": 2}])
        assert paginator.has_next_page is True
        assert paginator.offset == 2

    def test_undersized_page_terminates(self):
        paginator = FusionAuthOffsetPaginator(limit=100)
        response = _response({})
        paginator.update_state(response, data=[{"id": 1}])
        assert paginator.has_next_page is False

    def test_empty_page_terminates(self):
        paginator = FusionAuthOffsetPaginator(limit=100)
        response = _response({})
        paginator.update_state(response, data=[])
        assert paginator.has_next_page is False

    def test_maximum_offset_terminates(self):
        paginator = FusionAuthOffsetPaginator(limit=100, offset=9800, maximum_offset=9900)
        response = _response({})
        paginator.update_state(response, data=[{"id": i} for i in range(100)])
        assert paginator.has_next_page is False

    def test_resume_state_roundtrip(self):
        paginator = FusionAuthOffsetPaginator(limit=100)
        paginator.offset = 300
        state = paginator.get_resume_state()
        assert state == {"offset": 300}

        resumed = FusionAuthOffsetPaginator(limit=100)
        resumed.set_resume_state(state)
        assert resumed.offset == 300
        assert resumed.has_next_page is True

    def test_no_resume_state_when_exhausted(self):
        paginator = FusionAuthOffsetPaginator(limit=100)
        paginator._has_next_page = False
        assert paginator.get_resume_state() is None


class TestValidateCredentials:
    def _patch_session(self, response=None, raises=None):
        session = mock.MagicMock()
        if raises is not None:
            session.get.side_effect = raises
        else:
            session.get.return_value = response
        return mock.patch.object(fusionauth_module, "_make_bounded_session", return_value=session)

    def _resp(self, *, status_code=200, json_data=None, text=""):
        response = mock.MagicMock()
        response.status_code = status_code
        response.is_redirect = status_code in (301, 302, 303, 307, 308)
        response.is_permanent_redirect = status_code in (301, 308)
        response.text = text
        response.json.return_value = json_data
        return response

    def test_success(self):
        with self._patch_session(self._resp(status_code=200)):
            assert validate_credentials("https://auth.example.com", "tok") == (True, None)

    def test_invalid_key(self):
        with self._patch_session(self._resp(status_code=401)):
            valid, msg = validate_credentials("https://auth.example.com", "tok")
            assert valid is False
            assert msg == "Invalid FusionAuth API key"

    def test_error_body_surfaces_message(self):
        with self._patch_session(
            self._resp(status_code=500, json_data={"generalErrors": [{"message": "internal error"}]})
        ):
            valid, msg = validate_credentials("https://auth.example.com", "tok")
            assert valid is False
            assert msg == "internal error"

    def test_request_exception_returns_failure(self):
        import requests

        with self._patch_session(raises=requests.exceptions.ConnectionError("boom")):
            valid, msg = validate_credentials("https://auth.example.com", "tok")
            assert valid is False
            assert "boom" in (msg or "")

    def test_rejects_redirect_response(self):
        # A validated host that 3xx-redirects (potentially to an internal address) must be
        # rejected, not followed (SSRF).
        with self._patch_session(self._resp(status_code=302)) as patched:
            valid, msg = validate_credentials("https://auth.example.com", "tok")
            assert valid is False
            assert msg == fusionauth_module.HOST_NOT_ALLOWED_ERROR
            assert patched.return_value.get.call_args.kwargs["allow_redirects"] is False

    def test_blocks_unsafe_host(self):
        # When a team_id is supplied, a host that resolves to an internal address is rejected
        # before any HTTP request is made (SSRF guard).
        with (
            mock.patch.object(fusionauth_module, "_is_host_safe", return_value=(False, "internal address")),
            self._patch_session(self._resp(status_code=200)) as patched,
        ):
            valid, msg = validate_credentials("https://10.0.0.1", "tok", team_id=99)
            assert valid is False
            assert msg == "internal address"
            patched.return_value.get.assert_not_called()

    @pytest.mark.parametrize("bad_url", ["", "   "])
    def test_invalid_url_short_circuits(self, bad_url):
        valid, msg = validate_credentials(bad_url, "tok")
        assert valid is False
        assert msg == "Invalid FusionAuth base URL"

    def test_rejects_plaintext_http_before_sending_key(self):
        # An explicit http:// URL would send the API key in plaintext; reject it before any request.
        with self._patch_session(self._resp(status_code=200)) as patched:
            valid, msg = validate_credentials("http://auth.example.com", "tok")
            assert valid is False
            assert msg == HTTP_NOT_ALLOWED_ERROR
            patched.return_value.get.assert_not_called()

    def test_oversized_or_stalled_body_surfaces_as_failure(self):
        # A controlled host that ships an unbounded/stalled body must fail validation, not hang.
        with self._patch_session(raises=FusionAuthResponseTooLargeError("too big")):
            valid, msg = validate_credentials("https://auth.example.com", "tok")
            assert valid is False
            assert "too big" in (msg or "")


class TestFusionAuthSourceResponse:
    @pytest.mark.parametrize(
        "endpoint, primary_keys, sort_mode, partition_key",
        [
            ("Users", ["id"], "asc", "insertInstant"),
            ("AuditLogs", ["id"], "asc", "insertInstant"),
            ("EventLogs", ["id"], "asc", "insertInstant"),
            ("LoginRecords", ["userId", "applicationId", "instant"], "desc", "instant"),
        ],
    )
    def test_response_shape(self, endpoint, primary_keys, sort_mode, partition_key):
        response = fusionauth_source(
            base_url="https://auth.example.com",
            api_key="tok",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
        )
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == sort_mode
        assert response.partition_keys == [partition_key]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "week"


class TestFusionAuthAscendingPagination:
    def _source(self, endpoint="AuditLogs", manager=None, base_url="https://auth.example.com", **kwargs):
        return fusionauth_source(
            base_url=base_url,
            api_key="tok",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=manager if manager is not None else _make_manager(),
            **kwargs,
        )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_undersized_page(self, MockSession):
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({"auditLogs": [{"id": i} for i in range(100)]}),
                _response({"auditLogs": [{"id": 100}]}),
            ],
        )
        rows = _rows(self._source())
        assert [r["id"] for r in rows] == list(range(101))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_state_after_yielding(self, MockSession):
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({"auditLogs": [{"id": i} for i in range(100)]}),
                _response({"auditLogs": [{"id": 100}]}),
            ],
        )
        manager = _make_manager()
        _rows(self._source(manager=manager))

        manager.save_state.assert_called_once()
        saved = manager.save_state.call_args.args[0]
        assert isinstance(saved, FusionAuthResumeConfig)
        assert saved.offset == 100

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state(self, MockSession):
        session = MockSession.return_value
        snaps = _wire(session, [_response({"auditLogs": [{"id": 9}]})])
        manager = _make_manager(FusionAuthResumeConfig(offset=500))
        rows = _rows(self._source(manager=manager))

        assert snaps[0]["json"]["search"]["startRow"] == 500
        assert [r["id"] for r in rows] == [9]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_start_filter_reaches_request(self, MockSession):
        session = MockSession.return_value
        snaps = _wire(session, [_response({"auditLogs": [{"id": 1}]})])
        _rows(
            self._source(
                should_use_incremental_field=True,
                db_incremental_field_last_value=1700000000000,
            )
        )
        assert snaps[0]["json"]["search"]["start"] == 1700000000000
        assert snaps[0]["json"]["search"]["orderBy"] == "insertInstant ASC"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_ignores_stray_watermark(self, MockSession):
        # Users has no incremental_fields declared, so a watermark must never reach the request.
        session = MockSession.return_value
        snaps = _wire(session, [_response({"users": [{"id": 1}]})])
        _rows(
            self._source(
                endpoint="Users",
                should_use_incremental_field=True,
                db_incremental_field_last_value=1700000000000,
            )
        )
        assert "start" not in snaps[0]["json"]["search"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_users_body_shape(self, MockSession):
        session = MockSession.return_value
        snaps = _wire(session, [_response({"users": [{"id": 1}]})])
        _rows(self._source(endpoint="Users"))
        assert snaps[0]["json"]["search"]["queryString"] == "*"
        assert snaps[0]["json"]["search"]["numberOfResults"] == 100

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_does_not_follow_redirects(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_redirect_response(302)])
        with pytest.raises(ValueError):
            _rows(self._source())

    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retries_on_429(self, MockSession, _mock_sleep):
        session = MockSession.return_value
        _wire(session, [_response({}, status_code=429), _response({"auditLogs": [{"id": 1}]})])
        rows = _rows(self._source())

        assert [r["id"] for r in rows] == [1]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_runtime_host_check_blocks_unsafe_domain(self, MockSession):
        # The configured base URL is re-checked at run time (DNS rebinding) before any request.
        session = MockSession.return_value
        _wire(session, [_response({"auditLogs": [{"id": 1}]})])
        with mock.patch.object(fusionauth_module, "_is_host_safe", return_value=(False, "internal address")):
            with pytest.raises(fusionauth_module.FusionAuthHostNotAllowedError):
                _rows(self._source())
        session.send.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_runtime_rejects_plaintext_http_before_sending_key(self, MockSession):
        # A base URL edited to http:// must be refused at run time before the key leaves the process.
        session = MockSession.return_value
        _wire(session, [_response({"auditLogs": [{"id": 1}]})])
        with pytest.raises(fusionauth_module.FusionAuthHostNotAllowedError):
            _rows(self._source(base_url="http://auth.example.com"))
        session.send.assert_not_called()


class TestFusionAuthDescendingPagination:
    def _source(self, manager=None, **kwargs):
        return fusionauth_source(
            base_url="https://auth.example.com",
            api_key="tok",
            endpoint="LoginRecords",
            team_id=1,
            job_id="j",
            resumable_source_manager=manager if manager is not None else _make_manager(),
            **kwargs,
        )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_scan_when_no_watermarks(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response({"logins": [{"userId": "1"}]})])
        rows = _rows(self._source(should_use_incremental_field=True))
        assert rows == [{"userId": "1"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_scan_is_resumable(self, MockSession):
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({"logins": [{"userId": str(i)} for i in range(100)]}),
                _response({"logins": [{"userId": "100"}]}),
            ],
        )
        manager = _make_manager()
        _rows(self._source(manager=manager))

        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].offset == 100

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_earliest_and_last_value_both_queried(self, MockSession):
        session = MockSession.return_value
        snaps = _wire(
            session,
            [
                _response({"logins": [{"userId": "earlier"}]}),
                _response({"logins": [{"userId": "newer"}]}),
            ],
        )
        rows = _rows(
            self._source(
                should_use_incremental_field=True,
                db_incremental_field_earliest_value=1600000000000,
                db_incremental_field_last_value=1700000000000,
            )
        )

        assert [r["userId"] for r in rows] == ["earlier", "newer"]
        assert snaps[0]["json"]["search"]["end"] == 1600000000000
        assert snaps[1]["json"]["search"]["start"] == 1700000000000
        assert "orderBy" not in snaps[0]["json"]["search"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_only_last_value_set(self, MockSession):
        session = MockSession.return_value
        snaps = _wire(session, [_response({"logins": [{"userId": "newer"}]})])
        _rows(
            self._source(
                should_use_incremental_field=True,
                db_incremental_field_last_value=1700000000000,
                db_incremental_field_earliest_value=None,
            )
        )
        assert snaps[0]["json"]["search"]["start"] == 1700000000000

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_not_incremental_falls_back_to_full_scan(self, MockSession):
        session = MockSession.return_value
        snaps = _wire(session, [_response({"logins": [{"userId": "1"}]})])
        _rows(
            self._source(
                should_use_incremental_field=False,
                db_incremental_field_last_value=1700000000000,
            )
        )
        assert "start" not in snaps[0]["json"]["search"]


class _FakeStreamResponse:
    """Minimal streamed `requests.Response` stand-in: yields fixed chunks and records close()."""

    def __init__(self, chunks: list[bytes], *, block: bool = False) -> None:
        self._chunks = chunks
        self._block = block
        self._released = threading.Event()
        self.closed = False

    def iter_content(self, chunk_size: int = 1) -> Any:
        yield from self._chunks
        if self._block:
            # Never completes on its own; only close() releases it. Models a host that stops mid-body.
            self._released.wait()

    def close(self) -> None:
        self.closed = True
        self._released.set()


class TestReadBounded:
    def test_reads_full_body_under_cap(self):
        response = _FakeStreamResponse([b"hel", b"lo"])
        assert _read_bounded(cast(requests.Response, response), max_bytes=100) == b"hello"

    def test_raises_when_body_exceeds_byte_cap(self):
        # The cap is what stops a huge (or gzip-bombed) body from exhausting a worker's memory.
        response = _FakeStreamResponse([b"a" * 8, b"b" * 8])
        with pytest.raises(FusionAuthResponseTooLargeError):
            _read_bounded(cast(requests.Response, response), max_bytes=10)

    def test_times_out_and_closes_a_stalled_body(self):
        # A host that stalls mid-body must not pin the worker: the deadline fires and the socket is
        # closed. max_seconds=0 makes the join return immediately while the reader is still blocked.
        response = _FakeStreamResponse([b"partial"], block=True)
        with pytest.raises(FusionAuthResponseTimeoutError):
            _read_bounded(cast(requests.Response, response), max_bytes=100, max_seconds=0)
        assert response.closed is True
