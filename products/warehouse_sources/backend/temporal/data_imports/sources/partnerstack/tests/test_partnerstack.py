import json
import base64
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerstack.partnerstack import (
    PAGE_SIZE,
    PartnerStackResumeConfig,
    partnerstack_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerstack.settings import (
    ENDPOINTS,
    PARTNERSTACK_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the partnerstack module.
PARTNERSTACK_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.partnerstack.partnerstack.make_tracked_session"
)
# The retry backoff sleeps between attempts; zero it so failure-path tests don't wait.
RETRY_WAIT_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client._retry_wait_seconds"


def _response(
    items: list[dict[str, Any]] | None = None, *, has_more: bool = False, body: Any = "__default__"
) -> Response:
    if body == "__default__":
        body = {"data": {"items": items or [], "has_more": has_more}}
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    resp.url = "https://api.partnerstack.com/api/v2/partnerships"
    return resp


def _error_response(status: int) -> Response:
    resp = Response()
    resp.status_code = status
    resp.reason = "Error"
    resp._content = json.dumps({"error": "nope"}).encode()
    resp.url = "https://api.partnerstack.com/api/v2/partnerships"
    return resp


def _make_manager(resume_state: PartnerStackResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Wire a mock session; return (param_snapshots, header_snapshots) captured AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead. Headers are
    captured by really preparing the request through a throwaway session so the auth is applied.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []
    header_snapshots: list[dict[str, str]] = []
    real_session = requests.Session()

    def _prepare(request: Any) -> Any:
        param_snapshots.append(dict(request.params or {}))
        prepared = real_session.prepare_request(request)
        header_snapshots.append(dict(prepared.headers))
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots, header_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(manager: mock.MagicMock, endpoint: str = "partnerships"):
    return partnerstack_source(
        public_key="pub",
        private_key="priv",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_no_more_yields_and_stops(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(session, [_response([{"key": "a"}, {"key": "b"}], has_more=False)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == [{"key": "a"}, {"key": "b"}]
        assert session.send.call_count == 1
        # has_more is false, so we stop without persisting resume state.
        manager.save_state.assert_not_called()
        # First page omits the cursor and carries the page size.
        assert params[0] == {"limit": PAGE_SIZE}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_cursor_until_has_more_false(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(
            session,
            [_response([{"key": "a"}, {"key": "b"}], has_more=True), _response([{"key": "c"}], has_more=False)],
        )

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == [{"key": "a"}, {"key": "b"}, {"key": "c"}]
        # The second request advances the cursor to the last key of the first page.
        assert params[1]["starting_after"] == "b"
        assert params[1]["limit"] == PAGE_SIZE
        # State is saved once, after the first page (cursor "b"); the final page persists nothing.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == PartnerStackResumeConfig(starting_after="b")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(session, [_response([{"key": "c"}], has_more=False)])

        manager = _make_manager(PartnerStackResumeConfig(starting_after="b"))
        rows = _rows(_source(manager))

        # The initial (cursor-less) page is never fetched on resume; the first request seeds the cursor.
        assert rows == [{"key": "c"}]
        assert session.send.call_count == 1
        assert params[0]["starting_after"] == "b"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], has_more=False)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == []
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_when_last_object_missing_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        # has_more is true but the last object has no `key`, so we can't advance and must stop.
        _wire(session, [_response([{"no_key": 1}], has_more=True)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == [{"no_key": 1}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_has_more_defaults_to_false(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(body={"data": {"items": [{"key": "a"}]}})])

        manager = _make_manager()
        rows = _rows(_source(manager))

        # No has_more flag means the collection ended after this page.
        assert rows == [{"key": "a"}]
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_basic_auth_and_accept_headers(self, MockSession) -> None:
        session = MockSession.return_value
        _, headers = _wire(session, [_response([{"key": "a"}])])

        _rows(_source(_make_manager()))

        expected = base64.b64encode(b"pub:priv").decode("ascii")
        assert headers[0]["Authorization"] == f"Basic {expected}"
        # The non-secret Accept header is applied to the session by the client.
        assert session.headers.get("Accept") == "application/json"


class TestRetryAndFailure:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch(RETRY_WAIT_PATCH, return_value=0)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_retry_then_raise(self, _name: str, status: int, MockSession, _wait) -> None:
        session = MockSession.return_value
        _wire(session, [_error_response(status)] * 5)

        with pytest.raises(RESTClientRetryableError):
            _rows(_source(_make_manager()))
        # Retried up to the client's attempt cap before giving up.
        assert session.send.call_count == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_raise_for_status_without_retry(self, _name: str, status: int, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_error_response(status)])

        with pytest.raises(requests.HTTPError):
            _rows(_source(_make_manager()))
        assert session.send.call_count == 1

    @parameterized.expand(
        [
            ("bare_list", [{"key": "a"}]),
            ("missing_data", {"items": []}),
            ("data_not_dict", {"data": []}),
            ("non_list_items", {"data": {"items": "nope", "has_more": False}}),
        ]
    )
    @mock.patch(RETRY_WAIT_PATCH, return_value=0)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unexpected_envelope_is_retried_then_raises(self, _name: str, body: Any, MockSession, _wait) -> None:
        session = MockSession.return_value
        _wire(session, [_response(body=body)] * 5)

        # An unexpected 200 body shape is treated as transient: retried, then raised.
        with pytest.raises(RESTClientRetryableError):
            _rows(_source(_make_manager()))
        assert session.send.call_count == 5


class TestValidateCredentials:
    @staticmethod
    def _session(response: Any) -> mock.MagicMock:
        session = mock.MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        return session

    @parameterized.expand(
        [
            (200, None),
            (401, "Invalid PartnerStack API keys"),
            (403, "Invalid PartnerStack API keys"),
            (500, "PartnerStack returned HTTP 500"),
        ]
    )
    def test_status_to_message(self, status: int, expected_message: str | None) -> None:
        response = mock.MagicMock(status_code=status)
        session = self._session(response)
        with mock.patch(PARTNERSTACK_SESSION_PATCH, lambda **kwargs: session):
            valid, message = validate_credentials("pub", "priv")
        assert valid is (status == 200)
        assert message == expected_message

    def test_connection_error_is_not_validated_with_message(self) -> None:
        session = self._session(requests.ConnectionError("boom"))
        with mock.patch(PARTNERSTACK_SESSION_PATCH, lambda **kwargs: session):
            valid, message = validate_credentials("pub", "priv")
        assert valid is False
        assert message is not None


class TestSourceResponseShape:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(self, endpoint: str, MockSession) -> None:
        response = _source(_make_manager(), endpoint=endpoint)
        assert response.name == endpoint
        assert response.primary_keys == ["key"]
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_key_primary_key(self) -> None:
        assert all(config.primary_keys == ["key"] for config in PARTNERSTACK_ENDPOINTS.values())
        assert set(PARTNERSTACK_ENDPOINTS) == set(ENDPOINTS)
