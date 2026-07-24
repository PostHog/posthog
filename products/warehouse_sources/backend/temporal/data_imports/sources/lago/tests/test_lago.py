import json
from typing import Any, Optional
from urllib.parse import urlparse

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.lago import lago as lago_module
from products.warehouse_sources.backend.temporal.data_imports.sources.lago.lago import (
    DEFAULT_API_HOST,
    LagoHostNotAllowedError,
    LagoResumeConfig,
    lago_source,
    normalize_base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lago.settings import LAGO_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# tenacity sleeps between the client's retries; short-circuit it so retry tests don't wait.
SLEEP_PATCH = "tenacity.nap.time.sleep"


def _page(
    rows: Optional[list[dict[str, Any]]],
    *,
    total_pages: int = 1,
    next_page: Optional[int] = None,
    data_key: str = "customers",
    status_code: int = 200,
    drop_data: bool = False,
) -> Response:
    body: dict[str, Any] = {"meta": {"total_pages": total_pages, "next_page": next_page}}
    if not drop_data:
        body[data_key] = rows if rows is not None else []
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _redirect(status_code: int = 302) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp.headers["Location"] = "https://internal.example.com/api/v1/customers"
    resp._content = b""
    return resp


def _make_manager(resume_state: Optional[LagoResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's query params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so a copy is snapshotted when each
    request is prepared. ``prepared.url`` is set to the real request URL so the client's
    host-pinning check (allowed_hosts) resolves a real hostname rather than a MagicMock.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        prepared = mock.MagicMock()
        prepared.url = request.url
        prepared.is_redirect = False
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(manager, *, endpoint: str = "customers", api_url: Optional[str] = None, team_id: int = 1):
    return lago_source(
        api_url=api_url,
        api_key="key",
        endpoint=endpoint,
        team_id=team_id,
        job_id="job-1",
        resumable_source_manager=manager,
    )


class TestNormalizeBaseUrl:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (None, "https://api.getlago.com/api/v1"),
            ("", "https://api.getlago.com/api/v1"),
            ("   ", "https://api.getlago.com/api/v1"),
            ("https://api.getlago.com", "https://api.getlago.com/api/v1"),
            ("https://api.getlago.com/", "https://api.getlago.com/api/v1"),
            ("https://api.getlago.com/api/v1", "https://api.getlago.com/api/v1"),
            ("billing.example.com", "https://billing.example.com/api/v1"),
            ("http://billing.example.com/", "http://billing.example.com/api/v1"),
            ("https://billing.example.com/api/v2", "https://billing.example.com/api/v1"),
        ],
    )
    def test_normalize(self, raw, expected):
        assert normalize_base_url(raw) == expected


class TestValidateCredentials:
    def _patch_session(self, response=None, raises=None):
        session = mock.MagicMock()
        if raises is not None:
            session.get.side_effect = raises
        else:
            session.get.return_value = response
        return mock.patch.object(lago_module, "make_tracked_session", return_value=session)

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
            assert validate_credentials(None, "key") == (True, None)

    def test_invalid_key(self):
        with self._patch_session(self._resp(status_code=401)):
            valid, msg = validate_credentials(None, "key")
            assert valid is False
            assert msg == "Invalid Lago API key"

    def test_403_at_source_create_is_accepted(self):
        with self._patch_session(self._resp(status_code=403)):
            assert validate_credentials(None, "key", schema_name=None) == (True, None)

    def test_403_for_scoped_probe_fails(self):
        with self._patch_session(self._resp(status_code=403)):
            valid, msg = validate_credentials(None, "key", schema_name="invoices")
            assert valid is False
            assert msg is not None

    def test_request_exception_returns_failure(self):
        import requests

        with self._patch_session(raises=requests.exceptions.ConnectionError("boom")):
            valid, msg = validate_credentials(None, "key")
            assert valid is False
            assert "boom" in (msg or "")

    def test_rejects_redirect_response(self):
        with self._patch_session(self._resp(status_code=302)) as patched:
            valid, msg = validate_credentials(None, "key")
            assert valid is False
            assert msg == lago_module.HOST_NOT_ALLOWED_ERROR
            assert patched.return_value.get.call_args.kwargs["allow_redirects"] is False

    def test_blocks_unsafe_host(self):
        with (
            mock.patch.object(lago_module, "_is_host_safe", return_value=(False, "internal address")),
            self._patch_session(self._resp(status_code=200)) as patched,
        ):
            valid, msg = validate_credentials("http://10.0.0.1", "key", team_id=99)
            assert valid is False
            assert msg == "internal address"
            patched.return_value.get.assert_not_called()

    def test_probe_hits_configured_host(self):
        with self._patch_session(self._resp(status_code=200)) as patched:
            validate_credentials("https://billing.example.com", "key")
            url = patched.return_value.get.call_args.args[0]
            assert url.startswith("https://billing.example.com/api/v1/customers")


class TestLagoSourceResponse:
    @pytest.mark.parametrize("endpoint", list(LAGO_ENDPOINTS.keys()))
    def test_response_shape(self, endpoint):
        response = _source(_make_manager(), endpoint=endpoint)
        assert response.name == endpoint
        assert response.primary_keys == ["lago_id"]
        assert response.sort_mode == "asc"
        assert response.partition_keys == ["created_at"]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_and_progresses_page(self, MockSession):
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _page([{"lago_id": "1"}, {"lago_id": "2"}], total_pages=2, next_page=2),
                _page([{"lago_id": "3"}], total_pages=2, next_page=None),
            ],
        )

        rows = _rows(_source(_make_manager()))

        assert [r["lago_id"] for r in rows] == ["1", "2", "3"]
        # First request page=1, second request page=2, both carry per_page.
        assert params[0]["page"] == 1
        assert params[0]["per_page"] == 100
        assert params[1]["page"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_next_page_after_yielding(self, MockSession):
        session = MockSession.return_value
        _wire(
            session,
            [
                _page([{"lago_id": "1"}], total_pages=2, next_page=2),
                _page([{"lago_id": "2"}], total_pages=2, next_page=None),
            ],
        )

        manager = _make_manager()
        _rows(_source(manager))

        # State is saved once (after page 1, pointing at page 2); the last page ends pagination.
        assert manager.save_state.call_count == 1
        saved = manager.save_state.call_args.args[0]
        assert isinstance(saved, LagoResumeConfig)
        assert saved.next_page == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state(self, MockSession):
        session = MockSession.return_value
        params = _wire(session, [_page([{"lago_id": "9"}], total_pages=3, next_page=None)])

        rows = _rows(_source(_make_manager(LagoResumeConfig(next_page=3))))

        assert params[0]["page"] == 3
        assert [r["lago_id"] for r in rows] == ["9"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_terminates(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_page([], total_pages=1, next_page=2)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_yields_nothing_and_stops(self, MockSession):
        # The old transport treated a missing collection key as a terminal empty page (not an error);
        # data_selector is not marked required, so an absent key yields 0 rows and stops.
        session = MockSession.return_value
        _wire(session, [_page(None, drop_data=True)])

        rows = _rows(_source(_make_manager()))

        assert rows == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_per_endpoint_path_and_data_key(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_page([{"lago_id": "p1"}], data_key="plans", total_pages=1, next_page=None)])

        rows = _rows(_source(_make_manager(), endpoint="plans"))

        assert [r["lago_id"] for r in rows] == ["p1"]
        assert urlparse(session.prepare_request.call_args_list[0].args[0].url).path.endswith("/plans")


class TestRedirectAndHostGuards:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_rejects_redirect(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_redirect(302)])

        # allow_redirects=False in the client config surfaces a 3xx as a loud, non-retryable error.
        with pytest.raises(ValueError, match="redirect"):
            _rows(_source(_make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_does_not_follow_redirects(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_page([{"lago_id": "1"}], total_pages=1, next_page=None)])

        _rows(_source(_make_manager()))
        assert session.send.call_args.kwargs["allow_redirects"] is False

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_raises_when_host_not_allowed(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_page([{"lago_id": "1"}], total_pages=1, next_page=None)])

        with mock.patch.object(lago_module, "_is_host_safe", return_value=(False, "internal address")):
            with pytest.raises(LagoHostNotAllowedError):
                _rows(_source(_make_manager()))
        # The SSRF pre-check fires before any request leaves the process.
        session.send.assert_not_called()


class TestRetries:
    @pytest.mark.parametrize("status_code", [429, 503])
    @mock.patch(SLEEP_PATCH, return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retries_retryable_status_then_succeeds(self, MockSession, _sleep, status_code):
        # A retryable status raises inside the client, tenacity retries, and the subsequent 200
        # yields rows. Guards against dropping the retry behavior in the migration.
        session = MockSession.return_value
        _wire(
            session,
            [
                _page([], total_pages=1, next_page=None, status_code=status_code),
                _page([{"lago_id": "r1"}], total_pages=1, next_page=None),
            ],
        )

        rows = _rows(_source(_make_manager()))

        assert [r["lago_id"] for r in rows] == ["r1"]
        assert session.send.call_count == 2


class TestBaseUrl:
    def test_default_host_constant(self):
        assert DEFAULT_API_HOST == "https://api.getlago.com"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_requests_target_base_host(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_page([{"lago_id": "1"}], total_pages=1, next_page=None)])

        _rows(_source(_make_manager()))
        parsed = urlparse(session.prepare_request.call_args_list[0].args[0].url)
        assert parsed.hostname == "api.getlago.com"
        assert parsed.path == "/api/v1/customers"
