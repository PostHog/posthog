import json
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.invoiceninja import (
    invoiceninja as invoiceninja_module,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.invoiceninja.invoiceninja import (
    InvoiceNinjaHostNotAllowedError,
    InvoiceNinjaResumeConfig,
    invoiceninja_source,
    normalize_base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.invoiceninja.settings import (
    INVOICENINJA_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def _response(*, status_code: int = 200, body: Any = None, location: str | None = None) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode() if body is not None else b""
    if location is not None:
        resp.headers["Location"] = location
    return resp


def _page(
    rows: list[dict[str, Any]],
    *,
    current_page: int | None = None,
    total_pages: int | None = None,
    links_next: Any = "__omit__",
    with_meta: bool = True,
) -> Response:
    pagination: dict[str, Any] = {}
    if current_page is not None:
        pagination["current_page"] = current_page
    if total_pages is not None:
        pagination["total_pages"] = total_pages
    if links_next != "__omit__":
        pagination["links"] = {"next": links_next}
    body: dict[str, Any] = {"data": rows}
    if with_meta:
        body["meta"] = {"pagination": pagination}
    return _response(body=body)


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[requests.PreparedRequest]:
    """Wire a mock session; delegate prepare_request to a real session so auth + params are applied.

    The framework mutates a single request/params dict in place across pages, so we snapshot each
    prepared request (its URL carries the page/per_page query and its headers carry the auth) as the
    client prepares it, then return canned responses from ``send``.
    """
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


def _make_manager(resume_state: InvoiceNinjaResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _source(manager: mock.MagicMock, *, base_url: str | None = None, endpoint: str = "clients") -> Any:
    return invoiceninja_source(
        base_url=base_url,
        api_token="tok",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _page_qs(prepared: requests.PreparedRequest) -> list[str]:
    return parse_qs(urlparse(prepared.url).query)["page"]


class TestNormalizeBaseUrl:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (None, "https://invoicing.co/api/v1"),
            ("", "https://invoicing.co/api/v1"),
            ("   ", "https://invoicing.co/api/v1"),
            ("https://invoicing.co", "https://invoicing.co/api/v1"),
            ("https://invoicing.co/", "https://invoicing.co/api/v1"),
            ("https://invoicing.co/api/v1", "https://invoicing.co/api/v1"),
            ("invoices.example.com", "https://invoices.example.com/api/v1"),
            ("http://invoices.example.com/", "http://invoices.example.com/api/v1"),
            ("https://invoices.example.com/api/v5", "https://invoices.example.com/api/v1"),
        ],
    )
    def test_normalize(self, raw, expected):
        assert normalize_base_url(raw) == expected


class TestHostOf:
    @pytest.mark.parametrize(
        "url, expected_host",
        [
            ("https://invoices.example.com/api/v1", "invoices.example.com"),
            # Backslash (and its %5c encoding) is userinfo to urlparse but a path separator to
            # requests/urllib3 — the host must reflect the address the request actually reaches, or
            # the SSRF check validates a decoy host while the token goes elsewhere.
            ("https://127.0.0.1\\@example.com/api/v1", "127.0.0.1"),
            ("https://127.0.0.1%5c@example.com/api/v1", "127.0.0.1"),
            ("https://127.0.0.1%5C@example.com/api/v1", "127.0.0.1"),
        ],
    )
    def test_host_reflects_real_connect_target(self, url, expected_host):
        assert invoiceninja_module._host_of(url) == expected_host


class TestValidateCredentials:
    def _patch_session(self, response=None, raises=None):
        session = mock.MagicMock()
        if raises is not None:
            session.get.side_effect = raises
        else:
            session.get.return_value = response
        return mock.patch.object(invoiceninja_module, "make_tracked_session", return_value=session)

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
            assert validate_credentials(None, "tok") == (True, None)

    def test_invalid_token_401(self):
        with self._patch_session(self._resp(status_code=401)):
            valid, msg = validate_credentials(None, "tok")
            assert valid is False
            assert msg == "Invalid Invoice Ninja API token"

    def test_invalid_token_403_message_always_fails(self):
        # A bad Invoice Ninja token returns 403 {"message": "Invalid token"} — reject it even at create.
        response = self._resp(status_code=403, json_data={"message": "Invalid token"})
        with self._patch_session(response):
            valid, msg = validate_credentials(None, "tok", schema_name=None)
            assert valid is False
            assert msg == "Invalid Invoice Ninja API token"

    def test_permission_403_at_source_create_is_accepted(self):
        # A 403 without the "Invalid token" message is a restricted (enterprise) token, not a bad one.
        response = self._resp(status_code=403, json_data={"message": "This action is unauthorized."})
        with self._patch_session(response):
            assert validate_credentials(None, "tok", schema_name=None) == (True, None)

    def test_permission_403_for_scoped_probe_fails(self):
        response = self._resp(status_code=403, json_data={"message": "This action is unauthorized."})
        with self._patch_session(response):
            valid, msg = validate_credentials(None, "tok", schema_name="invoices")
            assert valid is False
            assert msg is not None

    def test_request_exception_returns_failure(self):
        with self._patch_session(raises=requests.exceptions.ConnectionError("boom")):
            valid, msg = validate_credentials(None, "tok")
            assert valid is False
            assert "boom" in (msg or "")

    def test_rejects_redirect_response(self):
        with self._patch_session(self._resp(status_code=302)) as patched:
            valid, msg = validate_credentials(None, "tok")
            assert valid is False
            assert msg == invoiceninja_module.HOST_NOT_ALLOWED_ERROR
            assert patched.return_value.get.call_args.kwargs["allow_redirects"] is False

    def test_blocks_unsafe_host(self):
        with (
            mock.patch.object(invoiceninja_module, "_is_host_safe", return_value=(False, "internal address")),
            self._patch_session(self._resp(status_code=200)) as patched,
        ):
            valid, msg = validate_credentials("http://10.0.0.1", "tok", team_id=99)
            assert valid is False
            assert msg == "internal address"
            patched.return_value.get.assert_not_called()

    def test_probe_hits_configured_host_with_required_headers(self):
        with self._patch_session(self._resp(status_code=200)) as patched:
            validate_credentials("https://invoices.example.com", "tok")
            call = patched.return_value.get.call_args
            assert call.args[0].startswith("https://invoices.example.com/api/v1/clients")
            headers = call.kwargs["headers"]
            assert headers["X-API-TOKEN"] == "tok"
            assert headers["X-Requested-With"] == "XMLHttpRequest"

    def test_redacts_token_in_telemetry(self):
        # The token rides in X-API-TOKEN, which the transport's name-based scrubber doesn't cover, so
        # it must be passed as a redact value to keep it out of captured HTTP samples.
        with self._patch_session(self._resp(status_code=200)) as patched:
            validate_credentials(None, "tok")
            assert patched.call_args.kwargs["redact_values"] == ("tok",)

    def test_rejects_plaintext_http_before_sending_token(self):
        # A plaintext http:// URL would expose the X-API-TOKEN on the wire, so reject it without
        # ever issuing the token-bearing request.
        with self._patch_session(self._resp(status_code=200)) as patched:
            valid, msg = validate_credentials("http://invoices.example.com", "tok")
            assert valid is False
            assert msg == invoiceninja_module.HTTP_NOT_ALLOWED_ERROR
            patched.return_value.get.assert_not_called()


class TestInvoiceNinjaSourceResponse:
    @pytest.mark.parametrize("endpoint", list(INVOICENINJA_ENDPOINTS.keys()))
    def test_response_shape(self, endpoint):
        response = _source(_make_manager(), endpoint=endpoint)
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        # Integer unix timestamps aren't datetime-partitionable, so no partitioning is applied.
        assert response.partition_keys is None
        assert response.partition_mode is None


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_via_meta_pagination(self, MockSession):
        session = MockSession.return_value
        prepared = _wire(
            session,
            [
                _page([{"id": "1"}, {"id": "2"}], current_page=1, total_pages=2),
                _page([{"id": "3"}], current_page=2, total_pages=2),
            ],
        )
        rows = _rows(_source(_make_manager()))

        assert [r["id"] for r in rows] == ["1", "2", "3"]
        assert _page_qs(prepared[0]) == ["1"]
        assert _page_qs(prepared[1]) == ["2"]
        # per_page rides alongside the page param on every request.
        assert parse_qs(urlparse(prepared[0].url).query)["per_page"] == ["100"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_next_page_after_yielding(self, MockSession):
        session = MockSession.return_value
        _wire(
            session,
            [
                _page([{"id": "1"}], current_page=1, total_pages=2),
                _page([{"id": "2"}], current_page=2, total_pages=2),
            ],
        )
        manager = _make_manager()
        _rows(_source(manager))

        # State is saved once (after page 1, pointing at page 2); the last page is terminal.
        assert manager.save_state.call_count == 1
        saved = manager.save_state.call_args.args[0]
        assert isinstance(saved, InvoiceNinjaResumeConfig)
        assert saved.next_page == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state(self, MockSession):
        session = MockSession.return_value
        prepared = _wire(session, [_page([{"id": "9"}], current_page=3, total_pages=3)])
        manager = _make_manager(InvoiceNinjaResumeConfig(next_page=3))
        rows = _rows(_source(manager))

        assert _page_qs(prepared[0]) == ["3"]
        assert [r["id"] for r in rows] == ["9"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_via_links_next_when_page_counts_absent(self, MockSession):
        # Some deployments only expose `links.next` without current/total page counts.
        session = MockSession.return_value
        prepared = _wire(
            session,
            [
                _page([{"id": "1"}], links_next="https://next"),
                _page([{"id": "2"}], links_next=None),
            ],
        )
        rows = _rows(_source(_make_manager()))

        assert [r["id"] for r in rows] == ["1", "2"]
        assert session.send.call_count == 2
        assert _page_qs(prepared[1]) == ["2"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_terminates(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_page([], current_page=1, total_pages=5)])
        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_pagination_terminates_after_first_page(self, MockSession):
        # A response with no pagination block must not loop forever.
        session = MockSession.return_value
        _wire(session, [_page([{"id": "1"}], with_meta=False)])
        manager = _make_manager()
        rows = _rows(_source(manager))

        assert [r["id"] for r in rows] == ["1"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_does_not_follow_redirects(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response(status_code=302, location="https://internal")])
        # With redirects disabled the framework rejects a 3xx before following it.
        with pytest.raises(ValueError):
            _rows(_source(_make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_passes_allow_redirects_false(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_page([{"id": "1"}], current_page=1, total_pages=1)])
        _rows(_source(_make_manager()))
        assert session.send.call_args.kwargs["allow_redirects"] is False

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sends_required_headers_and_token(self, MockSession):
        session = MockSession.return_value
        prepared = _wire(session, [_page([{"id": "1"}], current_page=1, total_pages=1)])
        _rows(_source(_make_manager()))
        headers = prepared[0].headers
        assert headers["X-API-TOKEN"] == "tok"
        assert headers["X-Requested-With"] == "XMLHttpRequest"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_redacts_token_in_telemetry(self, MockSession):
        # The api_key auth carries the token, so the framework masks it in logs / raised errors by
        # passing it to the tracked session as a redact value.
        session = MockSession.return_value
        _wire(session, [_page([{"id": "1"}], current_page=1, total_pages=1)])
        _rows(_source(_make_manager()))
        assert MockSession.call_args.kwargs["redact_values"] == ("tok",)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_raises_when_host_not_allowed(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_page([{"id": "1"}], current_page=1, total_pages=1)])
        with mock.patch.object(invoiceninja_module, "_is_host_safe", return_value=(False, "internal address")):
            with pytest.raises(InvoiceNinjaHostNotAllowedError):
                _rows(_source(_make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_raises_on_plaintext_http(self, MockSession):
        # A plaintext http:// URL must fail before the token-bearing request goes out.
        session = MockSession.return_value
        _wire(session, [_page([{"id": "1"}], current_page=1, total_pages=1)])
        with pytest.raises(InvoiceNinjaHostNotAllowedError):
            _rows(_source(_make_manager(), base_url="http://invoices.example.com"))

    @pytest.mark.parametrize("status_code", [429, 503])
    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retries_retryable_status_then_succeeds(self, MockSession, _sleep, status_code):
        # End-to-end: a retryable status raises, the framework retries, and the next 200 yields rows.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(status_code=status_code),
                _page([{"id": "r1"}], current_page=1, total_pages=1),
            ],
        )
        rows = _rows(_source(_make_manager()))
        assert [r["id"] for r in rows] == ["r1"]
        assert session.send.call_count == 2
