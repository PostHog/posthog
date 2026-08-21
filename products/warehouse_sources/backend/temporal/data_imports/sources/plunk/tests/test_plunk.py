import io
import json
import threading
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import TrackedHTTPAdapter
from products.warehouse_sources.backend.temporal.data_imports.sources.plunk import plunk as plunk_module
from products.warehouse_sources.backend.temporal.data_imports.sources.plunk.plunk import (
    DEFAULT_TIMEOUT_SECONDS,
    HOST_NOT_ALLOWED_ERROR,
    HTTP_NOT_ALLOWED_ERROR,
    PUBLIC_KEY_ERROR,
    PlunkHostNotAllowedError,
    PlunkResponseTimeoutError,
    PlunkResponseTooLargeError,
    PlunkResumeConfig,
    _make_bounded_session,
    _read_bounded,
    normalize_base_url,
    plunk_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.plunk.settings import PLUNK_ENDPOINTS

# The sync path runs through a bounded session built by `_make_bounded_session`; patch that so the
# pagination tests can drive `session.send` directly (RESTClient uses the session it's handed).
CLIENT_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.plunk.plunk._make_bounded_session"
)


def _response(*, status_code: int = 200, body: Any = None) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode() if body is not None else b""
    return resp


def _cursor_page(rows: list[dict[str, Any]], *, cursor: str | None = None, has_more: bool = False) -> Response:
    # Plunk omits the `cursor` key entirely on the last page (undefined is dropped by JSON
    # serialization server-side), so only include it when set.
    body: dict[str, Any] = {"data": rows, "total": len(rows), "hasMore": has_more}
    if cursor is not None:
        body["cursor"] = cursor
    return _response(body=body)


def _numbered_page(rows: list[dict[str, Any]], *, page: int, total_pages: int) -> Response:
    return _response(body={"data": rows, "total": 0, "page": page, "pageSize": 100, "totalPages": total_pages})


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[requests.PreparedRequest]:
    """Wire a mock session; delegate prepare_request to a real session so auth + params are applied."""
    session.headers = {}
    real = requests.Session()
    prepared: list[requests.PreparedRequest] = []

    def _prepare(request: Any) -> requests.PreparedRequest:
        real.headers.clear()
        real.headers.update(session.headers)
        p = real.prepare_request(request)
        prepared.append(p)
        return p

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return prepared


def _make_manager(resume_state: PlunkResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _source(manager: mock.MagicMock, *, base_url: str | None = None, endpoint: str = "contacts") -> Any:
    return plunk_source(
        base_url=base_url,
        api_key="sk_test",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _qs(prepared: requests.PreparedRequest) -> dict[str, list[str]]:
    assert prepared.url is not None
    return parse_qs(urlparse(prepared.url).query)


class TestNormalizeBaseUrl:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (None, "https://next-api.useplunk.com"),
            ("", "https://next-api.useplunk.com"),
            ("   ", "https://next-api.useplunk.com"),
            ("https://next-api.useplunk.com/", "https://next-api.useplunk.com"),
            ("plunk.example.com", "https://plunk.example.com"),
            ("http://plunk.example.com/", "http://plunk.example.com"),
        ],
    )
    def test_normalize(self, raw, expected):
        assert normalize_base_url(raw) == expected

    @pytest.mark.parametrize(
        "url, expected_host",
        [
            ("https://plunk.example.com", "plunk.example.com"),
            ("https://plunk.example.com:8443", "plunk.example.com"),
        ],
    )
    def test_host_of_plain_authority(self, url, expected_host):
        assert plunk_module._host_of(url) == expected_host

    @pytest.mark.parametrize(
        "url",
        [
            # urlparse and requests/urllib3 split these authorities differently, so validating the
            # urlparse host lets a request reach a different address (SSRF). urllib3 does NOT decode
            # `%5c`, so `safe.example%5c` stays userinfo and requests connects to `127.0.0.1`, while
            # a raw `\` is a path separator and flips the split the other way. Reject them outright.
            "https://safe.example%5c@127.0.0.1",
            "https://safe.example%5C@127.0.0.1",
            "https://127.0.0.1\\@example.com",
            "https://user:pass@127.0.0.1",
        ],
    )
    def test_host_of_rejects_ambiguous_authority(self, url):
        assert plunk_module._host_of(url) == ""


