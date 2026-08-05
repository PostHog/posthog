import json
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.smartsheet.settings import (
    ENDPOINTS,
    SMARTSHEET_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartsheet.smartsheet import (
    PAGE_SIZE,
    SmartsheetResumeConfig,
    smartsheet_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the smartsheet module.
SMARTSHEET_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.smartsheet.smartsheet.make_tracked_session"
)


def _response(items: list[dict[str, Any]], total_pages: int) -> Response:
    body = {"pageNumber": 1, "pageSize": PAGE_SIZE, "totalPages": total_pages, "data": items}
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: SmartsheetResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list capturing each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so inspecting it after the run shows
    only the final page — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _source(endpoint: str, manager: mock.MagicMock):
    return smartsheet_source("token", endpoint, team_id=1, job_id="j", resumable_source_manager=manager)


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_through_total_pages(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session, [_response([{"id": 1}, {"id": 2}], total_pages=2), _response([{"id": 3}], total_pages=2)]
        )

        manager = _make_manager()
        rows = _rows(_source("sheets", manager))

        assert [r["id"] for r in rows] == [1, 2, 3]
        # Each request asks for an explicit ascending page number plus the fixed page size.
        assert params[0]["page"] == 1
        assert params[0]["pageSize"] == PAGE_SIZE
        assert params[1]["page"] == 2
        # State is saved once — only while a further page remains — pointing at the next page.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == SmartsheetResumeConfig(next_page=2)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_does_not_save_state(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}], total_pages=1)])

        manager = _make_manager()
        rows = _rows(_source("sheets", manager))

        assert [r["id"] for r in rows] == [1]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_response_stops_without_saving(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], total_pages=0)])

        manager = _make_manager()
        rows = _rows(_source("sheets", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 9}], total_pages=3)])

        manager = _make_manager(SmartsheetResumeConfig(next_page=3))
        _rows(_source("sheets", manager))

        assert params[0]["page"] == 3

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_bearer_auth_carries_token(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}], total_pages=1)])

        _rows(_source("sheets", _make_manager()))
        # Framework Bearer auth attaches the Authorization header (redacted from raised errors).
        assert session.auth is not None


class TestSmartsheetSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_response_metadata_per_endpoint(self, MockSession, endpoint) -> None:
        config = SMARTSHEET_ENDPOINTS[endpoint]
        response = _source(endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "week"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(SMARTSHEET_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config) -> None:
        # Never partition on a mutable field like modifiedAt.
        if config.partition_key:
            assert config.partition_key == "createdAt"


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    @mock.patch(SMARTSHEET_SESSION_PATCH)
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("token") is expected

    @mock.patch(SMARTSHEET_SESSION_PATCH)
    def test_validate_credentials_probes_users_me(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        validate_credentials("token")

        assert mock_session.return_value.get.call_args.args[0] == "https://api.smartsheet.com/2.0/users/me"

    @mock.patch(SMARTSHEET_SESSION_PATCH)
    def test_validate_credentials_swallows_exceptions(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("token") is False
