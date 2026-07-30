import json
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.zenloop import zenloop
from products.warehouse_sources.backend.temporal.data_imports.sources.zenloop.settings import (
    ENDPOINTS,
    ZENLOOP_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zenloop.zenloop import (
    ZenloopResumeConfig,
    check_access,
    zenloop_source,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# Where tenacity sleeps between retries — patch so retryable-path tests don't actually wait.
SLEEP_PATCH = "tenacity.nap.time.sleep"


def _response(
    items: list[dict[str, Any]] | None,
    *,
    response_key: str = "surveys",
    status: int = 200,
    drop_key: bool = False,
) -> Response:
    body: dict[str, Any] = {"meta": {"per_page": zenloop.PER_PAGE}}
    if not drop_key:
        body[response_key] = items or []
    resp = Response()
    resp.status_code = status
    resp.url = f"{zenloop.ZENLOOP_BASE_URL}/surveys?page=1&per_page=50"
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: ZenloopResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so snapshot a copy when each
    request is prepared instead of inspecting the shared dict after the run.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_short_page_yields_items_and_stops(self, MockSession, monkeypatch) -> None:
        monkeypatch.setattr(zenloop, "PER_PAGE", 2)
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}])])

        manager = _make_manager()
        rows = _rows(zenloop_source("token", "surveys", team_id=1, job_id="j", resumable_source_manager=manager))

        assert rows == [{"id": 1}]
        assert session.send.call_count == 1
        # Page shorter than PER_PAGE, so no resume state is persisted.
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_pagination_until_short_page(self, MockSession, monkeypatch) -> None:
        monkeypatch.setattr(zenloop, "PER_PAGE", 2)
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response([{"id": 1}, {"id": 2}]),
                _response([{"id": 3}, {"id": 4}]),
                _response([{"id": 5}]),
            ],
        )

        manager = _make_manager()
        rows = _rows(zenloop_source("token", "surveys", team_id=1, job_id="j", resumable_source_manager=manager))

        assert [r["id"] for r in rows] == [1, 2, 3, 4, 5]
        # The short third page ends the sync with no extra empty-page request.
        assert session.send.call_count == 3
        assert params[0]["page"] == 1
        assert params[0]["per_page"] == 2
        assert params[1]["page"] == 2
        assert params[2]["page"] == 3

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_next_page_after_each_full_batch_only(self, MockSession, monkeypatch) -> None:
        monkeypatch.setattr(zenloop, "PER_PAGE", 2)
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}, {"id": 2}]), _response([{"id": 3}])])

        manager = _make_manager()
        _rows(zenloop_source("token", "surveys", team_id=1, job_id="j", resumable_source_manager=manager))

        # State saved AFTER the full page 1 (pointing at page 2), never for the final short page.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [ZenloopResumeConfig(next_page=2)]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession, monkeypatch) -> None:
        monkeypatch.setattr(zenloop, "PER_PAGE", 2)
        session = MockSession.return_value
        # Page 1 must never be fetched on resume.
        params = _wire(session, [_response([{"id": 3}, {"id": 4}]), _response([{"id": 5}])])

        manager = _make_manager(ZenloopResumeConfig(next_page=2))
        rows = _rows(zenloop_source("token", "surveys", team_id=1, job_id="j", resumable_source_manager=manager))

        assert [r["id"] for r in rows] == [3, 4, 5]
        assert params[0]["page"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_no_rows(self, MockSession, monkeypatch) -> None:
        monkeypatch.setattr(zenloop, "PER_PAGE", 2)
        session = MockSession.return_value
        _wire(session, [_response([])])

        manager = _make_manager()
        rows = _rows(zenloop_source("token", "surveys", team_id=1, job_id="j", resumable_source_manager=manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_selects_rows_under_endpoint_named_key(self, MockSession, monkeypatch) -> None:
        monkeypatch.setattr(zenloop, "PER_PAGE", 2)
        session = MockSession.return_value
        _wire(session, [_response([{"id": 9}], response_key="properties")])

        manager = _make_manager()
        rows = _rows(zenloop_source("token", "properties", team_id=1, job_id="j", resumable_source_manager=manager))

        assert rows == [{"id": 9}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_raises_loudly(self, MockSession, monkeypatch) -> None:
        monkeypatch.setattr(zenloop, "PER_PAGE", 2)
        session = MockSession.return_value
        _wire(session, [_response(None, drop_key=True)])

        manager = _make_manager()
        # A 200 body without the endpoint's named key means the response shape changed — fail loud
        # rather than silently syncing 0 rows.
        with pytest.raises(ValueError, match="matched nothing"):
            _rows(zenloop_source("token", "surveys", team_id=1, job_id="j", resumable_source_manager=manager))


class TestRetryAndErrors:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch(CLIENT_SESSION_PATCH)
    @mock.patch(SLEEP_PATCH)
    def test_retryable_status_is_retried_then_succeeds(self, _name: str, status: int, _mock_sleep, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}], status=status), _response([{"id": 1}])])

        manager = _make_manager()
        rows = _rows(zenloop_source("token", "surveys", team_id=1, job_id="j", resumable_source_manager=manager))

        # The transient error is retried and the reissued request succeeds.
        assert rows == [{"id": 1}]
        assert session.send.call_count == 2

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(CLIENT_SESSION_PATCH)
    @mock.patch(SLEEP_PATCH)
    def test_client_errors_raise_http_error(self, _name: str, status: int, _mock_sleep, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}], status=status)] * 6)

        manager = _make_manager()
        with pytest.raises(HTTPError):
            _rows(zenloop_source("token", "surveys", team_id=1, job_id="j", resumable_source_manager=manager))


class TestCheckAccess:
    def _patch_session(self, monkeypatch: Any, response: Any) -> mock.MagicMock:
        session = mock.MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        monkeypatch.setattr(zenloop, "make_tracked_session", lambda **kwargs: session)
        return session

    @pytest.mark.parametrize(
        "status, expected_status, expected_message",
        [
            (200, 200, None),
            (401, 401, None),
            (403, 403, None),
            (500, 500, "Zenloop returned HTTP 500"),
        ],
    )
    def test_status_mapping(
        self, status: int, expected_status: int, expected_message: str | None, monkeypatch: Any
    ) -> None:
        response = mock.MagicMock()
        response.status_code = status
        self._patch_session(monkeypatch, response)
        assert check_access("zenloop-token") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self, monkeypatch: Any) -> None:
        self._patch_session(monkeypatch, ConnectionError("boom"))
        status, message = check_access("zenloop-token")
        assert status == 0
        assert message is not None and "Zenloop" in message


class TestZenloopSourceResponse:
    @parameterized.expand([("surveys",), ("survey_groups",), ("properties",)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_response_shape_matches_endpoint_config(self, endpoint: str, MockSession) -> None:
        response = zenloop_source(
            api_token="zenloop-token",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # No endpoint exposes a creation-timestamp partition key, so partitioning stays off.
        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in ZENLOOP_ENDPOINTS.values())
        assert set(ZENLOOP_ENDPOINTS) == set(ENDPOINTS)
