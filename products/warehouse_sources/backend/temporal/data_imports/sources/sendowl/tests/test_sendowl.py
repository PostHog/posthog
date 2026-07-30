import json
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sendowl.sendowl import (
    PER_PAGE,
    SendowlResumeConfig,
    check_access,
    sendowl_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sendowl.settings import (
    ENDPOINTS,
    SENDOWL_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# check_access builds its own tracked session in the sendowl module.
SENDOWL_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.sendowl.sendowl.make_tracked_session"
)
# Retryable paths sleep between tenacity attempts; patch the clock so failure-path tests stay fast.
SLEEP_PATCH = "tenacity.nap.time.sleep"


def _wrapped(wrapper_key: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # SendOwl returns each list item under a single-key wrapper, e.g. `{"product": {...}}`.
    return [{wrapper_key: row} for row in rows]


def _page(wrapper_key: str, rows: list[dict[str, Any]]) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(_wrapped(wrapper_key, rows)).encode()
    resp.url = "https://www.sendowl.com/api/v1/products"
    return resp


def _body_response(status: int, body: Any) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    resp.url = "https://www.sendowl.com/api/v1/products"
    resp.reason = "Error"
    return resp


def _make_manager(resume_state: SendowlResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, send_side_effect: Any) -> list[dict[str, Any]]:
    """Wire a mock session, snapshotting each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    ``send_side_effect`` is a list of responses or a callable (for the retry paths).
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = send_side_effect
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock):
    return sendowl_source(
        api_key="sendowl-key",
        api_secret="sendowl-secret",
        endpoint=endpoint,
        team_id=1,
        job_id="job-1",
        resumable_source_manager=manager,
    )


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unwraps_wrapper_and_sends_page_and_per_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page("product", [{"id": 1, "name": "Ebook"}, {"id": 2, "name": "Course"}])])

        rows = _rows(_source("products", _make_manager()))

        # Each single-key wrapper object is unwrapped to the flat record.
        assert rows == [{"id": 1, "name": "Ebook"}, {"id": 2, "name": "Course"}]
        assert params[0]["page"] == 1
        assert params[0]["per_page"] == PER_PAGE

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_short_page_and_checkpoints(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"id": i} for i in range(PER_PAGE)]
        params = _wire(session, [_page("product", full_page), _page("product", [{"id": 999}])])

        manager = _make_manager()
        rows = _rows(_source("products", manager))

        assert rows == [*full_page, {"id": 999}]
        assert params[0]["page"] == 1
        assert params[1]["page"] == 2
        # State saved after the full page 1 (points at page 2); the short final page saves nothing.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == SendowlResumeConfig(next_page=2)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_first_page_makes_one_request_and_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page("product", [{"id": 1}, {"id": 2}])])

        manager = _make_manager()
        rows = _rows(_source("products", manager))

        assert rows == [{"id": 1}, {"id": 2}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_yields_no_rows_and_stops(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page("product", [])])

        manager = _make_manager()
        assert _rows(_source("products", manager)) == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"id": i} for i in range(PER_PAGE)]
        params = _wire(session, [_page("product", full_page), _page("product", [{"id": 7}])])

        manager = _make_manager(SendowlResumeConfig(next_page=2))
        rows = _rows(_source("products", manager))

        # Page 1 must never be fetched on resume; the first request targets the saved page.
        assert params[0]["page"] == 2
        assert rows == [*full_page, {"id": 7}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_orders_endpoint_uses_its_wrapper_key(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page("order", [{"id": 10}])])

        rows = _rows(_source("orders", _make_manager()))
        assert rows == [{"id": 10}]


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_retry_then_raise(self, _name: str, status: int, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, lambda *a, **k: _body_response(status, {}))

        with mock.patch(SLEEP_PATCH), pytest.raises(RESTClientRetryableError):
            _rows(_source("products", _make_manager()))
        # DEFAULT_RETRY_ATTEMPTS attempts are made before the retryable error is reraised.
        assert session.send.call_count == 5

    @parameterized.expand([("dict_body", {"error": "unexpected"}), ("bare_string", "nope")])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_is_retryable(self, _name: str, body: Any, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, lambda *a, **k: _body_response(200, body))

        with mock.patch(SLEEP_PATCH), pytest.raises(RESTClientRetryableError):
            _rows(_source("products", _make_manager()))
        assert session.send.call_count == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_raise_immediately(self, _name: str, status: int, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_body_response(status, [])])

        with pytest.raises(requests.HTTPError):
            _rows(_source("products", _make_manager()))
        # A non-retryable client error is not retried.
        assert session.send.call_count == 1


class TestCheckAccess:
    def _patch_session(self, mp: Any, response: Any) -> mock.MagicMock:
        session = mock.MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        mp.setattr(
            "products.warehouse_sources.backend.temporal.data_imports.sources.sendowl.sendowl.make_tracked_session",
            lambda **kwargs: session,
        )
        return session

    @parameterized.expand(
        [
            ("reachable", 200, 200, None),
            ("unauthorized", 401, 401, None),
            ("forbidden", 403, 403, None),
            ("server_error", 500, 500, "SendOwl returned HTTP 500"),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_status: int, expected_message: str | None) -> None:
        response = mock.MagicMock(status_code=status)
        with pytest.MonkeyPatch.context() as mp:
            self._patch_session(mp, response)
            assert check_access("sendowl-key", "sendowl-secret") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self, monkeypatch: Any) -> None:
        # validate_via_probe swallows the transport error, so the probe reports "not validated".
        self._patch_session(monkeypatch, requests.ConnectionError("boom"))
        assert check_access("sendowl-key", "sendowl-secret") == (0, "Could not connect to SendOwl")

    def test_probe_uses_basic_auth_and_products_path(self, monkeypatch: Any) -> None:
        session = self._patch_session(monkeypatch, mock.MagicMock(status_code=200))
        check_access("sendowl-key", "sendowl-secret")
        args, kwargs = session.get.call_args
        assert args[0] == "https://www.sendowl.com/api/v1/products?page=1&per_page=1"
        assert isinstance(kwargs["auth"], requests.auth.HTTPBasicAuth)
        assert kwargs["auth"].username == "sendowl-key"
        assert kwargs["auth"].password == "sendowl-secret"


class TestSendowlSourceResponse:
    @parameterized.expand([("products",), ("orders",), ("subscriptions",), ("discount_codes",)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_response_uses_id_primary_key(self, endpoint: str, MockSession) -> None:
        MockSession.return_value.headers = {}
        response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in SENDOWL_ENDPOINTS.values())
        assert set(SENDOWL_ENDPOINTS) == set(ENDPOINTS)
