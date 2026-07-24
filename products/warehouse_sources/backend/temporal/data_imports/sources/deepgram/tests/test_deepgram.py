import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.deepgram import deepgram as deepgram_mod
from products.warehouse_sources.backend.temporal.data_imports.sources.deepgram.deepgram import (
    DEEPGRAM_BASE_URL,
    DeepgramResumeConfig,
    _format_start_value,
    _make_child_map,
    _redact_url_userinfo,
    deepgram_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.deepgram.settings import DEEPGRAM_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the deepgram module.
DEEPGRAM_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.deepgram.deepgram.make_tracked_session"
)

# The framework injects the parent project id under this key before the child data_map lifts it out.
PARENT_KEY = "_projects_project_id"


def _response(body: Any) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: DeepgramResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[tuple[str, dict[str, Any]]]:
    """Wire a mock session; capture each request's (url, params) AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so snapshot a copy when each request
    is prepared instead of inspecting it after the run.
    """
    session.headers = {}
    snapshots: list[tuple[str, dict[str, Any]]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append((request.url, dict(request.params or {})))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return deepgram_source(
        api_key="token", endpoint=endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs
    )


class TestFormatStartValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_start_value(value) == expected

    def test_no_plus_zero_offset(self) -> None:
        # A +00:00 offset (isoformat default) is not the ISO shape we send; assert we emit the Z form.
        assert "+00:00" not in _format_start_value(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))

    @freeze_time("2026-06-15T12:00:00Z")
    def test_future_datetime_clamped_to_now(self) -> None:
        # Asking for requests created after "now" is pointless; cap it so we don't skip the window.
        assert _format_start_value(datetime(2027, 1, 1, tzinfo=UTC)) == "2026-06-15T12:00:00.000Z"


class TestChildMap:
    def test_injects_project_id(self) -> None:
        row = _make_child_map(DEEPGRAM_ENDPOINTS["members"])({PARENT_KEY: "proj-1", "member_id": "m1"})
        assert row["project_id"] == "proj-1"
        assert row["member_id"] == "m1"
        assert PARENT_KEY not in row

    def test_flattens_nested_key_to_root(self) -> None:
        # /keys nests the key under "api_key"; api_key_id must land at the row root or the composite
        # primary key can't be built and the delta merge multi-matches duplicate rows.
        row = _make_child_map(DEEPGRAM_ENDPOINTS["keys"])(
            {PARENT_KEY: "proj-1", "api_key": {"api_key_id": "k1", "comment": "ci"}, "member": {"email": "a@b.co"}}
        )
        assert row["api_key_id"] == "k1"
        assert row["comment"] == "ci"
        assert row["project_id"] == "proj-1"
        assert row["member"] == {"email": "a@b.co"}
        assert "api_key" not in row

    @parameterized.expand(
        [
            ("basic_auth", "https://user:pass@hooks.example.com/cb", "https://hooks.example.com/cb"),
            ("no_creds", "https://hooks.example.com/cb", "https://hooks.example.com/cb"),
            ("not_a_url", "not-a-url", "not-a-url"),
        ]
    )
    def test_redacts_callback_userinfo(self, _name: str, callback: str, expected: str) -> None:
        # A callback URL can embed Basic Auth creds; they must not reach the warehouse.
        row = _make_child_map(DEEPGRAM_ENDPOINTS["requests"])(
            {PARENT_KEY: "proj-1", "request_id": "r1", "callback": callback}
        )
        assert row["callback"] == expected

    def test_missing_primary_key_raises(self) -> None:
        # A row missing request_id would let the merge overwrite unrelated rows; fail instead of emit.
        with pytest.raises(ValueError, match="request_id"):
            _make_child_map(DEEPGRAM_ENDPOINTS["requests"])({PARENT_KEY: "proj-1", "created": "2026-01-01"})


class TestRedactUrlUserinfo:
    def test_malformed_url_passthrough(self) -> None:
        assert _redact_url_userinfo("http://[") == "http://["


