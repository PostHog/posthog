import json
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.justsift.justsift import (
    PAGE_SIZE,
    JustSiftResumeConfig,
    check_access,
    justsift_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.justsift.settings import (
    ENDPOINTS,
    JUSTSIFT_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# check_access builds its own tracked session in the justsift module.
JUSTSIFT_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.justsift.justsift.make_tracked_session"
)


def _response(items: list[dict[str, Any]] | None, *, total: int | None = None, status: int = 200) -> Response:
    body: dict[str, Any] = {"links": {}, "meta": {}}
    if total is not None:
        body["meta"]["totalLength"] = total
    if items is not None:
        body["data"] = items
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    return resp


def _full_page(seq: int, *, total: int | None = None) -> Response:
    # A page exactly PAGE_SIZE long, so termination relies on the total, not a short page.
    return _response([{"id": f"{seq}-{i}"} for i in range(PAGE_SIZE)], total=total)


def _make_manager(resume_state: JustSiftResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list capturing each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
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


def _source(endpoint: str, manager: mock.MagicMock) -> Any:
    return justsift_source(
        api_key="sift-token",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_short_page_yields_items_and_stops(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "a"}, {"id": "b"}])])

        manager = _make_manager()
        rows = _rows(_source("people", manager))

        assert rows == [{"id": "a"}, {"id": "b"}]
        assert session.send.call_count == 1
        # A short page ends the sync, so no resume state is persisted.
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_pagination_until_short_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_full_page(1), _full_page(2), _response([{"id": "tail"}])])

        rows = _rows(_source("people", _make_manager()))

        assert len(rows) == PAGE_SIZE * 2 + 1
        assert rows[-1] == {"id": "tail"}
        assert [p["page"] for p in params] == [1, 2, 3]
        assert all(p["pageSize"] == PAGE_SIZE for p in params)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_terminates_when_total_is_covered_by_full_page(self, MockSession) -> None:
        # A final page exactly PAGE_SIZE long still terminates because the reported total is reached
        # — without the total check the loop would fetch a spurious empty page.
        session = MockSession.return_value
        _wire(session, [_full_page(1, total=PAGE_SIZE)])

        rows = _rows(_source("people", _make_manager()))

        assert len(rows) == PAGE_SIZE
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_next_page_after_yielding_each_batch(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_full_page(1), _response([{"id": "last"}])])

        manager = _make_manager()
        _rows(_source("people", manager))

        # State is saved AFTER page 1 is yielded (pointing at page 2), never for the final page.
        manager.save_state.assert_called_once_with(JustSiftResumeConfig(next_page=2))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_full_page(2), _response([{"id": "z"}])])

        manager = _make_manager(JustSiftResumeConfig(next_page=2))
        rows = _rows(_source("people", manager))

        assert len(rows) == PAGE_SIZE + 1
        assert rows[-1] == {"id": "z"}
        # Page 1 must never be fetched on resume.
        assert params[0]["page"] == 2
        assert all(p["page"] != 1 for p in params)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_does_not_yield(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        manager = _make_manager()
        rows = _rows(_source("people", manager))

        assert rows == []
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_raises_loudly(self, MockSession) -> None:
        session = MockSession.return_value
        # A 200 body without "data" means the response shape changed — fail loud, not silently 0 rows.
        _wire(session, [_response(None)])

        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_source("people", _make_manager()))


class TestRetryAndFailLoud:
    @mock.patch("time.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_transient_5xx_is_retried_then_succeeds(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_response(None, status=500), _response([{"id": "a"}])])

        rows = _rows(_source("people", _make_manager()))

        assert rows == [{"id": "a"}]
        assert session.send.call_count == 2

    @mock.patch("time.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_rate_limit_is_retried_then_succeeds(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_response(None, status=429), _response([{"id": "a"}])])

        rows = _rows(_source("people", _make_manager()))

        assert rows == [{"id": "a"}]
        assert session.send.call_count == 2

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_fail_loud(self, _name: str, status: int, MockSession) -> None:
        session = MockSession.return_value
        # A non-retryable client error surfaces as an HTTPError (raise_for_status), stopping the sync.
        _wire(session, [_response(None, status=status)])

        with pytest.raises(HTTPError):
            _rows(_source("people", _make_manager()))


class TestSourceResponse:
    @parameterized.expand([("people", ["id"]), ("fields", ["objectKey"])])
    def test_primary_keys_match_endpoint_config(self, endpoint: str, primary_keys: list[str]) -> None:
        response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        # No endpoint exposes a creation timestamp, so nothing is partitioned by datetime.
        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_endpoint_catalog_matches_exported_tuple(self) -> None:
        assert set(JUSTSIFT_ENDPOINTS) == set(ENDPOINTS)


class TestCheckAccess:
    def _patch_session(self, response: Any):
        session = mock.MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        return mock.patch(JUSTSIFT_SESSION_PATCH, return_value=session)

    @pytest.mark.parametrize(
        "status, expected_status, expected_message",
        [
            (200, 200, None),
            (401, 401, None),
            (403, 403, None),
            (500, 500, "Sift returned HTTP 500"),
        ],
    )
    def test_status_mapping(self, status: int, expected_status: int, expected_message: str | None) -> None:
        with self._patch_session(mock.MagicMock(status_code=status)):
            assert check_access("sift-token") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self) -> None:
        with self._patch_session(Exception("boom")):
            status, message = check_access("sift-token")
        assert status == 0
        assert message == "Could not connect to Sift"
