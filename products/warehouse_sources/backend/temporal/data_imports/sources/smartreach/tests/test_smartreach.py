import json
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.smartreach.settings import (
    ENDPOINTS,
    SMARTREACH_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartreach.smartreach import (
    SMARTREACH_BASE_URL,
    SmartreachResumeConfig,
    check_access,
    smartreach_source,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# check_access builds its own tracked session in the smartreach module.
SMARTREACH_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.smartreach.smartreach.make_tracked_session"
)


def _response(rows: list[dict[str, Any]] | None, data_key: str, next_url: str | None, status: int = 200) -> Response:
    body: dict[str, Any] = {"data": {data_key: rows if rows is not None else []}, "links": {"next": next_url}}
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    resp.url = f"{SMARTREACH_BASE_URL}/prospects"
    return resp


def _make_manager(resume_state: SmartreachResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[str]:
    """Wire a mock session and return a list that captures each request's URL AT SEND TIME.

    The paginator rewrites ``request.url`` in place across pages, so snapshot it as each request is
    prepared. The prepared request must expose a real ``url`` string because the client's host-pinning
    guard (``allowed_hosts``) runs on ``prepared.url`` before every send.
    """
    session.headers = {}
    url_snapshots: list[str] = []

    def _prepare(request: Any) -> mock.MagicMock:
        url_snapshots.append(request.url)
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return url_snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(manager: mock.MagicMock, endpoint: str = "prospects") -> Any:
    return smartreach_source(
        api_key="uk_test",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_yields_rows_and_stops(self, MockSession: Any) -> None:
        session = MockSession.return_value
        urls = _wire(session, [_response([{"id": 1}, {"id": 2}], "prospects", next_url=None)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == [{"id": 1}, {"id": 2}]
        assert urls == [f"{SMARTREACH_BASE_URL}/prospects"]
        # No further pages, so no resume state is persisted.
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_links_next_until_null(self, MockSession: Any) -> None:
        session = MockSession.return_value
        p2 = f"{SMARTREACH_BASE_URL}/prospects?cursor=abc"
        p3 = f"{SMARTREACH_BASE_URL}/prospects?cursor=def"
        urls = _wire(
            session,
            [
                _response([{"id": 1}], "prospects", next_url=p2),
                _response([{"id": 2}], "prospects", next_url=p3),
                _response([{"id": 3}], "prospects", next_url=None),
            ],
        )

        rows = _rows(_source(_make_manager()))

        assert rows == [{"id": 1}, {"id": 2}, {"id": 3}]
        # The follow-up requests hit the verbatim links.next URLs.
        assert urls == [f"{SMARTREACH_BASE_URL}/prospects", p2, p3]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_next_url_after_yielding_each_batch(self, MockSession: Any) -> None:
        session = MockSession.return_value
        p2 = f"{SMARTREACH_BASE_URL}/prospects?cursor=abc"
        _wire(
            session,
            [
                _response([{"id": 1}], "prospects", next_url=p2),
                _response([{"id": 2}], "prospects", next_url=None),
            ],
        )

        manager = _make_manager()
        _rows(_source(manager))

        # State is saved AFTER page 1 is yielded (pointing at the next URL), never for the final page.
        manager.save_state.assert_called_once_with(SmartreachResumeConfig(next_url=p2))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor_url(self, MockSession: Any) -> None:
        session = MockSession.return_value
        p2 = f"{SMARTREACH_BASE_URL}/prospects?cursor=abc"
        p3 = f"{SMARTREACH_BASE_URL}/prospects?cursor=def"
        urls = _wire(
            session,
            [
                _response([{"id": 2}], "prospects", next_url=p3),
                _response([{"id": 3}], "prospects", next_url=None),
            ],
        )

        manager = _make_manager(SmartreachResumeConfig(next_url=p2))
        rows = _rows(_source(manager))

        assert rows == [{"id": 2}, {"id": 3}]
        # The first-page URL is never fetched on resume — the run starts at the saved cursor.
        assert urls == [p2, p3]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_yields_no_rows(self, MockSession: Any) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], "prospects", next_url=None)])

        rows = _rows(_source(_make_manager()))
        assert rows == []

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_reads_rows_from_endpoint_specific_data_key(self, MockSession: Any) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 9}], "campaigns", next_url=None)])

        rows = _rows(_source(_make_manager(), endpoint="campaigns"))
        assert rows == [{"id": 9}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_yields_empty_page(self, MockSession: Any) -> None:
        session = MockSession.return_value
        # A body without the endpoint's data key is tolerated as an empty page (not a hard error).
        resp = Response()
        resp.status_code = 200
        resp._content = json.dumps({"data": {"other": []}, "links": {"next": None}}).encode()
        resp.url = f"{SMARTREACH_BASE_URL}/prospects"
        _wire(session, [resp])

        assert _rows(_source(_make_manager())) == []


class TestSSRFHostPinning:
    @parameterized.expand(
        [
            ("other_host", "https://evil.example.com/api/v1/prospects"),
            ("subdomain_spoof", "https://api.smartreach.io.evil.com/api/v1/prospects"),
            ("http_downgrade", "http://api.smartreach.io/api/v1/prospects"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_off_origin_next_url_is_rejected(self, _name: str, bad_next: str, MockSession: Any) -> None:
        # Following an off-origin (or scheme-downgraded) cursor would send the user's API key to a host
        # other than SmartReach's own https origin — reject it before the request leaves the process.
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}], "prospects", next_url=bad_next)])

        with pytest.raises(ValueError):
            _rows(_source(_make_manager()))


class TestRetryAndFailLoud:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_transient_5xx_is_retried_then_succeeds(self, MockSession: Any) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(None, "prospects", next_url=None, status=500),
                _response([{"id": 1}], "prospects", next_url=None, status=200),
            ],
        )

        rows = _rows(_source(_make_manager()))
        assert rows == [{"id": 1}]
        assert session.send.call_count == 2

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_fail_loud(self, _name: str, status: int, MockSession: Any) -> None:
        session = MockSession.return_value
        _wire(session, [_response(None, "prospects", next_url=None, status=status)])

        with pytest.raises(requests.HTTPError):
            _rows(_source(_make_manager()))


class TestCheckAccess:
    def _patch_session(self, response: Any) -> Any:
        session = mock.MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        return mock.patch(SMARTREACH_SESSION_PATCH, return_value=session)

    @pytest.mark.parametrize(
        "status, expected_status, expected_message",
        [
            (200, 200, None),
            (401, 401, None),
            (403, 403, None),
            (500, 500, "SmartReach returned HTTP 500"),
        ],
    )
    def test_status_mapping(self, status: int, expected_status: int, expected_message: str | None) -> None:
        response = mock.MagicMock()
        response.status_code = status
        with self._patch_session(response):
            assert check_access("uk_test") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self) -> None:
        with self._patch_session(requests.ConnectionError("boom")):
            status, message = check_access("uk_test")
        assert status == 0
        assert message == "Could not connect to SmartReach"

    def test_probes_campaigns_endpoint(self) -> None:
        response = mock.MagicMock()
        response.status_code = 200
        with self._patch_session(response) as patched:
            check_access("uk_test")
        session = patched.return_value
        assert session.get.call_args.args[0] == f"{SMARTREACH_BASE_URL}/campaigns"


class TestSmartreachSourceResponse:
    @parameterized.expand([("prospects",), ("campaigns",)])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _source(_make_manager(), endpoint=endpoint)
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Full refresh only: no datetime partitioning is configured.
        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in SMARTREACH_ENDPOINTS.values())
        assert set(SMARTREACH_ENDPOINTS) == set(ENDPOINTS)