class TestProjectsEndpoint:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_yields_projects_without_fan_out(self, MockSession) -> None:
        session = MockSession.return_value
        projects = [{"project_id": "p1"}, {"project_id": "p2"}]
        snapshots = _wire(session, [_response({"projects": projects})])

        rows = _rows(_source("projects", _make_manager()))

        assert rows == projects
        # projects is its own endpoint — one request, and it must NOT fan out per project.
        assert len(snapshots) == 1
        assert snapshots[0][0] == f"{DEEPGRAM_BASE_URL}/projects"


class TestFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fans_out_over_projects_and_injects_project_id(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response({"projects": [{"project_id": "p1"}, {"project_id": "p2"}]}),
                _response({"members": [{"member_id": "m1"}]}),
                _response({"members": [{"member_id": "m2"}]}),
            ],
        )

        rows = _rows(_source("members", _make_manager()))

        assert [(r["member_id"], r["project_id"]) for r in rows] == [("m1", "p1"), ("m2", "p2")]
        assert [url for url, _ in snapshots] == [
            f"{DEEPGRAM_BASE_URL}/projects",
            f"{DEEPGRAM_BASE_URL}/projects/p1/members",
            f"{DEEPGRAM_BASE_URL}/projects/p2/members",
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_flattens_keys_endpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({"projects": [{"project_id": "p1"}]}),
                _response({"api_keys": [{"api_key": {"api_key_id": "k1"}, "member": {"email": "a@b.co"}}]}),
            ],
        )

        rows = _rows(_source("keys", _make_manager()))

        assert rows == [{"api_key_id": "k1", "member": {"email": "a@b.co"}, "project_id": "p1"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_project_without_id_is_skipped(self, MockSession) -> None:
        session = MockSession.return_value
        # A project row missing project_id can't be fanned out; the old code skipped it, so no
        # /projects//members request is made for it.
        snapshots = _wire(
            session,
            [
                _response({"projects": [{"name": "no-id"}, {"project_id": "p2"}]}),
                _response({"members": [{"member_id": "m2"}]}),
            ],
        )

        rows = _rows(_source("members", _make_manager()))

        assert [r["project_id"] for r in rows] == ["p2"]
        assert [url for url, _ in snapshots] == [
            f"{DEEPGRAM_BASE_URL}/projects",
            f"{DEEPGRAM_BASE_URL}/projects/p2/members",
        ]


class TestRequestsPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_terminates_on_short_page(self, MockSession) -> None:
        session = MockSession.return_value
        # page size patched to 2, so a page returning fewer than 2 rows ends pagination for a project
        # without paying an extra empty-page request.
        snapshots = _wire(
            session,
            [
                _response({"projects": [{"project_id": "p1"}]}),
                _response({"requests": [{"request_id": "r1"}, {"request_id": "r2"}]}),
                _response({"requests": [{"request_id": "r3"}]}),
            ],
        )

        with mock.patch.object(deepgram_mod, "REQUESTS_PAGE_SIZE", 2):
            rows = _rows(_source("requests", _make_manager(), should_use_incremental_field=True))

        assert [r["request_id"] for r in rows] == ["r1", "r2", "r3"]
        # projects + page 0 + page 1 == 3 requests; no trailing empty page.
        assert len(snapshots) == 3
        assert snapshots[1][1]["page"] == 0
        assert snapshots[2][1]["page"] == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoint_advances_page_after_yield(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({"projects": [{"project_id": "p1"}]}),
                _response({"requests": [{"request_id": "r1"}, {"request_id": "r2"}]}),
                _response({"requests": [{"request_id": "r3"}]}),
            ],
        )
        manager = _make_manager()

        with mock.patch.object(deepgram_mod, "REQUESTS_PAGE_SIZE", 2):
            _rows(_source("requests", manager, should_use_incremental_field=True))

        # After yielding the first full page we persist the next page so a crash re-fetches page 1.
        child_pages = [
            call.args[0].fanout_state.get("child_state", {}).get("page")
            for call in manager.save_state.call_args_list
            if call.args[0].fanout_state and call.args[0].fanout_state.get("child_state")
        ]
        assert 1 in child_pages


class TestRequestsIncremental:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_start_filter_only_on_requests(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [_response({"projects": [{"project_id": "p1"}]}), _response({"requests": []})],
        )

        _rows(
            _source(
                "requests",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            )
        )

        assert snapshots[-1][1]["start"] == "2026-03-04T02:58:14.000Z"
        assert snapshots[-1][1]["limit"] == deepgram_mod.REQUESTS_PAGE_SIZE
        # The parent project enumeration carries no incremental filter.
        assert "start" not in snapshots[0][1]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_start_filter_on_full_refresh(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [_response({"projects": [{"project_id": "p1"}]}), _response({"requests": []})],
        )

        _rows(_source("requests", _make_manager(), should_use_incremental_field=False))

        assert "start" not in snapshots[-1][1]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_start_filter_when_no_cursor_yet(self, MockSession) -> None:
        session = MockSession.return_value
        # First incremental sync: no persisted watermark, so no server-side filter (full pull).
        snapshots = _wire(
            session,
            [_response({"projects": [{"project_id": "p1"}]}), _response({"requests": []})],
        )

        _rows(
            _source(
                "requests", _make_manager(), should_use_incremental_field=True, db_incremental_field_last_value=None
            )
        )

        assert "start" not in snapshots[-1][1]


class TestResume:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_skips_completed_project(self, MockSession) -> None:
        session = MockSession.return_value
        # p1 already fully synced last run — only projects (re-enumerated) and p2 are fetched.
        snapshots = _wire(
            session,
            [
                _response({"projects": [{"project_id": "p1"}, {"project_id": "p2"}]}),
                _response({"members": [{"member_id": "m2"}]}),
            ],
        )
        resume = DeepgramResumeConfig(
            fanout_state={"completed": ["/projects/p1/members"], "current": None, "child_state": None}
        )

        rows = _rows(_source("members", _make_manager(resume)))

        assert [r["member_id"] for r in rows] == ["m2"]
        assert [url for url, _ in snapshots] == [
            f"{DEEPGRAM_BASE_URL}/projects",
            f"{DEEPGRAM_BASE_URL}/projects/p2/members",
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoint_records_completed_child_path(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"projects": [{"project_id": "p1"}]}), _response({"members": [{"member_id": "m1"}]})])
        manager = _make_manager()

        _rows(_source("members", manager))

        assert manager.save_state.called
        last_saved = manager.save_state.call_args.args[0]
        assert isinstance(last_saved, DeepgramResumeConfig)
        assert last_saved.fanout_state is not None
        assert last_saved.fanout_state["completed"] == ["/projects/p1/members"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_legacy_resume_state_restarts_from_beginning(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"projects": [{"project_id": "p1"}]}), _response({"members": [{"member_id": "m1"}]})])
        # An old-format saved state (no fanout_state) parses but resumes nothing — a full re-read the
        # merge dedupes, rather than mis-mapping the old positional scope onto the new fan-out state.
        rows = _rows(_source("members", _make_manager(DeepgramResumeConfig(project_id="p1", page=3))))

        assert [r["member_id"] for r in rows] == ["m1"]


class TestSourceResponse:
    @parameterized.expand(
        [
            ("requests_is_incremental", "requests", "desc", ["project_id", "request_id"]),
            ("members_full_refresh", "members", "asc", ["project_id", "member_id"]),
            ("projects_top_level", "projects", "asc", ["project_id"]),
        ]
    )
    def test_shape(self, _name: str, endpoint: str, sort_mode: str, primary_keys: list[str]) -> None:
        response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == sort_mode

    def test_partitioned_only_when_partition_key_set(self) -> None:
        assert _source("requests", _make_manager()).partition_mode == "datetime"
        assert _source("requests", _make_manager()).partition_keys == ["created"]
        assert _source("members", _make_manager()).partition_mode is None


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_maps_to_bool(self, _name: str, status: int, expected: bool) -> None:
        with mock.patch(DEEPGRAM_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
            assert validate_credentials("token") is expected

    def test_network_error_is_false(self) -> None:
        with mock.patch(DEEPGRAM_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")
            assert validate_credentials("token") is False
