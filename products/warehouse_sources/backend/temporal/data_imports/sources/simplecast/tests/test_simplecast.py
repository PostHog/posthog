import json
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.simplecast.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.simplecast.simplecast import (
    PAGE_SIZE,
    SimpleCastResumeConfig,
    simplecast_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the simplecast module.
SIMPLECAST_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.simplecast.simplecast.make_tracked_session"
)
# Retryable paths spin the tenacity retry loop; patching the sleep keeps failure tests instant.
SLEEP_PATCH = "tenacity.nap.time.sleep"


def _envelope(items: list[dict[str, Any]], *, total: int = 1, current: int = 1) -> Response:
    body = {"collection": items, "pages": {"total": total, "current": current}}
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    resp.url = "https://api.simplecast.com/podcasts"
    return resp


def _raw(body: Any, *, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    resp.url = "https://api.simplecast.com/podcasts"
    return resp


def _full_page(start_id: int) -> list[dict[str, Any]]:
    return [{"id": f"p_{start_id + i}"} for i in range(PAGE_SIZE)]


def _make_manager(resume_state: SimpleCastResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so a copy must be snapshotted when
    each request is prepared rather than read after the run.
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


def _source(manager: mock.MagicMock, endpoint: str = "podcasts"):
    return simplecast_source(
        api_key="sc-token",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_and_progresses_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [_envelope(_full_page(0), total=2, current=1), _envelope([{"id": "p_last"}], total=2, current=2)],
        )

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert [r["id"] for r in rows] == [*(f"p_{i}" for i in range(PAGE_SIZE)), "p_last"]
        assert params[0]["offset"] == 0
        assert params[0]["limit"] == PAGE_SIZE
        assert params[1]["offset"] == PAGE_SIZE
        # Checkpoint saved once after the first full page (points at the next page); short page ends it.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == SimpleCastResumeConfig(offset=PAGE_SIZE)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_last_page_stops_on_pages_metadata_without_extra_request(self, MockSession) -> None:
        session = MockSession.return_value
        # A full page whose `pages` metadata marks it as the last page must terminate without paying
        # for an extra empty-page request, and without persisting a resume checkpoint.
        _wire(session, [_envelope(_full_page(0), total=1, current=1)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert len(rows) == PAGE_SIZE
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_first_page_one_request_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_envelope([{"id": "a"}, {"id": "b"}], total=1, current=1)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert [r["id"] for r in rows] == ["a", "b"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_envelope([], total=1, current=1)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_envelope([{"id": "p_101"}], total=2, current=2)])

        manager = _make_manager(SimpleCastResumeConfig(offset=PAGE_SIZE))
        rows = _rows(_source(manager))

        # Offset 0 must never be fetched on resume; the first (only) request starts at the saved offset.
        assert params[0]["offset"] == PAGE_SIZE
        assert [r["id"] for r in rows] == ["p_101"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_request_uses_limit_and_offset_params(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_envelope([], total=1, current=1)])

        _rows(_source(_make_manager()))
        assert params[0] == {"limit": PAGE_SIZE, "offset": 0}


class TestErrorHandling:
    @parameterized.expand(
        [
            ("bare_list", [{"id": 1}]),
            ("missing_collection", {"pages": {}}),
            ("error_envelope", {"error": "no"}),
        ]
    )
    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unexpected_200_body_is_retried_then_raises(self, _name, body, MockSession, _sleep) -> None:
        session = MockSession.return_value
        # The client retries a malformed 200 body up to 5 attempts, then reraises.
        _wire(session, [_raw(body) for _ in range(5)])

        with pytest.raises(Exception):
            _rows(_source(_make_manager()))
        assert session.send.call_count == 5

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_is_retried_then_raises(self, _name, status, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_raw({}, status=status) for _ in range(5)])

        with pytest.raises(Exception):
            _rows(_source(_make_manager()))
        assert session.send.call_count == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_raises_without_retry(self, _name, status, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_raw({}, status=status)])

        with pytest.raises(requests.HTTPError):
            _rows(_source(_make_manager()))
        # 4xx is a permanent failure — issued exactly once, never retried.
        assert session.send.call_count == 1


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, expected",
        [
            (200, (True, None)),
            (401, (False, "Invalid Simplecast API token")),
            (403, (False, "Invalid Simplecast API token")),
            (500, (False, "Simplecast returned HTTP 500")),
        ],
    )
    @mock.patch(SIMPLECAST_SESSION_PATCH)
    def test_status_mapping(self, mock_session, status, expected) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("sc-token") == expected

    @mock.patch(SIMPLECAST_SESSION_PATCH)
    def test_unreachable_probe_is_not_validated(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        assert validate_credentials("sc-token") == (False, "Could not validate Simplecast API token")


class TestSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _source(_make_manager(), endpoint=endpoint)
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None
