import json
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rentcast.rentcast import (
    PAGE_SIZE,
    RentCastResumeConfig,
    rentcast_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rentcast.settings import (
    ENDPOINTS,
    RENTCAST_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the rentcast module.
RENTCAST_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.rentcast.rentcast.make_tracked_session"
)


def _response(body: Any) -> Response:
    # RentCast list endpoints return a bare JSON array of records.
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    resp.url = "https://api.rentcast.io/v1/properties"
    return resp


def _make_manager(resume_state: RentCastResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], list[Any]]:
    """Wire a mock session; capture request params AND the request object AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []
    request_snapshots: list[Any] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        request_snapshots.append(request)
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots, request_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _full_page(start_id: int) -> list[dict]:
    return [{"id": start_id + i} for i in range(PAGE_SIZE)]


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_and_progresses_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(session, [_response(_full_page(0)), _response([{"id": 999}])])

        manager = _make_manager()
        rows = _rows(rentcast_source("rc-key", "properties", team_id=1, job_id="j", resumable_source_manager=manager))

        assert len(rows) == PAGE_SIZE + 1
        assert rows[-1] == {"id": 999}
        assert params[0]["offset"] == 0
        assert params[0]["limit"] == PAGE_SIZE
        assert params[1]["offset"] == PAGE_SIZE
        # Checkpoint saved after the first full page (points at the next page); short page ends it.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == RentCastResumeConfig(offset=PAGE_SIZE)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_first_page_makes_one_request_and_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}, {"id": 2}])])

        manager = _make_manager()
        rows = _rows(rentcast_source("rc-key", "properties", team_id=1, job_id="j", resumable_source_manager=manager))

        assert rows == [{"id": 1}, {"id": 2}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        manager = _make_manager()
        rows = _rows(rentcast_source("rc-key", "properties", team_id=1, job_id="j", resumable_source_manager=manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(session, [_response([{"id": 5}])])

        manager = _make_manager(RentCastResumeConfig(offset=PAGE_SIZE))
        rows = _rows(rentcast_source("rc-key", "properties", team_id=1, job_id="j", resumable_source_manager=manager))

        # Offset 0 must never be fetched on resume — the first request starts at the saved offset.
        assert params[0]["offset"] == PAGE_SIZE
        assert rows == [{"id": 5}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_endpoint_path_matches_config(self, MockSession) -> None:
        session = MockSession.return_value
        _, requests_seen = _wire(session, [_response([{"id": 1}])])

        _rows(
            rentcast_source("rc-key", "sale_listings", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        )
        assert requests_seen[0].url == "https://api.rentcast.io/v1/listings/sale"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_api_key_rides_in_x_api_key_header_and_accept_set(self, MockSession) -> None:
        session = MockSession.return_value
        _, requests_seen = _wire(session, [_response([{"id": 1}])])

        _rows(rentcast_source("rc-key", "properties", team_id=1, job_id="j", resumable_source_manager=_make_manager()))
        # The key is wired through framework auth (redacted from logs), targeting the X-Api-Key header.
        auth = requests_seen[0].auth
        assert auth.name == "X-Api-Key"
        assert auth.location == "header"
        assert auth.api_key == "rc-key"
        assert session.headers.get("Accept") == "application/json"

    @parameterized.expand([("bare_string", "nope"), ("dict_without_list", {"error": "nope"})])
    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_is_retryable(self, _name: str, bad_body: Any, MockSession, _sleep) -> None:
        session = MockSession.return_value
        session.headers = {}
        session.prepare_request.return_value = mock.MagicMock()
        session.send.return_value = _response(bad_body)

        # A 200 body that isn't a list means an unexpected shape — retry, don't sync garbage.
        with pytest.raises(RESTClientRetryableError, match="Unexpected 200 response body shape"):
            _rows(
                rentcast_source("rc-key", "properties", team_id=1, job_id="j", resumable_source_manager=_make_manager())
            )


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid RentCast API key"),
            ("forbidden", 403, False, "Invalid RentCast API key"),
            ("server_error", 500, False, "RentCast returned HTTP 500"),
        ]
    )
    @mock.patch(RENTCAST_SESSION_PATCH)
    def test_status_mapping(
        self, _name: str, status: int, expected_valid: bool, expected_message: str | None, mock_session
    ) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("rc-key") == (expected_valid, expected_message)

    @mock.patch(RENTCAST_SESSION_PATCH)
    def test_connection_error_is_not_validated(self, mock_session) -> None:
        # A transport failure must not raise out of validate_credentials — it maps to "not validated".
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("rc-key") == (False, "Could not validate RentCast API key")


class TestRentCastSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(self, endpoint: str, MockSession) -> None:
        response = rentcast_source("rc-key", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager())
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # No stable creation timestamp is guaranteed across every record, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in RENTCAST_ENDPOINTS.values())
        assert set(RENTCAST_ENDPOINTS) == set(ENDPOINTS)
