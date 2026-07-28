import json
from typing import Any
from urllib.parse import urlparse

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.lattice.lattice import (
    PAGE_SIZE,
    LatticeResumeConfig,
    _base_url,
    lattice_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lattice.settings import (
    ENDPOINTS,
    LATTICE_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the lattice module.
LATTICE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.lattice.lattice.make_tracked_session"
)


def _response(
    items: list[dict[str, Any]] | None, *, has_more: bool = False, ending_cursor: str | None = None
) -> Response:
    body: dict[str, Any] = {"data": items or [], "hasMore": has_more, "endingCursor": ending_cursor}
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: LatticeResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's (url, params) AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so inspect it when each request
    is prepared instead of after the run.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(region: str, endpoint: str, manager: mock.MagicMock):
    return lattice_source(
        region=region,
        api_key="key",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


class TestBaseUrl:
    def test_us_and_emea_hosts(self):
        assert _base_url("us") == "https://api.latticehq.com"
        assert _base_url("emea") == "https://api.emea.latticehq.com"

    def test_invalid_region_raises(self):
        with pytest.raises(ValueError):
            _base_url("evil.example.com")


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_message",
        [
            (200, True, None),
            # Keys inherit the creating user's privileges; 403 means a scope
            # gap, not a bad key.
            (403, True, None),
            (401, False, "Invalid Lattice API key"),
        ],
    )
    @mock.patch(LATTICE_SESSION_PATCH)
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected_valid, expected_message):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("us", "key") == (expected_valid, expected_message)

    @mock.patch(LATTICE_SESSION_PATCH)
    def test_validate_credentials_rejects_bad_region_without_request(self, mock_session):
        is_valid, error = validate_credentials("evil", "key")
        assert is_valid is False
        assert error is not None
        mock_session.return_value.get.assert_not_called()

    @mock.patch(LATTICE_SESSION_PATCH)
    def test_validate_credentials_transport_error_is_not_invalid_key(self, mock_session):
        # A transient connectivity failure must not be reported as a bad key.
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")

        is_valid, error = validate_credentials("us", "key")
        assert is_valid is False
        assert error is not None
        assert "Invalid Lattice API key" not in error


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_via_ending_cursor(self, MockSession):
        session = MockSession.return_value
        snaps = _wire(
            session,
            [
                _response([{"id": "1"}], has_more=True, ending_cursor="cur_abc"),
                _response([{"id": "2"}], has_more=False),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("us", "users", manager))

        assert [r["id"] for r in rows] == ["1", "2"]
        # Checkpoint saved after the first page (points at the next cursor); the second page ends it.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].starting_after == "cur_abc"
        assert snaps[1]["params"]["startingAfter"] == "cur_abc"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_first_request_uses_max_page_size(self, MockSession):
        session = MockSession.return_value
        snaps = _wire(session, [_response([])])

        list(_source("us", "goals", _make_manager()).items())

        assert urlparse(snaps[0]["url"]).path == "/v1/goals"
        assert snaps[0]["params"]["limit"] == PAGE_SIZE
        assert "startingAfter" not in snaps[0]["params"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_emea_region_uses_emea_host(self, MockSession):
        session = MockSession.return_value
        snaps = _wire(session, [_response([])])

        list(_source("emea", "users", _make_manager()).items())

        assert urlparse(snaps[0]["url"]).netloc == "api.emea.latticehq.com"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession):
        session = MockSession.return_value
        snaps = _wire(session, [_response([])])

        manager = _make_manager(LatticeResumeConfig(starting_after="cur_resume"))
        list(_source("us", "users", manager).items())

        assert snaps[0]["params"]["startingAfter"] == "cur_resume"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_has_more_without_cursor_stops(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response([{"id": "1"}], has_more=True, ending_cursor=None)])

        manager = _make_manager()
        rows = _rows(_source("us", "users", manager))

        assert [r["id"] for r in rows] == ["1"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_stops_without_saving_state(self, MockSession):
        # A server that keeps advertising hasMore with an empty page must not loop forever.
        session = MockSession.return_value
        _wire(session, [_response([], has_more=True, ending_cursor="cur_loop")])

        manager = _make_manager()
        rows = _rows(_source("us", "users", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()


class TestLatticeSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_response_metadata_per_endpoint(self, MockSession, endpoint):
        config = LATTICE_ENDPOINTS[endpoint]
        response = _source("us", endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        assert response.partition_mode is None
        assert response.partition_keys is None
