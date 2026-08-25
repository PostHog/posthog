import json
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.qualaroo.qualaroo import (
    PAGE_SIZE,
    QualarooResumeConfig,
    qualaroo_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.qualaroo.settings import (
    ENDPOINTS,
    QUALAROO_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the qualaroo module.
QUALAROO_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.qualaroo.qualaroo.make_tracked_session"
)
# tenacity naps between retries; patch it out so failure-path tests don't sleep.
SLEEP_PATCH = "tenacity.nap.time.sleep"


def _response(body: Any, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    resp.url = "https://api.qualaroo.com/api/v1/nudges.json"
    resp.reason = "OK" if status < 400 else "Error"
    return resp


def _make_manager(resume_state: QualarooResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session; return a list capturing each request's params AT SEND TIME.

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


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _run(manager) -> Any:
    return qualaroo_source(
        api_key="q-key",
        api_secret="q-secret",
        endpoint="nudges",
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


def _full_page(start_id: int) -> list[dict[str, Any]]:
    return [{"id": start_id + i} for i in range(PAGE_SIZE)]


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_and_progresses_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response(_full_page(0)), _response([{"id": 999}])])

        manager = _make_manager()
        rows = _rows(_run(manager))

        assert len(rows) == PAGE_SIZE + 1
        assert rows[-1] == {"id": 999}
        # First request starts at offset 0 with the max page size; second advances one page.
        assert params[0]["offset"] == 0
        assert params[0]["limit"] == PAGE_SIZE
        assert params[1]["offset"] == PAGE_SIZE
        # Checkpoint saved once after the first full page (points at the next page); short page ends it.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == QualarooResumeConfig(offset=PAGE_SIZE)

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
    def test_empty_first_page_yields_nothing_and_no_checkpoint(self, MockSession) -> None:
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
        # Offset 0 must never be fetched on resume — the first request starts at the saved offset.
        params = _wire(session, [_response([{"id": 5}])])

        manager = _make_manager(QualarooResumeConfig(offset=PAGE_SIZE))
        rows = _rows(_run(manager))

        assert rows == [{"id": 5}]
        assert params[0]["offset"] == PAGE_SIZE


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_are_retried_then_reraised(self, _name: str, status: int, MockSession, _sleep) -> None:
        session = MockSession.return_value
        session.headers = {}
        session.prepare_request.return_value = mock.MagicMock()
        session.send.return_value = _response([], status=status)

        with pytest.raises(RESTClientRetryableError):
            _rows(_run(_make_manager()))
        # A persistent retryable status is reissued, not surfaced on the first attempt.
        assert session.send.call_count > 1

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_fail_loud_without_retry(self, _name: str, status: int, MockSession, _sleep) -> None:
        session = MockSession.return_value
        session.headers = {}
        session.prepare_request.return_value = mock.MagicMock()
        session.send.return_value = _response({"error": "nope"}, status=status)

        with pytest.raises(requests.HTTPError):
            _rows(_run(_make_manager()))
        # 4xx is permanent — the request must not be reissued.
        assert session.send.call_count == 1

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_is_retried(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        session.headers = {}
        session.prepare_request.return_value = mock.MagicMock()
        # Qualaroo list endpoints return a bare array; a 200 dict body is treated as a transient
        # shape glitch and reissued rather than ingested as a single row.
        session.send.return_value = _response({"error": "nope"})

        with pytest.raises(RESTClientRetryableError):
            _rows(_run(_make_manager()))
        assert session.send.call_count > 1


class TestValidateCredentials:
    @parameterized.expand(
        [
            (200, True, None),
            (401, False, "Invalid Qualaroo API key or secret"),
            (403, False, "Invalid Qualaroo API key or secret"),
            (500, False, "Qualaroo returned HTTP 500"),
        ]
    )
    @mock.patch(QUALAROO_SESSION_PATCH)
    def test_status_mapping(
        self, status: int, expected_valid: bool, expected_message: str | None, mock_session
    ) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("q-key", "q-secret") == (expected_valid, expected_message)

    @mock.patch(QUALAROO_SESSION_PATCH)
    def test_connection_error_is_unvalidated(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        assert validate_credentials("q-key", "q-secret") == (False, "Could not validate Qualaroo credentials")


class TestSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(self, endpoint: str, MockSession) -> None:
        MockSession.return_value.headers = {}
        response = qualaroo_source(
            api_key="q-key",
            api_secret="q-secret",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in QUALAROO_ENDPOINTS.values())
        assert set(QUALAROO_ENDPOINTS) == set(ENDPOINTS)
