import json
from typing import Any, Optional

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.tavus import tavus
from products.warehouse_sources.backend.temporal.data_imports.sources.tavus.settings import ENDPOINTS, TAVUS_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.tavus.tavus import (
    TAVUS_BASE_URL,
    TavusResumeConfig,
    check_access,
    tavus_source,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# check_access builds its own tracked session in the tavus module (via validate_via_probe).
TAVUS_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.tavus.tavus.make_tracked_session"
)


def _response(
    items: Optional[list[dict[str, Any]]],
    *,
    total_count: Optional[int] = None,
    drop_data: bool = False,
    status: int = 200,
    reason: str = "OK",
    url: str = f"{TAVUS_BASE_URL}/videos?page=0&limit=100",
) -> Response:
    body: dict[str, Any] = {}
    if not drop_data:
        body["data"] = items or []
        if total_count is not None:
            body["total_count"] = total_count
    resp = Response()
    resp.status_code = status
    resp.reason = reason
    resp.url = url
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: TavusResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session; return a list capturing each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so a copy is snapshotted when
    each request is prepared rather than inspected after the run.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        prepared = mock.MagicMock()
        prepared.url = f"{TAVUS_BASE_URL}/videos"
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(manager: mock.MagicMock, endpoint: str = "videos"):
    return tavus_source(
        api_key="tavus-key",
        endpoint=endpoint,
        team_id=1,
        job_id="job-1",
        resumable_source_manager=manager,
    )


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_page_then_short_page_progresses_page_param(self, MockSession) -> None:
        session = MockSession.return_value
        full = [{"video_id": f"v_{i}"} for i in range(100)]
        params = _wire(
            session, [_response(full, total_count=101), _response([{"video_id": "v_last"}], total_count=101)]
        )

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert [r["video_id"] for r in rows] == [*(f"v_{i}" for i in range(100)), "v_last"]
        assert params[0]["page"] == 0
        assert params[0]["limit"] == 100
        assert params[1]["page"] == 1
        # Checkpoint saved after the first full page (pointing at page 1); the short page ends it.
        manager.save_state.assert_called_once_with(TavusResumeConfig(next_page=1))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_first_page_makes_one_request_and_no_checkpoint(self, MockSession, monkeypatch) -> None:
        monkeypatch.setattr(tavus, "PAGE_SIZE", 2)
        session = MockSession.return_value
        _wire(session, [_response([{"video_id": "a"}], total_count=1)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert [r["video_id"] for r in rows] == ["a"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_when_running_count_reaches_total_on_full_final_page(self, MockSession, monkeypatch) -> None:
        # Both pages are full (== PAGE_SIZE), so termination relies on total_count, not a short page.
        monkeypatch.setattr(tavus, "PAGE_SIZE", 2)
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"video_id": "a"}, {"video_id": "b"}], total_count=4),
                _response([{"video_id": "c"}, {"video_id": "d"}], total_count=4),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert [r["video_id"] for r in rows] == ["a", "b", "c", "d"]
        # Page 2 must never be requested; state saved exactly once (after page 0).
        assert session.send.call_count == 2
        manager.save_state.assert_called_once_with(TavusResumeConfig(next_page=1))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession, monkeypatch) -> None:
        monkeypatch.setattr(tavus, "PAGE_SIZE", 2)
        session = MockSession.return_value
        # Page 0 must never be fetched on resume; the first request targets the saved page.
        params = _wire(session, [_response([{"video_id": "c"}], total_count=3)])

        manager = _make_manager(TavusResumeConfig(next_page=1))
        rows = _rows(_source(manager))

        assert params[0]["page"] == 1
        assert [r["video_id"] for r in rows] == ["c"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_yields_no_rows_and_no_checkpoint(self, MockSession, monkeypatch) -> None:
        monkeypatch.setattr(tavus, "PAGE_SIZE", 2)
        session = MockSession.return_value
        _wire(session, [_response([], total_count=0)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_raises_loudly(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(None, drop_data=True)])

        # A 200 body without "data" means the response shape changed — fail loud, not silently 0 rows.
        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_source(_make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_accept_header_set_on_session(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"video_id": "a"}], total_count=1)])

        _rows(_source(_make_manager()))
        assert session.headers.get("Accept") == "application/json"


class TestRetryClassification:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_server_error_is_retried_then_succeeds(self, MockSession, monkeypatch) -> None:
        # 5xx is retryable at the framework level; the request is reissued and eventually yields rows.
        monkeypatch.setattr("time.sleep", lambda _s: None)
        session = MockSession.return_value
        _wire(
            session, [_response(None, status=500, reason="Server Error"), _response([{"video_id": "a"}], total_count=1)]
        )

        rows = _rows(_source(_make_manager()))
        assert [r["video_id"] for r in rows] == ["a"]
        assert session.send.call_count == 2

    @parameterized.expand([("unauthorized", 401, "Unauthorized"), ("forbidden", 403, "Forbidden")])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_auth_error_raises_matchable_httperror(self, _name, status, reason, MockSession) -> None:
        session = MockSession.return_value
        url = f"{TAVUS_BASE_URL}/videos?page=0&limit=100"
        _wire(session, [_response(None, status=status, reason=reason, url=url)])

        with pytest.raises(requests.HTTPError) as exc_info:
            _rows(_source(_make_manager()))
        # The message must carry the stable "{status} Client Error: {reason} for url: <base host>"
        # prefix that TavusSource.get_non_retryable_errors matches on.
        assert f"{status} Client Error: {reason} for url: {TAVUS_BASE_URL}" in str(exc_info.value)


class TestCheckAccess:
    @parameterized.expand(
        [
            (200, 200, None),
            (401, 401, None),
            (403, 403, None),
            (500, 500, "Tavus returned HTTP 500"),
        ]
    )
    def test_status_mapping(self, http_status: int, expected_status: int, expected_message: str | None) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=http_status)
        with mock.patch(TAVUS_SESSION_PATCH, lambda **kwargs: session):
            assert check_access("tavus-key") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with mock.patch(TAVUS_SESSION_PATCH, lambda **kwargs: session):
            status, message = check_access("tavus-key")
        assert status == 0
        assert message == "Could not connect to Tavus"

    def test_probe_targets_default_path(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=200)
        with mock.patch(TAVUS_SESSION_PATCH, lambda **kwargs: session):
            check_access("tavus-key")
        called_url = session.get.call_args.args[0]
        assert called_url == f"{TAVUS_BASE_URL}/replicas?page=0&limit=1"


class TestTavusSourceResponse:
    @parameterized.expand(
        [
            ("videos", "video_id"),
            ("replicas", "replica_id"),
            ("personas", "persona_id"),
            ("conversations", "conversation_id"),
        ]
    )
    def test_primary_key_matches_endpoint_config(self, endpoint: str, primary_key: str) -> None:
        response = _source(_make_manager(), endpoint=endpoint)
        assert response.name == endpoint
        assert response.primary_keys == [primary_key]
        # No endpoint exposes a curl-verified creation field, so none partition.
        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_every_endpoint_uses_a_resource_specific_primary_key(self) -> None:
        assert {name: cfg.primary_keys for name, cfg in TAVUS_ENDPOINTS.items()} == {
            "videos": ["video_id"],
            "replicas": ["replica_id"],
            "personas": ["persona_id"],
            "conversations": ["conversation_id"],
        }
        assert set(TAVUS_ENDPOINTS) == set(ENDPOINTS)
