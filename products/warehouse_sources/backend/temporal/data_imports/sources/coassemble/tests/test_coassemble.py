import json
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.coassemble import coassemble
from products.warehouse_sources.backend.temporal.data_imports.sources.coassemble.coassemble import (
    COASSEMBLE_BASE_URL,
    PAGE_SIZE,
    CoassembleResumeConfig,
    coassemble_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coassemble.settings import (
    COASSEMBLE_ENDPOINTS,
    ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the coassemble module.
COASSEMBLE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.coassemble.coassemble.make_tracked_session"
)


def _response(body: Any, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    return resp


def _page(prefix: str, start: int, count: int) -> list[dict[str, Any]]:
    return [{"id": f"{prefix}-{i}"} for i in range(start, start + count)]


def _make_manager(resume_state: CoassembleResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list capturing each request's url/params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {}), "auth": request.auth})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(endpoint: str, manager: mock.MagicMock) -> list[dict[str, Any]]:
    source_response = coassemble_source(
        workspace_id="ws-1",
        api_key="sk-key",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )
    return [row for page in source_response.items() for row in page]


class TestListEndpointPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_first_page_makes_one_request_and_no_checkpoint(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response(_page("c", 0, 2))])

        manager = _make_manager()
        rows = _rows("courses", manager)

        # A short page marks the end of the collection — no extra empty-page request is paid.
        assert rows == _page("c", 0, 2)
        assert session.send.call_count == 1
        assert snapshots[0]["url"] == f"{COASSEMBLE_BASE_URL}/courses"
        assert snapshots[0]["params"] == {"page": 0, "length": PAGE_SIZE}
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_page_advances_until_short_page(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response(_page("c", 0, PAGE_SIZE)), _response(_page("c", PAGE_SIZE, 3))])

        manager = _make_manager()
        rows = _rows("courses", manager)

        assert len(rows) == PAGE_SIZE + 3
        assert [s["params"]["page"] for s in snapshots] == [0, 1]
        # Checkpoint saved after the first full page (points at the next page); the short page ends it.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == CoassembleResumeConfig(next_page=1)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response(_page("c", 0, 1))])

        rows = _rows("courses", _make_manager(CoassembleResumeConfig(next_page=2)))

        # Pages 0 and 1 must never be re-fetched on resume.
        assert rows == _page("c", 0, 1)
        assert session.send.call_count == 1
        assert snapshots[0]["params"]["page"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        manager = _make_manager()
        rows = _rows("courses", manager)

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @parameterized.expand([("string", "nope"), ("object_without_list", {"count": 1})])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_fails_loudly(self, _name: str, body: Any, MockSession: mock.MagicMock) -> None:
        # List endpoints document a plain JSON array; any other 200 body means the response shape
        # changed — fail loud instead of silently syncing 0 rows.
        session = MockSession.return_value
        _wire(session, [_response(body)])

        with pytest.raises(ValueError, match="Required a list response body"):
            _rows("courses", _make_manager())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_raise_for_status(self, _name: str, status: int, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"error": "denied"}, status=status)])

        with pytest.raises(requests.HTTPError):
            _rows("courses", _make_manager())

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_credential_travels_via_framework_auth(self, MockSession: mock.MagicMock) -> None:
        # Coassemble rejects standard schemes (Bearer etc.) with "Invalid Authorization header"; the
        # documented format is COASSEMBLE:<workspace_id>:<api_key>, sent via framework api_key auth
        # (not a hand-built header) so the secret is value-redacted from logs.
        session = MockSession.return_value
        snapshots = _wire(session, [_response(_page("c", 0, 1))])

        _rows("courses", _make_manager())

        auth = snapshots[0]["auth"]
        assert auth.api_key == "COASSEMBLE:ws-1:sk-key"
        assert auth.name == "Authorization"
        assert auth.location == "header"
        assert session.headers.get("Accept") == "application/json"


class TestTrackingFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_iterates_courses_and_injects_course_id(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": 11}, {"id": 22}]),
                _response([{"id": 1}, {"id": 2}]),
                _response([{"id": 3}]),
            ],
        )

        manager = _make_manager()
        rows = _rows("course_trackings", manager)

        # Tracking rows don't reference their course, so the parent id is stamped in (also part of
        # the primary key — see settings.py).
        assert rows == [
            {"id": 1, "course_id": 11},
            {"id": 2, "course_id": 11},
            {"id": 3, "course_id": 22},
        ]
        assert [s["url"] for s in snapshots] == [
            f"{COASSEMBLE_BASE_URL}/courses",
            f"{COASSEMBLE_BASE_URL}/trackings?id=11",
            f"{COASSEMBLE_BASE_URL}/trackings?id=22",
        ]
        # Each course lands in `completed` once its pages are exhausted.
        assert manager.save_state.call_args_list[-1].args[0] == CoassembleResumeConfig(
            fanout_state={"completed": ["/trackings?id=11", "/trackings?id=22"], "current": None, "child_state": None}
        )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_within_a_course_and_checkpoints(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": 11}]),
                _response([{"id": i} for i in range(PAGE_SIZE)]),
                _response([{"id": PAGE_SIZE}]),
            ],
        )

        manager = _make_manager()
        rows = _rows("course_trackings", manager)

        assert len(rows) == PAGE_SIZE + 1
        tracking_snapshots = [s for s in snapshots if "/trackings" in s["url"]]
        assert [s["params"]["page"] for s in tracking_snapshots] == [0, 1]
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        # Mid-course: the in-progress course path and its next page are checkpointed so a crash
        # resumes into the same course at the saved page.
        assert saved[0] == CoassembleResumeConfig(
            fanout_state={"completed": [], "current": "/trackings?id=11", "child_state": {"page": 1}}
        )
        # Course finished: it lands in `completed` so a restart skips it.
        assert saved[-1] == CoassembleResumeConfig(
            fanout_state={"completed": ["/trackings?id=11"], "current": None, "child_state": None}
        )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_by_skipping_completed_courses(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": 11}, {"id": 22}]),
                _response([{"id": 9}]),
            ],
        )

        manager = _make_manager(
            CoassembleResumeConfig(
                fanout_state={"completed": ["/trackings?id=11"], "current": None, "child_state": None}
            )
        )
        rows = _rows("course_trackings", manager)

        assert rows == [{"id": 9, "course_id": 22}]
        assert snapshots[1]["url"] == f"{COASSEMBLE_BASE_URL}/trackings?id=22"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_pre_migration_bookmark_resumes_exactly(self, MockSession: mock.MagicMock) -> None:
        # An old-shape bookmark (completed_course_ids + current_course_id + next_page) is translated
        # into the framework fan-out state: completed courses are skipped and the in-progress course
        # resumes at the saved page.
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": 11}, {"id": 22}]),
                _response([{"id": 9}]),
            ],
        )

        manager = _make_manager(CoassembleResumeConfig(next_page=1, completed_course_ids=[11], current_course_id=22))
        rows = _rows("course_trackings", manager)

        assert rows == [{"id": 9, "course_id": 22}]
        tracking_snapshots = [s for s in snapshots if "/trackings" in s["url"]]
        assert [s["url"] for s in tracking_snapshots] == [f"{COASSEMBLE_BASE_URL}/trackings?id=22"]
        assert tracking_snapshots[0]["params"]["page"] == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_page_cap_stops_runaway_course(self, MockSession: mock.MagicMock) -> None:
        with mock.patch.object(coassemble, "MAX_TRACKING_PAGES_PER_COURSE", 2):
            session = MockSession.return_value
            # Every trackings page is full, so without the cap this would page forever.
            _wire(
                session,
                [
                    _response([{"id": 11}]),
                    _response([{"id": i} for i in range(PAGE_SIZE)]),
                    _response([{"id": i} for i in range(PAGE_SIZE)]),
                ],
            )

            rows = _rows("course_trackings", _make_manager())

        assert len(rows) == 2 * PAGE_SIZE
        assert session.send.call_count == 3  # 1 courses page + 2 capped trackings pages


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Coassemble workspace ID or API key"),
            ("forbidden", 403, False, "Invalid Coassemble workspace ID or API key"),
            ("server_error", 500, False, "Coassemble returned HTTP 500"),
        ]
    )
    def test_status_maps_to_result(
        self, _name: str, status: int, expected_ok: bool, expected_message: str | None
    ) -> None:
        with mock.patch(COASSEMBLE_SESSION_PATCH) as make_session:
            session = mock.MagicMock()
            session.get.return_value = mock.MagicMock(status_code=status)
            make_session.return_value = session
            assert validate_credentials("ws-1", "sk-key") == (expected_ok, expected_message)

    def test_connection_error_is_inconclusive(self) -> None:
        with mock.patch(COASSEMBLE_SESSION_PATCH) as make_session:
            session = mock.MagicMock()
            session.get.side_effect = requests.ConnectionError("boom")
            make_session.return_value = session
            ok, message = validate_credentials("ws-1", "sk-key")
        assert ok is False
        assert message is not None and "Could not connect to Coassemble" in message

    def test_probe_sends_vendor_authorization_scheme(self) -> None:
        with mock.patch(COASSEMBLE_SESSION_PATCH) as make_session:
            session = mock.MagicMock()
            session.get.return_value = mock.MagicMock(status_code=200)
            make_session.return_value = session
            validate_credentials("ws-1", "sk-key")
            headers = session.get.call_args.kwargs["headers"]
            assert headers["Authorization"] == "COASSEMBLE:ws-1:sk-key"


class TestResumeStateCompatibility:
    def test_pre_migration_saved_state_still_parses(self) -> None:
        # ResumableSourceManager._load_json does `dataclass(**saved)` — state saved before the
        # framework migration must still construct.
        assert CoassembleResumeConfig(
            **{"next_page": 3, "completed_course_ids": [11], "current_course_id": 22}
        ) == CoassembleResumeConfig(next_page=3, completed_course_ids=[11], current_course_id=22)


class TestCoassembleSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = coassemble_source(
            workspace_id="ws-1",
            api_key="sk-key",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
        )
        assert response.name == endpoint
        assert response.primary_keys == COASSEMBLE_ENDPOINTS[endpoint].primary_keys
        # Trackings/courses only guarantee mutable progress timestamps, so we don't partition.
        assert response.partition_mode is None

    def test_trackings_key_includes_injected_course_id(self) -> None:
        # Tracking rows are aggregated across every course; without the parent id in the key,
        # per-course id collisions would seed duplicate rows that every later merge multi-matches.
        assert COASSEMBLE_ENDPOINTS["course_trackings"].primary_keys == ["course_id", "id"]

    def test_clients_and_users_use_identifier_keys(self) -> None:
        # Neither object carries a numeric `id` in the API response.
        assert COASSEMBLE_ENDPOINTS["clients"].primary_keys == ["clientIdentifier"]
        assert COASSEMBLE_ENDPOINTS["users"].primary_keys == ["identifier"]
