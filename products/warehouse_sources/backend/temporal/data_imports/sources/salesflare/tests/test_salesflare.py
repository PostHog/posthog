import json
from typing import Any

import pytest
from unittest import mock
from unittest.mock import MagicMock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.salesflare import salesflare
from products.warehouse_sources.backend.temporal.data_imports.sources.salesflare.salesflare import (
    PAGE_SIZE,
    SalesflareResumeConfig,
    check_access,
    salesflare_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.salesflare.settings import (
    ENDPOINTS,
    SALESFLARE_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# tenacity sleeps between retries; patch it so the failure-path tests don't actually wait.
SLEEP_PATCH = "tenacity.nap.time.sleep"


def _response(body: Any, *, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _full_page(start_id: int) -> list[dict[str, Any]]:
    return [{"id": start_id + i} for i in range(PAGE_SIZE)]


def _make_manager(resume_state: SalesflareResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
    request is prepared instead of inspecting it after the run.
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


def _run(manager, endpoint: str = "contacts"):
    return salesflare_source(
        api_key="sf-key",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_and_progresses_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response(_full_page(0)), _response([{"id": 999}])])

        manager = _make_manager()
        rows = _rows(_run(manager))

        assert len(rows) == PAGE_SIZE + 1
        assert rows[-1] == {"id": 999}
        assert params[0]["offset"] == 0
        assert params[0]["limit"] == PAGE_SIZE
        assert params[1]["offset"] == PAGE_SIZE
        # Checkpoint saved after the first full page (points at the next page); short page ends it.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == SalesflareResumeConfig(offset=PAGE_SIZE)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_first_page_makes_one_request_and_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}, {"id": 2}])])

        manager = _make_manager()
        rows = _rows(_run(manager))

        assert rows == [{"id": 1}, {"id": 2}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        manager = _make_manager()
        rows = _rows(_run(manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        # Offset 0 must never be fetched on resume — only the seeded page is served.
        params = _wire(session, [_response([{"id": 5}])])

        manager = _make_manager(SalesflareResumeConfig(offset=PAGE_SIZE))
        rows = _rows(_run(manager))

        assert rows == [{"id": 5}]
        assert params[0]["offset"] == PAGE_SIZE

    @parameterized.expand([(e,) for e in ENDPOINTS])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_requests_the_endpoint_path(self, endpoint: str, MockSession) -> None:
        session = MockSession.return_value
        urls: list[str] = []

        def _prepare(request: Any) -> mock.MagicMock:
            urls.append(request.url)
            return mock.MagicMock()

        session.headers = {}
        session.prepare_request.side_effect = _prepare
        session.send.side_effect = [_response([])]

        _rows(_run(_make_manager(), endpoint))
        assert urls[0] == f"{salesflare.SALESFLARE_BASE_URL}{SALESFLARE_ENDPOINTS[endpoint].path}"


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_are_retried_then_raise(self, _name: str, status: int, MockSession, _sleep) -> None:
        session = MockSession.return_value
        # Five identical failures exhaust the client's retry budget, then it reraises.
        _wire(session, [_response({"error": "nope"}, status_code=status) for _ in range(5)])

        with pytest.raises(RESTClientRetryableError):
            _rows(_run(_make_manager()))
        assert session.send.call_count == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_raise_immediately(self, _name: str, status: int, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"error": "nope"}, status_code=status)])

        with pytest.raises(requests.HTTPError):
            _rows(_run(_make_manager()))
        # 4xx is not retryable — exactly one request is made.
        assert session.send.call_count == 1

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_is_retryable(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        # A 200 whose body isn't a bare array is a malformed payload — retried, then reraised.
        _wire(session, [_response({"error": "nope"}) for _ in range(5)])

        with pytest.raises(RESTClientRetryableError):
            _rows(_run(_make_manager()))
        assert session.send.call_count == 5


class TestCheckAccess:
    @staticmethod
    def _session(response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        return session

    @parameterized.expand(
        [
            ("ok", 200, True, 200, None),
            ("unauthorized", 401, False, 401, None),
            ("forbidden", 403, False, 403, None),
            ("server_error", 500, False, 500, "Salesflare returned HTTP 500"),
        ]
    )
    @mock.patch.object(salesflare, "make_tracked_session")
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        ok: bool,
        expected_status: int,
        expected_message: str | None,
        mock_make_session: MagicMock,
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        mock_make_session.return_value = self._session(response)
        assert check_access("sf-key") == (expected_status, expected_message)

    @mock.patch.object(salesflare, "make_tracked_session")
    def test_connection_error_maps_to_zero(self, mock_make_session: MagicMock) -> None:
        mock_make_session.return_value = self._session(requests.ConnectionError("boom"))
        status, message = check_access("sf-key")
        assert status == 0
        assert message is not None and "boom" in message

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Salesflare API key"),
            ("forbidden", 403, False, "Invalid Salesflare API key"),
            ("server_error", 500, False, "Salesflare returned HTTP 500"),
        ]
    )
    @mock.patch.object(salesflare, "make_tracked_session")
    def test_validate_credentials(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_make_session: MagicMock,
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        mock_make_session.return_value = self._session(response)
        assert validate_credentials("sf-key") == (expected_valid, expected_message)


class TestSalesflareSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = salesflare_source(
            api_key="sf-key",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in SALESFLARE_ENDPOINTS.values())
        assert set(SALESFLARE_ENDPOINTS) == set(ENDPOINTS)
