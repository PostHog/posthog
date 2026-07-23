import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.resend.resend import (
    RESEND_BASE_URL,
    ResendResumeConfig,
    resend_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.resend.settings import ENDPOINTS, RESEND_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the resend module.
RESEND_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.resend.resend.make_tracked_session"
)


def _response(body: Any, status_code: int = 200, url: str = f"{RESEND_BASE_URL}/x") -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.url = url
    resp.reason = "OK" if status_code < 400 else "Error"
    resp.headers["Content-Type"] = "application/json"
    return resp


def _make_manager(resume_state: ResendResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[tuple[str, dict[str, Any]]]:
    """Wire a mock session and capture (url, params) snapshots AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[tuple[str, dict[str, Any]]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append((request.url, dict(request.params or {})))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(endpoint: str, manager: mock.MagicMock | None = None) -> SourceResponse:
    return resend_source(
        api_key="re_test",
        endpoint=endpoint,
        team_id=1,
        job_id="job-1",
        resumable_source_manager=manager if manager is not None else _make_manager(),
    )


def _rows(source_response: SourceResponse) -> list[dict[str, Any]]:
    return [row for page in cast("Iterable[Any]", source_response.items()) for row in page]


class TestFlatEndpoints:
    @pytest.mark.parametrize("endpoint", ["audiences", "broadcasts", "domains"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_flat_endpoint_yields_single_batch(self, MockSession, endpoint: str) -> None:
        session = MockSession.return_value
        rows = [{"id": "a1", "created_at": "2026-01-01T00:00:00Z"}]
        snapshots = _wire(session, [_response({"data": rows})])

        manager = _make_manager()
        result = _rows(_source(endpoint, manager))

        assert result == rows
        assert snapshots[0][0] == f"{RESEND_BASE_URL}{RESEND_ENDPOINTS[endpoint].path}"
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_flat_endpoint_empty_response_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"data": []})])

        assert _rows(_source("audiences")) == []


class TestEmailsPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_with_has_more_and_saves_state(self, MockSession) -> None:
        session = MockSession.return_value
        page1 = [{"id": f"e{i}", "created_at": "2026-01-01T00:00:00Z"} for i in range(2)]
        page2 = [{"id": f"e{i}", "created_at": "2026-01-01T00:00:00Z"} for i in range(2, 4)]
        snapshots = _wire(
            session,
            [
                _response({"data": page1, "has_more": True}),
                _response({"data": page2, "has_more": False}),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("emails", manager))

        assert [r["id"] for r in rows] == ["e0", "e1", "e2", "e3"]
        assert session.send.call_count == 2
        # The `after` cursor advances from the last row's id of the previous page.
        assert "after" not in snapshots[0][1]
        assert snapshots[0][1]["limit"] == 100
        assert snapshots[1][1]["after"] == "e1"
        # First page is not terminal -> save next cursor; second page (has_more=False) -> no save.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == ResendResumeConfig(next_cursor="e1")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"data": [{"id": "e42"}], "has_more": False})])

        manager = _make_manager(ResendResumeConfig(next_cursor="e41"))
        rows = _rows(_source("emails", manager))

        assert [r["id"] for r in rows] == ["e42"]
        assert snapshots[0][1]["after"] == "e41"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_when_has_more_false(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"data": [{"id": "e1"}], "has_more": False})])

        manager = _make_manager()
        _rows(_source("emails", manager))

        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_raises_when_empty_page_with_has_more_true(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"data": [], "has_more": True})])

        with pytest.raises(ValueError, match="empty page but has_more=True"):
            _rows(_source("emails"))


class TestContactsFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fanout_injects_audience_id_and_checkpoints(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response({"data": [{"id": "aud_1"}, {"id": "aud_2"}]}),  # audiences
                _response({"data": [{"id": "c1", "email": "a@example.com"}]}),  # aud_1 contacts
                _response({"data": [{"id": "c2", "email": "b@example.com"}]}),  # aud_2 contacts
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("contacts", manager))

        assert rows == [
            {"id": "c1", "email": "a@example.com", "_audience_id": "aud_1"},
            {"id": "c2", "email": "b@example.com", "_audience_id": "aud_2"},
        ]
        assert snapshots[0][0] == f"{RESEND_BASE_URL}/audiences"
        assert snapshots[1][0] == f"{RESEND_BASE_URL}/audiences/aud_1/contacts"
        assert snapshots[2][0] == f"{RESEND_BASE_URL}/audiences/aud_2/contacts"
        # After finishing aud_1 a checkpoint marks its path completed, so a crash resumes on aud_2.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert any(
            state.fanout_state is not None
            and any("audiences/aud_1/contacts" in p for p in state.fanout_state["completed"])
            for state in saved
        )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fanout_resumes_past_completed_parents(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response({"data": [{"id": "aud_1"}, {"id": "aud_2"}, {"id": "aud_3"}]}),  # audiences re-fetched
                _response({"data": [{"id": "c3"}]}),  # aud_3 only
            ],
        )

        manager = _make_manager(
            ResendResumeConfig(
                fanout_state={
                    "completed": ["/audiences/aud_1/contacts", "/audiences/aud_2/contacts"],
                    "current": None,
                    "child_state": None,
                }
            )
        )
        rows = _rows(_source("contacts", manager))

        assert [r["id"] for r in rows] == ["c3"]
        # audiences list + aud_3 contacts only; completed parents are skipped.
        assert session.send.call_count == 2
        assert snapshots[1][0] == f"{RESEND_BASE_URL}/audiences/aud_3/contacts"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fanout_full_resync_when_completed_parent_absent(self, MockSession) -> None:
        # If the completed audience no longer exists (e.g. deleted between syncs) no current parent
        # matches the stale path, so every present audience is fetched — no silent data loss.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({"data": [{"id": "aud_1"}, {"id": "aud_2"}]}),
                _response({"data": [{"id": "c1"}]}),
                _response({"data": [{"id": "c2"}]}),
            ],
        )

        manager = _make_manager(
            ResendResumeConfig(
                fanout_state={"completed": ["/audiences/aud_deleted/contacts"], "current": None, "child_state": None}
            )
        )
        rows = _rows(_source("contacts", manager))

        assert sorted(r["_audience_id"] for r in rows) == ["aud_1", "aud_2"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_pre_migration_resume_state_starts_fresh(self, MockSession) -> None:
        # An old-shape bookmark (last_completed_parent_id, no fanout_state) can't be translated into
        # the framework's completed/current map — the fan-out restarts from the first audience.
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response({"data": [{"id": "aud_1"}, {"id": "aud_2"}]}),
                _response({"data": [{"id": "c1"}]}),
                _response({"data": [{"id": "c2"}]}),
            ],
        )

        manager = _make_manager(ResendResumeConfig(last_completed_parent_id="aud_2"))
        rows = _rows(_source("contacts", manager))

        assert sorted(r["_audience_id"] for r in rows) == ["aud_1", "aud_2"]
        assert snapshots[1][0] == f"{RESEND_BASE_URL}/audiences/aud_1/contacts"


class TestRetryable:
    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_429_retries_until_success(self, MockSession, _mock_sleep) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({}, status_code=429),
                _response({"data": [{"id": "a1"}]}),
            ],
        )

        rows = _rows(_source("audiences"))

        assert [r["id"] for r in rows] == ["a1"]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_401_does_not_retry_and_raises(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"message": "unauthorized"}, status_code=401)])

        with pytest.raises(Exception):
            _rows(_source("audiences"))

        assert session.send.call_count == 1


class TestResumeConfigCompatibility:
    def test_old_saved_state_still_parses(self) -> None:
        # ResumableSourceManager._load_json does dataclass(**saved) — state saved by the
        # pre-framework implementation must keep loading after the migration.
        state = ResendResumeConfig(**cast("dict[str, Any]", {"next_cursor": "e1", "last_completed_parent_id": "aud_2"}))
        assert state.next_cursor == "e1"
        assert state.last_completed_parent_id == "aud_2"
        assert state.fanout_state is None


class TestSourceResponseShape:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _source(endpoint)

        config = RESEND_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"
        assert response.partition_keys == [config.partition_key]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [(200, True), (401, False), (403, False), (500, False)],
    )
    @mock.patch(RESEND_SESSION_PATCH)
    def test_status_mapping(self, mock_session, status_code: int, expected: bool) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)

        assert validate_credentials("re_test") is expected

        url = mock_session.return_value.get.call_args.args[0]
        assert url == f"{RESEND_BASE_URL}/domains"
        headers = mock_session.return_value.get.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer re_test"

    @mock.patch(RESEND_SESSION_PATCH)
    def test_network_error_returns_false(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("re_test") is False
