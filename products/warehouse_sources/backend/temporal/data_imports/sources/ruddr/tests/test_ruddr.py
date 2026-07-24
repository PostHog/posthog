import json
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ruddr.ruddr import (
    PAGE_SIZE,
    RuddrResumeConfig,
    ruddr_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ruddr.settings import ENDPOINTS, RUDDR_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the ruddr module.
RUDDR_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.ruddr.ruddr.make_tracked_session"
)
# Patch tenacity's sleep so the client's retry backoff doesn't slow the malformed/retryable tests.
SLEEP_PATCH = "tenacity.nap.time.sleep"


def _response(results: list[dict[str, Any]], *, has_more: bool = False, status_code: int = 200) -> Response:
    # Ruddr list endpoints wrap records in {"results": [...], "hasMore": bool}.
    return _raw_response({"results": results, "hasMore": has_more}, status_code=status_code)


def _raw_response(body: Any, *, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    resp.url = "https://www.ruddr.io/api/workspace/clients"
    return resp


def _make_manager(resume_state: RuddrResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list capturing each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
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


def _full_page(start_id: int) -> list[dict[str, Any]]:
    # Ruddr resource ids are strings, and the cursor (RuddrResumeConfig.cursor) is typed str | None.
    return [{"id": str(start_id + i)} for i in range(PAGE_SIZE)]


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_cursor_until_hasmore_false(self, MockSession) -> None:
        session = MockSession.return_value
        # First page is full with hasMore true; the cursor advances to the last row's id ("99").
        params = _wire(session, [_response(_full_page(0), has_more=True), _response([{"id": "999"}], has_more=False)])

        manager = _make_manager()
        rows = _rows(ruddr_source("key", "clients", team_id=1, job_id="j", resumable_source_manager=manager))

        assert [r["id"] for r in rows] == [*(str(i) for i in range(PAGE_SIZE)), "999"]
        # First page has limit only; the second carries startingAfter = the previous page's last id.
        assert params[0] == {"limit": PAGE_SIZE}
        assert params[1] == {"limit": PAGE_SIZE, "startingAfter": str(PAGE_SIZE - 1)}
        # Checkpoint saved after the first page (points at the next page); hasMore false ends it.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == RuddrResumeConfig(cursor=str(PAGE_SIZE - 1))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_hasmore_false_yields_and_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "1"}, {"id": "2"}], has_more=False)])

        manager = _make_manager()
        rows = _rows(ruddr_source("key", "clients", team_id=1, job_id="j", resumable_source_manager=manager))

        assert [r["id"] for r in rows] == ["1", "2"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_page_with_hasmore_false_stops(self, MockSession) -> None:
        session = MockSession.return_value
        # A full page but hasMore false: stop after it rather than requesting another page.
        _wire(session, [_response(_full_page(0), has_more=False)])

        manager = _make_manager()
        rows = _rows(ruddr_source("key", "clients", team_id=1, job_id="j", resumable_source_manager=manager))

        assert len(rows) == PAGE_SIZE
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing_and_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], has_more=False)])

        manager = _make_manager()
        rows = _rows(ruddr_source("key", "clients", team_id=1, job_id="j", resumable_source_manager=manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_with_hasmore_true_still_stops(self, MockSession) -> None:
        session = MockSession.return_value
        # Defensive: an empty page ends the sync even if the server claims more remain.
        _wire(session, [_response([], has_more=True)])

        manager = _make_manager()
        rows = _rows(ruddr_source("key", "clients", team_id=1, job_id="j", resumable_source_manager=manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "5"}], has_more=False)])

        manager = _make_manager(RuddrResumeConfig(cursor="cur-99"))
        rows = _rows(ruddr_source("key", "clients", team_id=1, job_id="j", resumable_source_manager=manager))

        assert [r["id"] for r in rows] == ["5"]
        # The initial (cursor-less) page must never be fetched on resume — the first request
        # targets the saved cursor.
        assert params[0]["startingAfter"] == "cur-99"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_request_targets_endpoint_path(self, MockSession) -> None:
        session = MockSession.return_value
        session.headers = {}
        captured: list[str] = []

        def _prepare(request: Any) -> mock.MagicMock:
            captured.append(request.url)
            return mock.MagicMock()

        session.prepare_request.side_effect = _prepare
        session.send.side_effect = [_response([{"id": "1"}], has_more=False)]

        _rows(ruddr_source("key", "time_entries", team_id=1, job_id="j", resumable_source_manager=_make_manager()))
        assert captured[0] == "https://www.ruddr.io/api/workspace/time-entries"


