import json
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.alguna.alguna import (
    ALGUNA_API_VERSION,
    AlgunaResumeConfig,
    alguna_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the alguna module.
ALGUNA_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.alguna.alguna.make_tracked_session"
)


def _response(items: list[dict[str, Any]] | None, *, drop_data: bool = False) -> Response:
    body: dict[str, Any] = {"pagination": {"per_page": 100}}
    if not drop_data:
        body["data"] = items or []
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: AlgunaResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list that captures each request's params AT SEND TIME.

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


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_and_progresses_offset(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"id": f"c_{i}"} for i in range(100)]
        params = _wire(session, [_response(full_page), _response([{"id": "c_last"}])])

        manager = _make_manager()
        rows = _rows(alguna_source("key", "customers", team_id=1, job_id="j", resumable_source_manager=manager))

        assert [r["id"] for r in rows] == [*(f"c_{i}" for i in range(100)), "c_last"]
        assert params[0]["offset"] == 0
        assert params[0]["limit"] == 100
        assert params[1]["offset"] == 100
        # Checkpoint saved after the first full page (points at the next page); short page ends it.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == AlgunaResumeConfig(offset=100)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_first_page_makes_one_request_and_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "a"}, {"id": "b"}])])

        manager = _make_manager()
        rows = _rows(alguna_source("key", "customers", team_id=1, job_id="j", resumable_source_manager=manager))

        assert [r["id"] for r in rows] == ["a", "b"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "c_201"}])])

        manager = _make_manager(AlgunaResumeConfig(offset=200))
        _rows(alguna_source("key", "customers", team_id=1, job_id="j", resumable_source_manager=manager))

        assert params[0]["offset"] == 200

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_version_header_is_set_on_session(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "a"}])])

        _rows(alguna_source("key", "customers", team_id=1, job_id="j", resumable_source_manager=_make_manager()))
        assert session.headers.get("Alguna-Version") == ALGUNA_API_VERSION

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sort_param_present_for_sortable_endpoint(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "a"}])])

        _rows(alguna_source("key", "customers", team_id=1, job_id="j", resumable_source_manager=_make_manager()))
        assert params[0]["sort"] == "created_at:asc"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_sort_param_for_unsortable_endpoint(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "a"}])])

        _rows(alguna_source("key", "payments", team_id=1, job_id="j", resumable_source_manager=_make_manager()))
        assert "sort" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_raises_loudly(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(None, drop_data=True)])

        # A 200 body without "data" means the response shape changed — fail loud, not silently 0 rows.
        with pytest.raises(ValueError, match="matched nothing"):
            _rows(alguna_source("key", "customers", team_id=1, job_id="j", resumable_source_manager=_make_manager()))


class TestValidateCredentials:
    @mock.patch(ALGUNA_SESSION_PATCH)
    def test_ok(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("key") is True

    @mock.patch(ALGUNA_SESSION_PATCH)
    def test_unauthorized(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=401)
        assert validate_credentials("key") is False

    @mock.patch(ALGUNA_SESSION_PATCH)
    def test_swallows_exceptions(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key") is False
