import json
from datetime import UTC, datetime
from typing import Any

from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.front.front import (
    FrontResumeConfig,
    _build_initial_params,
    _resolve_after_value,
    _to_unix_seconds,
    front_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.front.settings import FRONT_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the front module.
FRONT_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.front.front.make_tracked_session"
)


def _response(
    json_body: dict[str, Any] | None = None,
    *,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp.headers["Content-Type"] = "application/json"
    if headers:
        resp.headers.update(headers)
    resp._content = json.dumps(json_body or {}).encode()
    return resp


def _make_manager(resume_state: FrontResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's URL + params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
    request is prepared instead of inspecting the final state.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestToUnixSeconds:
    def test_aware_datetime(self) -> None:
        dt = datetime(2023, 1, 1, tzinfo=UTC)
        assert _to_unix_seconds(dt) == dt.timestamp()

    def test_naive_datetime_assumed_utc(self) -> None:
        assert _to_unix_seconds(datetime(2023, 1, 1)) == datetime(2023, 1, 1, tzinfo=UTC).timestamp()

    @parameterized.expand([("int", 1700000000), ("float", 1700000000.123)])
    def test_numeric_passthrough(self, _name: str, value: Any) -> None:
        assert _to_unix_seconds(value) == value


class TestResolveAfterValue:
    def test_not_incremental_returns_none(self) -> None:
        assert _resolve_after_value(FRONT_ENDPOINTS["events"], False, 1700000000) is None

    def test_last_value_used(self) -> None:
        assert _resolve_after_value(FRONT_ENDPOINTS["events"], True, 1700000000) == 1700000000

    def test_lookback_used_when_no_last_value(self) -> None:
        result = _resolve_after_value(FRONT_ENDPOINTS["events"], True, None)
        # events has a 365-day lookback, so a float timestamp in the past is returned
        assert isinstance(result, float)
        assert result < datetime.now(UTC).timestamp()

    def test_no_lookback_no_last_value_returns_none(self) -> None:
        assert _resolve_after_value(FRONT_ENDPOINTS["contacts"], True, None) is None


class TestBuildInitialParams:
    def test_events_incremental_sets_q_after(self) -> None:
        params = _build_initial_params(FRONT_ENDPOINTS["events"], True, 1700000000)
        assert params["q[after]"] == 1700000000
        assert params["limit"] == 15
        assert params["sort_by"] == "created_at"
        assert params["sort_order"] == "asc"

    def test_events_non_incremental_omits_q_after(self) -> None:
        params = _build_initial_params(FRONT_ENDPOINTS["events"], False, None)
        assert "q[after]" not in params

    def test_tags_full_refresh_params(self) -> None:
        params = _build_initial_params(FRONT_ENDPOINTS["tags"], False, None)
        assert params == {"limit": 100, "sort_by": "id", "sort_order": "asc"}

    def test_teammates_sends_no_params(self) -> None:
        assert _build_initial_params(FRONT_ENDPOINTS["teammates"], False, None) == {}


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("unauthorized", 401, True, False),
            ("forbidden_with_scope", 403, True, False),
            ("forbidden_without_scope", 403, False, True),
            ("ok", 200, True, True),
            ("not_found_token_valid", 404, False, True),
        ]
    )
    @mock.patch(FRONT_SESSION_PATCH)
    def test_status_mapping(
        self, _name: str, status: int, require_scope: bool, expected_ok: bool, mock_session: mock.MagicMock
    ) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        ok, _msg = validate_credentials("tok", "/teammates", require_scope=require_scope)
        assert ok is expected_ok

    @mock.patch(FRONT_SESSION_PATCH)
    def test_connection_error_fails(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        ok, msg = validate_credentials("tok", "/teammates", require_scope=False)
        assert ok is False
        assert msg is not None


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_and_saves_state(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        next_url = "https://api2.frontapp.com/events?page_token=p2"
        snapshots = _wire(
            session,
            [
                _response({"_results": [{"id": "evt_1"}], "_pagination": {"next": next_url}}),
                _response({"_results": [{"id": "evt_2"}], "_pagination": {"next": None}}),
            ],
        )
        manager = _make_manager()

        rows = _rows(front_source("tok", "events", team_id=1, job_id="j", resumable_source_manager=manager))

        assert [r["id"] for r in rows] == ["evt_1", "evt_2"]
        # Checkpoint saved after the first page (points at the next link); the null next ends it.
        manager.save_state.assert_called_once_with(FrontResumeConfig(next_url=next_url))
        # The self-contained next link drives page 2 (original query params dropped).
        assert snapshots[1]["url"] == next_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        resume_url = "https://api2.frontapp.com/events?page_token=resume"
        snapshots = _wire(session, [_response({"_results": [{"id": "evt_9"}], "_pagination": {"next": None}})])
        manager = _make_manager(FrontResumeConfig(next_url=resume_url))

        rows = _rows(front_source("tok", "events", team_id=1, job_id="j", resumable_source_manager=manager))

        assert [r["id"] for r in rows] == ["evt_9"]
        assert snapshots[0]["url"] == resume_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_does_not_terminate(self, MockSession: mock.MagicMock) -> None:
        # An empty `_results` page with a next link must keep paginating (deleted resources can
        # leave a page short without it being the last page).
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({"_results": [], "_pagination": {"next": "https://api2.frontapp.com/tags?page_token=p2"}}),
                _response({"_results": [{"id": "tag_1"}], "_pagination": {"next": None}}),
            ],
        )
        manager = _make_manager()

        rows = _rows(front_source("tok", "tags", team_id=1, job_id="j", resumable_source_manager=manager))

        assert [r["id"] for r in rows] == ["tag_1"]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retries_on_429(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(status_code=429, headers={"retry-after": "0"}),
                _response({"_results": [{"id": "tag_1"}], "_pagination": {"next": None}}),
            ],
        )
        manager = _make_manager()

        rows = _rows(front_source("tok", "tags", team_id=1, job_id="j", resumable_source_manager=manager))

        assert [r["id"] for r in rows] == ["tag_1"]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_events_incremental_sends_q_after(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"_results": [{"id": "evt_1"}], "_pagination": {"next": None}})])
        manager = _make_manager()

        _rows(
            front_source(
                "tok",
                "events",
                team_id=1,
                job_id="j",
                resumable_source_manager=manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=1700000000,
            )
        )

        assert snapshots[0]["params"]["q[after]"] == 1700000000
        assert snapshots[0]["params"]["limit"] == 15


class TestFrontSourceResponse:
    @parameterized.expand(
        [
            ("events", "emitted_at", "week", "asc"),
            ("conversations", "created_at", "month", "asc"),
            ("accounts", "created_at", "month", "asc"),
            ("tags", "created_at", "month", "asc"),
        ]
    )
    def test_partitioned_endpoints(
        self, endpoint: str, partition_key: str, partition_format: str, sort_mode: str
    ) -> None:
        response = front_source("tok", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager())
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [partition_key]
        assert response.partition_format == partition_format
        assert response.sort_mode == sort_mode

    @parameterized.expand([("contacts",), ("teammates",), ("inboxes",), ("channels",), ("teams",)])
    def test_non_partitioned_endpoints(self, endpoint: str) -> None:
        response = front_source("tok", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager())
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None