class TestErrorHandling:
    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_dict_body_is_retried_then_reraises(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        session.headers = {}
        session.prepare_request.return_value = mock.MagicMock()
        # A 200 body that is a bare array (not the {"results": [...]} envelope) — retried, never
        # ingested as rows.
        session.send.return_value = _raw_response([{"id": "1"}])

        with pytest.raises(RESTClientRetryableError, match="Unexpected 200 response body shape"):
            _rows(ruddr_source("key", "clients", team_id=1, job_id="j", resumable_source_manager=_make_manager()))

        # Exhausts the client's default retry budget (5 attempts) before giving up.
        assert session.send.call_count == 5

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_results_key_is_retried_then_reraises(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        session.headers = {}
        session.prepare_request.return_value = mock.MagicMock()
        session.send.return_value = _raw_response({"hasMore": False})

        with pytest.raises(RESTClientRetryableError, match="Unexpected 200 response body shape"):
            _rows(ruddr_source("key", "clients", team_id=1, job_id="j", resumable_source_manager=_make_manager()))
        assert session.send.call_count == 5

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_malformed_then_valid_recovers(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        session.headers = {}
        session.prepare_request.return_value = mock.MagicMock()
        session.send.side_effect = [_raw_response({"error": "glitch"}), _response([{"id": "1"}], has_more=False)]

        rows = _rows(ruddr_source("key", "clients", team_id=1, job_id="j", resumable_source_manager=_make_manager()))
        assert [r["id"] for r in rows] == ["1"]
        assert session.send.call_count == 2

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_then_success_recovers(self, _name, status, MockSession, _sleep) -> None:
        session = MockSession.return_value
        session.headers = {}
        session.prepare_request.return_value = mock.MagicMock()
        session.send.side_effect = [_response([], status_code=status), _response([{"id": "1"}], has_more=False)]

        rows = _rows(ruddr_source("key", "clients", team_id=1, job_id="j", resumable_source_manager=_make_manager()))
        assert [r["id"] for r in rows] == ["1"]
        assert session.send.call_count == 2

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_raise_http_error(self, _name, status, MockSession) -> None:
        session = MockSession.return_value
        session.headers = {}
        session.prepare_request.return_value = mock.MagicMock()
        session.send.return_value = _response([], status_code=status)

        with pytest.raises(HTTPError):
            _rows(ruddr_source("key", "clients", team_id=1, job_id="j", resumable_source_manager=_make_manager()))


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, (True, None)),
            ("unauthorized", 401, (False, "Invalid Ruddr API key")),
            ("forbidden", 403, (False, "Invalid Ruddr API key")),
            ("server_error", 500, (False, "Ruddr returned HTTP 500")),
        ]
    )
    @mock.patch(RUDDR_SESSION_PATCH)
    def test_status_mapping(self, _name: str, status: int, expected: tuple[bool, str | None], mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("key") == expected

    @mock.patch(RUDDR_SESSION_PATCH)
    def test_connection_error_is_not_validated(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key") == (False, "Could not validate Ruddr API key")

    @mock.patch(RUDDR_SESSION_PATCH)
    def test_probe_uses_limit_one(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("key")
        url = mock_session.return_value.get.call_args.args[0]
        assert url == "https://www.ruddr.io/api/workspace/clients?limit=1"


class TestRuddrSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(self, endpoint: str, MockSession) -> None:
        response = ruddr_source("key", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager())
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in RUDDR_ENDPOINTS.values())
        assert set(RUDDR_ENDPOINTS) == set(ENDPOINTS)
