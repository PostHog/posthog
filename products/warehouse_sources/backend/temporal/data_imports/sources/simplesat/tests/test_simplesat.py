import json
from typing import Any, Optional

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.simplesat.settings import (
    ENDPOINTS,
    SIMPLESAT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.simplesat.simplesat import (
    SIMPLESAT_BASE_URL,
    SimplesatResumeConfig,
    simplesat_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the simplesat module.
SIMPLESAT_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.simplesat.simplesat.make_tracked_session"
)
# tenacity sleeps between retries; patch it so retry-exhaustion paths don't slow the suite.
SLEEP_PATCH = "tenacity.nap.time.sleep"


def _response(
    list_key: str,
    items: Any,
    *,
    next_url: Optional[str] = None,
    include_key: bool = True,
    status: int = 200,
    url: str = f"{SIMPLESAT_BASE_URL}/surveys",
) -> Response:
    body: dict[str, Any] = {"count": 0, "next": next_url, "previous": None}
    if include_key:
        body[list_key] = items
    resp = Response()
    resp.status_code = status
    resp.url = url
    resp._content = json.dumps(body).encode()
    return resp


def _raw_response(payload: Any, *, status: int = 200) -> Response:
    """A response whose top-level body is exactly ``payload`` (e.g. a bare list)."""
    resp = Response()
    resp.status_code = status
    resp.url = f"{SIMPLESAT_BASE_URL}/surveys"
    resp._content = json.dumps(payload).encode()
    return resp


def _make_manager(resume_state: SimplesatResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: Any) -> list[dict[str, Any]]:
    """Wire a mock session; return a list capturing each request's method/url/params/json AT SEND TIME.

    ``request`` fields are mutated in place across pages, so snapshot a copy when each request is
    prepared. ``prepared.url`` mirrors ``request.url`` so the client's host-pinning check sees the
    real (possibly off-host) URL. ``responses`` may be a list (consumed in order) or a callable.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append(
            {
                "method": request.method,
                "url": request.url,
                "params": dict(request.params or {}),
                "json": request.json,
            }
        )
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock) -> Any:
    return simplesat_source(
        api_key="ss-key", endpoint=endpoint, team_id=1, job_id="j", resumable_source_manager=manager
    )


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_with_null_next_stops(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response("surveys", [{"id": 1}, {"id": 2}], next_url=None)])

        manager = _make_manager()
        rows = _rows(_source("surveys", manager))

        assert rows == [{"id": 1}, {"id": 2}]
        assert session.send.call_count == 1
        # `next` is null, so we stop without persisting resume state.
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_next_url_until_null_and_checkpoints(self, MockSession) -> None:
        session = MockSession.return_value
        next_url = f"{SIMPLESAT_BASE_URL}/surveys?page=2&page_size=100"
        snapshots = _wire(
            session,
            [
                _response("surveys", [{"id": 1}], next_url=next_url),
                _response("surveys", [{"id": 2}], next_url=None, url=next_url),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("surveys", manager))

        assert rows == [{"id": 1}, {"id": 2}]
        # First request carries page_size; the follow-up targets the self-contained next URL with no
        # re-appended params.
        assert snapshots[0]["params"] == {"page_size": 100}
        assert snapshots[1]["url"] == next_url
        assert snapshots[1]["params"] == {}
        # State is saved with the cursor after the first page, then we stop on the null `next`.
        manager.save_state.assert_called_once_with(SimplesatResumeConfig(next_url=next_url))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor_without_refetching_first_page(self, MockSession) -> None:
        session = MockSession.return_value
        next_url = f"{SIMPLESAT_BASE_URL}/surveys?page=2&page_size=100"
        snapshots = _wire(session, [_response("surveys", [{"id": 5}], next_url=None, url=next_url)])

        manager = _make_manager(SimplesatResumeConfig(next_url=next_url))
        rows = _rows(_source("surveys", manager))

        assert rows == [{"id": 5}]
        # The one and only request goes straight to the saved cursor — the first page is never fetched.
        assert session.send.call_count == 1
        assert snapshots[0]["url"] == next_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response("surveys", [], next_url=None)])

        manager = _make_manager()
        assert _rows(_source("surveys", manager)) == []
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_post_endpoint_uses_post_with_empty_json_body(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response("answers", [{"id": 1}], next_url=None)])

        rows = _rows(_source("answers", _make_manager()))

        assert rows == [{"id": 1}]
        assert snapshots[0]["method"] == "POST"
        assert snapshots[0]["json"] == {}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_get_endpoint_sends_no_json_body(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response("surveys", [{"id": 1}], next_url=None)])

        _rows(_source("surveys", _make_manager()))

        assert snapshots[0]["method"] == "GET"
        assert snapshots[0]["json"] is None

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_api_key_rides_header_auth_not_client_headers(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response("surveys", [{"id": 1}], next_url=None)])

        _rows(_source("surveys", _make_manager()))

        # The secret is injected via framework api_key auth (redacted), so it must not sit in the
        # non-secret client headers copied onto the session.
        assert "X-Simplesat-Token" not in session.headers
        assert session.headers.get("Accept") == "application/json"


class TestHostPinning:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_off_origin_next_url_is_rejected_before_it_is_fetched(self, MockSession) -> None:
        session = MockSession.return_value
        evil = "https://evil.example.com/api/v1/surveys?page=2"
        _wire(session, [_response("surveys", [{"id": 1}], next_url=evil)])

        # A pagination cursor pointing off the Simplesat host must not be followed — it would leak the
        # customer's API key to another origin.
        with pytest.raises(ValueError, match="disallowed host"):
            _rows(_source("surveys", _make_manager()))
        # Only the first (on-host) page was actually sent; the off-host URL never left the process.
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_off_origin_resume_url_is_rejected(self, MockSession) -> None:
        session = MockSession.return_value
        evil = "https://evil.example.com/api/v1/surveys?page=2"
        _wire(session, [_response("surveys", [{"id": 5}], next_url=None, url=evil)])

        manager = _make_manager(SimplesatResumeConfig(next_url=evil))
        # A tampered saved cursor is rejected before any request is made.
        with pytest.raises(ValueError, match="disallowed host"):
            _rows(_source("surveys", manager))
        session.send.assert_not_called()

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_redirect_is_rejected(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        redirect = Response()
        redirect.status_code = 302
        redirect.url = f"{SIMPLESAT_BASE_URL}/surveys"
        redirect.headers["Location"] = "https://evil.example.com/steal"
        _wire(session, [redirect])

        # Redirects are disabled, so a 3xx can't smuggle the request (and API key) to another origin.
        with pytest.raises(ValueError, match="[Rr]edirect"):
            _rows(_source("surveys", _make_manager()))


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_retry_then_reraise(self, _name: str, status: int, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, lambda *a, **k: _response("surveys", [], status=status))

        with pytest.raises(RESTClientRetryableError):
            _rows(_source("surveys", _make_manager()))
        # Retried up to the client's attempt cap before giving up.
        assert session.send.call_count == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_raise_immediately(self, _name: str, status: int, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response("surveys", [], status=status)])

        with pytest.raises(requests.HTTPError):
            _rows(_source("surveys", _make_manager()))
        # A 4xx is permanent — no retry.
        assert session.send.call_count == 1

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_dict_body_is_retried(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, lambda *a, **k: _raw_response([{"id": 1}]))

        with pytest.raises(RESTClientRetryableError):
            _rows(_source("surveys", _make_manager()))
        assert session.send.call_count == 5

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_resource_key_is_retried(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, lambda *a, **k: _response("surveys", {"nope": 1}, next_url=None))

        with pytest.raises(RESTClientRetryableError):
            _rows(_source("surveys", _make_manager()))
        assert session.send.call_count == 5

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_resource_key_is_retried(self, MockSession, _sleep) -> None:
        # A response envelope without the resource key must not silently sync zero rows.
        session = MockSession.return_value
        _wire(session, lambda *a, **k: _response("surveys", None, include_key=False, next_url=None))

        with pytest.raises(RESTClientRetryableError):
            _rows(_source("surveys", _make_manager()))
        assert session.send.call_count == 5


class TestValidateCredentials:
    def _patch_session(self, monkeypatch: Any, response: Any) -> mock.MagicMock:
        session = mock.MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        monkeypatch.setattr(
            "products.warehouse_sources.backend.temporal.data_imports.sources.simplesat.simplesat.make_tracked_session",
            lambda **kwargs: session,
        )
        return session

    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid Simplesat API key"),
            (403, False, "Invalid Simplesat API key"),
            (500, False, "Simplesat returned HTTP 500"),
        ],
    )
    def test_status_mapping(
        self, status: int, expected_valid: bool, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = mock.MagicMock(status_code=status)
        self._patch_session(monkeypatch, response)
        assert validate_credentials("ss-key") == (expected_valid, expected_message)

    def test_connection_error_is_not_validated(self, monkeypatch: Any) -> None:
        self._patch_session(monkeypatch, requests.ConnectionError("boom"))
        assert validate_credentials("ss-key") == (False, "Could not validate Simplesat API key")

    def test_probe_disables_redirects_to_protect_api_key(self) -> None:
        # The X-Simplesat-Token header rides on the probe; the session must be built with redirects
        # pinned off so a redirect can't replay the key to the redirect target during validation.
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=200)
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.simplesat.simplesat.make_tracked_session",
            return_value=session,
        ) as make_session:
            validate_credentials("ss-key")
        assert make_session.call_args.kwargs["allow_redirects"] is False


class TestSimplesatSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in SIMPLESAT_ENDPOINTS.values())
        assert set(SIMPLESAT_ENDPOINTS) == set(ENDPOINTS)

    def test_list_key_matches_endpoint_name(self) -> None:
        assert all(config.list_key == config.name for config in SIMPLESAT_ENDPOINTS.values())