class TestValidateCredentials:
    def _patch_session(self, response=None, raises=None):
        session = mock.MagicMock()
        if raises is not None:
            session.get.side_effect = raises
        else:
            session.get.return_value = response
        return mock.patch.object(plunk_module, "_make_bounded_session", return_value=session)

    def _resp(self, *, status_code=200, json_data=None):
        response = mock.MagicMock()
        response.status_code = status_code
        response.is_redirect = status_code in (301, 302, 303, 307, 308)
        response.is_permanent_redirect = status_code in (301, 308)
        response.json.return_value = json_data
        return response

    def test_success(self):
        with self._patch_session(self._resp(status_code=200)):
            assert validate_credentials(None, "sk_test") == (True, None)

    def test_invalid_key_401(self):
        with self._patch_session(self._resp(status_code=401)):
            valid, msg = validate_credentials(None, "sk_bad")
            assert valid is False
            assert "Invalid Plunk secret API key" in (msg or "")

    def test_public_key_rejected_before_any_request(self):
        # The pk_* key only works for event tracking; catching it locally gives a clearer error
        # than the API's 401 and never sends the key anywhere.
        with self._patch_session(self._resp(status_code=200)) as patched:
            assert validate_credentials(None, "pk_test") == (False, PUBLIC_KEY_ERROR)
            patched.return_value.get.assert_not_called()

    def test_403_surfaces_api_error_message(self):
        # Plunk 403s (project disabled, unverified email) block syncing outright, so source-create
        # must fail with the API's own explanation.
        response = self._resp(
            status_code=403,
            json_data={"success": False, "error": {"code": "FORBIDDEN", "message": "Please verify your email"}},
        )
        with self._patch_session(response):
            valid, msg = validate_credentials(None, "sk_test")
            assert valid is False
            assert msg == "Please verify your email"

    def test_request_exception_returns_failure(self):
        with self._patch_session(raises=requests.exceptions.ConnectionError("boom")):
            valid, msg = validate_credentials(None, "sk_test")
            assert valid is False
            assert "boom" in (msg or "")

    def test_rejects_redirect_response(self):
        with self._patch_session(self._resp(status_code=302)) as patched:
            valid, msg = validate_credentials(None, "sk_test")
            assert valid is False
            assert msg == HOST_NOT_ALLOWED_ERROR
            assert patched.return_value.get.call_args.kwargs["allow_redirects"] is False

    def test_blocks_unsafe_host_before_request(self):
        with (
            mock.patch.object(plunk_module, "_is_host_safe", return_value=(False, "internal address")),
            self._patch_session(self._resp(status_code=200)) as patched,
        ):
            valid, msg = validate_credentials("https://10.0.0.1", "sk_test", team_id=99)
            assert valid is False
            assert msg == "internal address"
            patched.return_value.get.assert_not_called()

    @pytest.mark.parametrize(
        "url",
        ["https://safe.example%5c@127.0.0.1", "https://safe.example%5C@127.0.0.1"],
    )
    def test_rejects_ambiguous_authority_before_request(self, url):
        # The urlparse host (`safe.example`) is not the address requests reaches (`127.0.0.1`), so
        # validation must fail before the key-bearing probe goes out (SSRF bypass guard).
        with self._patch_session(self._resp(status_code=200)) as patched:
            valid, msg = validate_credentials(url, "sk_test", team_id=99)
            assert valid is False
            assert msg == "Invalid Plunk API URL"
            patched.return_value.get.assert_not_called()

    def test_rejects_plaintext_http_before_sending_key(self):
        with self._patch_session(self._resp(status_code=200)) as patched:
            valid, msg = validate_credentials("http://plunk.example.com", "sk_test")
            assert valid is False
            assert msg == HTTP_NOT_ALLOWED_ERROR
            patched.return_value.get.assert_not_called()

    def test_probe_hits_configured_host_with_bearer_key(self):
        with self._patch_session(self._resp(status_code=200)) as patched:
            validate_credentials("https://plunk.example.com", "sk_test")
            call = patched.return_value.get.call_args
            assert call.args[0].startswith("https://plunk.example.com/contacts")
            assert call.kwargs["headers"]["Authorization"] == "Bearer sk_test"
            # The key is handed to the session factory (which wires it into sample redaction), and
            # the probe runs under tight validation caps so a controlled host can't hold the worker.
            assert patched.call_args.args[0] == "sk_test"
            assert patched.call_args.kwargs["max_bytes"] == plunk_module.VALIDATION_MAX_RESPONSE_BYTES
            assert patched.call_args.kwargs["max_seconds"] == plunk_module.VALIDATION_MAX_RESPONSE_SECONDS

    def test_probe_surfaces_oversized_or_stalled_body_as_failure(self):
        # A controlled host that overruns the validation caps fails source-create rather than
        # propagating as an unhandled 500 out of the inline probe.
        with self._patch_session(raises=plunk_module.PlunkResponseTooLargeError("too big")):
            valid, msg = validate_credentials("https://plunk.example.com", "sk_test")
            assert valid is False
            assert "too big" in (msg or "")


