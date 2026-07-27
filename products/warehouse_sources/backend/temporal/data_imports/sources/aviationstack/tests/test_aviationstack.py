import json
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.aviationstack import aviationstack
from products.warehouse_sources.backend.temporal.data_imports.sources.aviationstack.aviationstack import (
    AviationstackResumeConfig,
    aviationstack_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aviationstack.settings import (
    AVIATIONSTACK_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the aviationstack module.
AVIATIONSTACK_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.aviationstack.aviationstack.make_tracked_session"
)


def _page(data: list[dict[str, Any]] | None, *, total: int | None = None, drop_data: bool = False) -> Response:
    body: dict[str, Any] = {"pagination": {"limit": 100, "offset": 0, "count": len(data or []), "total": total}}
    if not drop_data:
        body["data"] = data or []
    return _response(body)


def _error_body(code: str) -> Response:
    # aviationstack signals API-level errors with an HTTP 200 body envelope.
    return _response({"error": {"code": code, "message": "boom"}})


def _response(body: Any, *, status: int = 200, reason: str = "OK") -> Response:
    resp = Response()
    resp.status_code = status
    resp.reason = reason
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    resp.url = "https://api.aviationstack.com/v1/airlines?access_key=supersecret&offset=0&limit=100"
    return resp


def _make_manager(resume_state: AviationstackResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and snapshot each request's params AT SEND TIME.

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


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str = "airlines", manager: mock.MagicMock | None = None) -> Any:
    return aviationstack_source(
        "supersecret", endpoint, team_id=1, job_id="j", resumable_source_manager=manager or _make_manager()
    )


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_total_reached(self, MockSession) -> None:
        session = MockSession.return_value
        page1 = [{"id": i} for i in range(100)]
        page2 = [{"id": i} for i in range(100, 200)]
        params = _wire(session, [_page(page1, total=200), _page(page2, total=200)])

        rows = _rows(_source())

        assert [r["id"] for r in rows] == list(range(200))
        assert params[0]["offset"] == 0
        assert params[0]["limit"] == 100
        assert params[1]["offset"] == 100
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_short_page(self, MockSession) -> None:
        # A page shorter than the limit means there's no further page, even without a total.
        session = MockSession.return_value
        _wire(session, [_page([{"id": 1}], total=None)])

        rows = _rows(_source())

        assert [r["id"] for r in rows] == [1]
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_empty_first_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([], total=0)])

        rows = _rows(_source())

        assert rows == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page([{"id": 9}], total=None)])

        _rows(_source(manager=_make_manager(AviationstackResumeConfig(next_offset=200))))

        # The first (and only) request must start from the persisted offset, not 0.
        assert params[0]["offset"] == 200

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_state_after_yielding_a_page(self, MockSession) -> None:
        session = MockSession.return_value
        page1 = [{"id": i} for i in range(100)]
        page2 = [{"id": i} for i in range(100, 200)]
        _wire(session, [_page(page1, total=200), _page(page2, total=200)])

        manager = _make_manager()
        _rows(_source(manager=manager))

        # State saved once, with the next offset to resume from, only while more pages remain.
        manager.save_state.assert_called_once_with(AviationstackResumeConfig(next_offset=100))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_page_saves_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([{"id": 1}], total=None)])

        manager = _make_manager()
        _rows(_source(manager=manager))

        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_raises_loudly(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page(None, drop_data=True)])

        # A 200 body without "data" (an unrecognized error envelope or changed shape) fails loud
        # rather than silently syncing 0 rows.
        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_source())


class TestBodyErrorEnvelope:
    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_permanent_body_code_raises_and_hides_secret(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_error_body("invalid_access_key")])

        with pytest.raises(ValueError) as exc:
            _rows(_source())

        # The stable [code] token is what get_non_retryable_errors matches on.
        assert "[invalid_access_key]" in str(exc.value)
        # The access_key secret value must never leak into the user-visible error.
        assert "supersecret" not in str(exc.value)
        # Permanent: raised on the first response, never retried.
        assert session.send.call_count == 1

    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_rate_limit_body_code_is_retryable(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        session.headers = {}
        session.prepare_request.return_value = mock.MagicMock()
        session.send.return_value = _error_body("rate_limit_reached")

        with pytest.raises(RESTClientRetryableError):
            _rows(_source())
        # Retried up to the client's default attempt cap, then re-raised.
        assert session.send.call_count == 5


class TestHttpErrors:
    @parameterized.expand([("unauthorized", 401, "401"), ("forbidden", 403, "403")])
    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_hard_auth_status_raises_without_leaking_secret(
        self, _name: str, status: int, expected: str, MockSession, _sleep
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"data": [], "pagination": {}}, status=status, reason=expected)])

        with pytest.raises(ValueError) as exc:
            _rows(_source())

        assert expected in str(exc.value)
        assert "supersecret" not in str(exc.value)
        assert "access_key" not in str(exc.value)
        # Permanent credential/plan problem — not retried.
        assert session.send.call_count == 1

    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_retries_then_raises(self, _name: str, status: int, MockSession, _sleep) -> None:
        session = MockSession.return_value
        session.headers = {}
        session.prepare_request.return_value = mock.MagicMock()
        session.send.return_value = _response({}, status=status, reason="err")

        with pytest.raises(RESTClientRetryableError):
            _rows(_source())
        assert session.send.call_count == 5


class TestSourceResponse:
    @parameterized.expand(
        [
            ("airlines", ["id"]),
            ("airports", ["id"]),
            ("countries", ["id"]),
            ("flights", None),
            ("routes", None),
        ]
    )
    def test_primary_keys(self, endpoint: str, expected_keys: list[str] | None) -> None:
        response = _source(endpoint)
        assert response.name == endpoint
        assert response.primary_keys == expected_keys

    def test_every_endpoint_builds_a_source_response(self) -> None:
        for endpoint in AVIATIONSTACK_ENDPOINTS:
            response = _source(endpoint)
            assert response.name == endpoint
            assert callable(response.items)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, {"data": []}, True),
            ("unauthorized", 401, {"error": {"code": "invalid_access_key"}}, False),
            ("ok_status_but_error_body", 200, {"error": {"code": "usage_limit_reached"}}, False),
        ]
    )
    def test_status_and_body_mapping(self, _name: str, status: int, body: dict, expected: bool) -> None:
        response = mock.MagicMock()
        response.status_code = status
        response.json.return_value = body
        session = mock.MagicMock()
        session.get.return_value = response
        with mock.patch(AVIATIONSTACK_SESSION_PATCH, return_value=session):
            assert validate_credentials("k") is expected

    def test_handles_network_error(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with mock.patch(AVIATIONSTACK_SESSION_PATCH, return_value=session):
            assert validate_credentials("k") is False


def test_module_exposes_base_url() -> None:
    assert aviationstack.AVIATIONSTACK_BASE_URL == "https://api.aviationstack.com/v1"
