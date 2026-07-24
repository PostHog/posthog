import json
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.planhat.planhat import (
    PAGE_SIZE,
    PlanhatResumeConfig,
    planhat_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.planhat.settings import (
    ENDPOINTS,
    PLANHAT_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the planhat module.
PLANHAT_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.planhat.planhat.make_tracked_session"
)
SLEEP_PATCH = "tenacity.nap.time.sleep"


def _response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    resp.url = "https://api.planhat.com/companies"
    return resp


def _make_manager(resume_state: PlanhatResumeConfig | None = None) -> mock.MagicMock:
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
    return [{"_id": str(start_id + i)} for i in range(PAGE_SIZE)]


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_and_progresses_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response(_full_page(0)), _response([{"_id": "c_last"}])])

        manager = _make_manager()
        rows = _rows(planhat_source("tok", "companies", team_id=1, job_id="j", resumable_source_manager=manager))

        assert [r["_id"] for r in rows] == [*(str(i) for i in range(PAGE_SIZE)), "c_last"]
        assert params[0]["offset"] == 0
        assert params[0]["limit"] == PAGE_SIZE
        assert params[1]["offset"] == PAGE_SIZE
        # Checkpoint saved after the first full page (points at the next page); short page ends it.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == PlanhatResumeConfig(offset=PAGE_SIZE)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_first_page_makes_one_request_and_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"_id": "1"}, {"_id": "2"}])])

        manager = _make_manager()
        rows = _rows(planhat_source("tok", "companies", team_id=1, job_id="j", resumable_source_manager=manager))

        assert [r["_id"] for r in rows] == ["1", "2"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing_and_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        manager = _make_manager()
        rows = _rows(planhat_source("tok", "companies", team_id=1, job_id="j", resumable_source_manager=manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"_id": "5"}])])

        manager = _make_manager(PlanhatResumeConfig(offset=PAGE_SIZE))
        rows = _rows(planhat_source("tok", "companies", team_id=1, job_id="j", resumable_source_manager=manager))

        assert [r["_id"] for r in rows] == ["5"]
        # Offset 0 must never be fetched on resume — the first request targets the saved offset.
        assert params[0]["offset"] == PAGE_SIZE

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_request_targets_endpoint_path(self, MockSession) -> None:
        session = MockSession.return_value
        session.headers = {}
        captured: list[str] = []

        def _prepare(request: Any) -> mock.MagicMock:
            captured.append(request.url)
            return mock.MagicMock()

        session.prepare_request.side_effect = _prepare
        session.send.side_effect = [_response([{"_id": "1"}])]

        _rows(planhat_source("tok", "endusers", team_id=1, job_id="j", resumable_source_manager=_make_manager()))
        assert captured[0] == "https://api.planhat.com/endusers"


class TestMalformedBody:
    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_is_retried_then_reraises(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        session.headers = {}
        session.prepare_request.return_value = mock.MagicMock()
        # A 200 body that is not a bare array (an error object) — retried, never ingested as a row.
        session.send.return_value = _response({"error": "nope"})

        with pytest.raises(RESTClientRetryableError, match="Unexpected 200 response body shape"):
            _rows(planhat_source("tok", "companies", team_id=1, job_id="j", resumable_source_manager=_make_manager()))

        # Exhausts the client's default retry budget (5 attempts) before giving up.
        assert session.send.call_count == 5

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_malformed_then_valid_recovers(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        session.headers = {}
        session.prepare_request.return_value = mock.MagicMock()
        session.send.side_effect = [_response({"error": "glitch"}), _response([{"_id": "1"}])]

        rows = _rows(
            planhat_source("tok", "companies", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        )
        assert [r["_id"] for r in rows] == ["1"]
        assert session.send.call_count == 2


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, (True, None)),
            ("unauthorized", 401, (False, "Invalid Planhat API token")),
            ("forbidden", 403, (False, "Invalid Planhat API token")),
            ("server_error", 500, (False, "Planhat returned HTTP 500")),
        ]
    )
    @mock.patch(PLANHAT_SESSION_PATCH)
    def test_status_mapping(self, _name: str, status: int, expected: tuple[bool, str | None], mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("tok") == expected

    @mock.patch(PLANHAT_SESSION_PATCH)
    def test_connection_error_is_not_validated(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("tok") == (False, "Could not validate Planhat API token")

    @mock.patch(PLANHAT_SESSION_PATCH)
    def test_probe_uses_limit_one(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("tok")
        url = mock_session.return_value.get.call_args.args[0]
        assert url == "https://api.planhat.com/companies?limit=1&offset=0"


class TestPlanhatSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(self, endpoint: str, MockSession) -> None:
        response = planhat_source("tok", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager())
        assert response.name == endpoint
        assert response.primary_keys == ["_id"]
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["_id"] for config in PLANHAT_ENDPOINTS.values())
        assert set(PLANHAT_ENDPOINTS) == set(ENDPOINTS)