class TestSourceResponseShape:
    @pytest.mark.parametrize("endpoint", list(PLUNK_ENDPOINTS.keys()))
    def test_response_shape(self, endpoint):
        config = PLUNK_ENDPOINTS[endpoint]
        response = _source(_make_manager(), endpoint=endpoint)
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == config.sort_mode
        if config.partition_key:
            assert response.partition_keys == [config.partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None
            assert response.partition_mode is None


class TestCursorPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_cursor_until_omitted(self, MockSession):
        session = MockSession.return_value
        prepared = _wire(
            session,
            [
                _cursor_page([{"id": "1"}, {"id": "2"}], cursor="c_2", has_more=True),
                _cursor_page([{"id": "3"}]),
            ],
        )
        rows = _rows(_source(_make_manager()))

        assert [r["id"] for r in rows] == ["1", "2", "3"]
        first_qs, second_qs = _qs(prepared[0]), _qs(prepared[1])
        # First request carries the stable ascending sort and page size; no cursor yet.
        assert first_qs["limit"] == ["100"]
        assert first_qs["sort"] == ["createdAt"]
        assert first_qs["dir"] == ["asc"]
        assert "cursor" not in first_qs
        assert second_qs["cursor"] == ["c_2"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_cursor_after_yielding(self, MockSession):
        session = MockSession.return_value
        _wire(
            session,
            [
                _cursor_page([{"id": "1"}], cursor="c_1", has_more=True),
                _cursor_page([{"id": "2"}]),
            ],
        )
        manager = _make_manager()
        _rows(_source(manager))

        # State is saved once (after page 1, pointing at the next cursor); the last page is terminal.
        assert manager.save_state.call_count == 1
        saved = manager.save_state.call_args.args[0]
        assert isinstance(saved, PlunkResumeConfig)
        assert saved.cursor == "c_1"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession):
        session = MockSession.return_value
        prepared = _wire(session, [_cursor_page([{"id": "9"}])])
        rows = _rows(_source(_make_manager(PlunkResumeConfig(cursor="c_9"))))

        assert _qs(prepared[0])["cursor"] == ["c_9"]
        assert [r["id"] for r in rows] == ["9"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sends_bearer_key_and_redacts_it(self, MockSession):
        session = MockSession.return_value
        prepared = _wire(session, [_cursor_page([{"id": "1"}])])
        _rows(_source(_make_manager()))

        assert prepared[0].headers["Authorization"] == "Bearer sk_test"
        # The key is handed to the session factory, which wires it into the tracked adapter's
        # value redaction (asserted directly in TestBoundedSession).
        assert MockSession.call_args.args == ("sk_test",)
        assert session.send.call_args.kwargs["allow_redirects"] is False


class TestPageNumberPagination:
    @pytest.mark.parametrize("endpoint", ["campaigns", "templates"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_via_total_pages(self, MockSession, endpoint):
        session = MockSession.return_value
        prepared = _wire(
            session,
            [
                _numbered_page([{"id": "1"}], page=1, total_pages=2),
                _numbered_page([{"id": "2"}], page=2, total_pages=2),
            ],
        )
        rows = _rows(_source(_make_manager(), endpoint=endpoint))

        assert [r["id"] for r in rows] == ["1", "2"]
        first_qs = _qs(prepared[0])
        assert first_qs["page"] == ["1"]
        assert first_qs["pageSize"] == ["100"]
        assert first_qs["sort"] == ["createdAt"]
        assert first_qs["dir"] == ["asc"]
        assert _qs(prepared[1])["page"] == ["2"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_next_page_after_yielding_and_resumes(self, MockSession):
        session = MockSession.return_value
        _wire(
            session,
            [
                _numbered_page([{"id": "1"}], page=1, total_pages=2),
                _numbered_page([{"id": "2"}], page=2, total_pages=2),
            ],
        )
        manager = _make_manager()
        _rows(_source(manager, endpoint="campaigns"))

        assert manager.save_state.call_count == 1
        saved = manager.save_state.call_args.args[0]
        assert saved.page == 2

        session_two = mock.MagicMock()
        with mock.patch(CLIENT_SESSION_PATCH, return_value=session_two):
            prepared = _wire(session_two, [_numbered_page([{"id": "2"}], page=2, total_pages=2)])
            rows = _rows(_source(_make_manager(PlunkResumeConfig(page=2)), endpoint="campaigns"))

        assert _qs(prepared[0])["page"] == ["2"]
        assert [r["id"] for r in rows] == ["2"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_terminates(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_numbered_page([], page=1, total_pages=5)])
        manager = _make_manager()
        rows = _rows(_source(manager, endpoint="templates"))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()


class TestSegments:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_bare_array_ingested_in_single_request(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response(body=[{"id": "s1"}, {"id": "s2"}])])
        manager = _make_manager()
        rows = _rows(_source(manager, endpoint="segments"))

        assert [r["id"] for r in rows] == ["s1", "s2"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()


class TestHostSafety:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_raises_when_host_not_allowed_at_sync_time(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_cursor_page([{"id": "1"}])])
        with mock.patch.object(plunk_module, "_is_host_safe", return_value=(False, "internal address")):
            with pytest.raises(PlunkHostNotAllowedError):
                _rows(_source(_make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_raises_on_plaintext_http_before_sending_key(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_cursor_page([{"id": "1"}])])
        with pytest.raises(PlunkHostNotAllowedError):
            _rows(_source(_make_manager(), base_url="http://plunk.example.com"))
        session.send.assert_not_called()


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
        with pytest.raises(PlunkResponseTooLargeError):
            _read_bounded(cast(requests.Response, response), max_bytes=10)

    def test_times_out_and_closes_a_stalled_body(self):
        # A host that stalls mid-body must not pin the worker: the deadline fires and the socket is
        # closed. max_seconds=0 makes the join return immediately while the reader is still blocked.
        response = _FakeStreamResponse([b"partial"], block=True)
        with pytest.raises(PlunkResponseTimeoutError):
            _read_bounded(cast(requests.Response, response), max_bytes=100, max_seconds=0)
        assert response.closed is True


class TestBoundedSession:
    def test_send_pins_default_timeout_and_rebuffers_body(self):
        session = _make_bounded_session("sk_test")
        captured: dict[str, Any] = {}

        def fake_super_send(request, **kwargs):
            captured.update(kwargs)
            resp = requests.Response()
            resp.status_code = 200
            resp.raw = io.BytesIO(b'{"data": []}')
            return resp

        with mock.patch.object(requests.Session, "send", side_effect=fake_super_send):
            response = session.send(requests.PreparedRequest())

        # A timeout is pinned when the caller passes none, redirects are refused, and the body is
        # streamed — then re-buffered so RESTClient's `.json()` still works.
        assert captured["timeout"] == DEFAULT_TIMEOUT_SECONDS
        assert captured["allow_redirects"] is False
        assert captured["stream"] is True
        assert response.json() == {"data": []}

    def test_factory_wires_key_redaction_into_adapter(self):
        session = _make_bounded_session("sk_secret")
        adapter = cast(TrackedHTTPAdapter, session.get_adapter("https://plunk.example.com"))
        assert adapter._redact_values == ("sk_secret",)
