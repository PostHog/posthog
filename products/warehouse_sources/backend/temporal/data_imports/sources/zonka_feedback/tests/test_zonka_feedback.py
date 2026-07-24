import json
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.zonka_feedback import zonka_feedback
from products.warehouse_sources.backend.temporal.data_imports.sources.zonka_feedback.settings import (
    ENDPOINTS,
    ZONKA_FEEDBACK_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zonka_feedback.zonka_feedback import (
    PAGE_SIZE,
    ZonkaFeedbackResumeConfig,
    base_url,
    check_access,
    zonka_feedback_source,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def _response(items: list[dict[str, Any]] | None, *, drop_result: bool = False, status: int = 200) -> Response:
    body: dict[str, Any] = {}
    if not drop_result:
        body["result"] = items or []
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    return resp


def _redirect(location: str = "https://evil.example.com/") -> Response:
    resp = Response()
    resp.status_code = 302
    resp.headers["Location"] = location
    resp._content = b"{}"
    return resp


def _make_manager(resume_state: ZonkaFeedbackResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list capturing each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead. The prepared
    request keeps the real request URL so the client's allowed-host pin sees the true host.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(manager: mock.MagicMock, endpoint: str = "responses", data_center: str = "us1"):
    return zonka_feedback_source(
        auth_token="zonka-token",
        data_center=data_center,
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_then_empty_page_stops(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 1}, {"id": 2}]), _response([])])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == [{"id": 1}, {"id": 2}]
        assert params[0]["page"] == 1
        assert params[0]["page_size"] == PAGE_SIZE
        assert params[1]["page"] == 2
        # State is saved after page 1 (pointing at page 2); the terminating empty page saves nothing.
        assert [c.args[0].next_page for c in manager.save_state.call_args_list] == [2]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_pagination_until_empty_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}]), _response([{"id": 2}]), _response([{"id": 3}]), _response([])])

        rows = _rows(_source(_make_manager()))
        assert rows == [{"id": 1}, {"id": 2}, {"id": 3}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_next_page_after_yielding_each_batch(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}]), _response([{"id": 2}]), _response([])])

        manager = _make_manager()
        _rows(_source(manager))
        assert [c.args[0].next_page for c in manager.save_state.call_args_list] == [2, 3]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        # Page 1 must never be fetched on resume — only pages from the saved bookmark onward.
        params = _wire(session, [_response([{"id": 2}]), _response([])])

        manager = _make_manager(ZonkaFeedbackResumeConfig(next_page=2))
        rows = _rows(_source(manager))

        assert rows == [{"id": 2}]
        assert params[0]["page"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_first_page_empty_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        manager = _make_manager()
        rows = _rows(_source(manager))
        assert rows == []
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_result_key_raises_loudly(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(None, drop_result=True)])

        # A 200 body without "result" means the response shape changed — fail loud, not silently 0 rows.
        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_source(_make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_auth_failure_fails_loud(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], status=401)])

        # An invalid/revoked token surfaces as a permanent HTTPError; retrying can't fix credentials.
        with pytest.raises(requests.HTTPError):
            _rows(_source(_make_manager()))


class TestSessionSecurity:
    """Credentialed requests must reject a 3xx so a redirect from a compromised host can't retarget
    the bearer token at another origin (the source pins the client with allow_redirects=False)."""

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_redirect_is_rejected(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_redirect()])

        with pytest.raises(ValueError, match="refusing to follow"):
            _rows(_source(_make_manager()))


class TestBaseUrl:
    @parameterized.expand(
        [
            ("us", "us1", "https://us1.apis.zonkafeedback.com"),
            ("eu", "e", "https://e.apis.zonkafeedback.com"),
            ("in", "in", "https://in.apis.zonkafeedback.com"),
        ]
    )
    def test_base_url_per_data_center(self, _name: str, data_center: str, expected: str) -> None:
        assert base_url(data_center) == expected

    @parameterized.expand(
        [
            ("path_delimiter", "us1/evil.com"),
            ("fragment", "us1#@evil.com"),
            ("userinfo", "us1@evil.com"),
            ("unknown_region", "au"),
            ("empty", ""),
        ]
    )
    def test_base_url_rejects_unlisted_data_center(self, _name: str, data_center: str) -> None:
        # A `data_center` outside the allowlist could otherwise retarget the credentialed request at
        # an attacker host and leak the bearer token.
        with pytest.raises(ValueError, match="Unknown Zonka Feedback data center"):
            base_url(data_center)


class TestCheckAccess:
    @parameterized.expand(
        [
            ("reachable", 200, 200, None),
            ("unauthorized", 401, 401, None),
            ("forbidden", 403, 403, None),
            ("server_error", 500, 500, "Zonka Feedback returned HTTP 500"),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_status: int, expected_message: str | None) -> None:
        response = mock.MagicMock()
        response.status_code = status
        session = mock.MagicMock()
        session.get.return_value = response
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(zonka_feedback, "make_tracked_session", lambda **kwargs: session)
            assert check_access("zonka-token", "us1") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self, monkeypatch: Any) -> None:
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        monkeypatch.setattr(zonka_feedback, "make_tracked_session", lambda **kwargs: session)
        status, message = check_access("zonka-token", "us1")
        assert status == 0
        assert message == "Could not connect to Zonka Feedback"

    def test_probe_redacts_token_and_pins_redirects(self, monkeypatch: Any) -> None:
        response = mock.MagicMock()
        response.status_code = 200
        session = mock.MagicMock()
        session.get.return_value = response
        make_session = mock.MagicMock(return_value=session)
        monkeypatch.setattr(zonka_feedback, "make_tracked_session", make_session)

        check_access("secret-token", "us1")
        assert make_session.call_args.kwargs["redact_values"] == ("secret-token",)
        assert make_session.call_args.kwargs["allow_redirects"] is False


class TestZonkaFeedbackSourceResponse:
    @parameterized.expand([("responses",), ("surveys",), ("contacts",)])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _source(_make_manager(), endpoint=endpoint)
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # No endpoint exposes a stable creation timestamp we can safely partition on.
        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in ZONKA_FEEDBACK_ENDPOINTS.values())
        assert set(ZONKA_FEEDBACK_ENDPOINTS) == set(ENDPOINTS)
