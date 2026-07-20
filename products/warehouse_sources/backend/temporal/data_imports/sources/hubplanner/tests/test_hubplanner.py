import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import HTTPError, PreparedRequest, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hubplanner.hubplanner import (
    PAGE_SIZE,
    HubPlannerResumeConfig,
    _build_request_plan,
    _format_value,
    hubplanner_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hubplanner.settings import HUBPLANNER_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the hubplanner module.
HUBPLANNER_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.hubplanner.hubplanner.make_tracked_session"
)


def _response(items: list[dict[str, Any]] | Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(items).encode()
    return resp


def _make_manager(resume_state: HubPlannerResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's method/url/params/json/auth AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so a copy is snapshotted
    when each request is prepared rather than inspected after the run.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append(
            {
                "method": request.method,
                "url": request.url,
                "params": dict(request.params or {}),
                "json": request.json,
                "auth": request.auth,
            }
        )
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestFormatValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            (
                "datetime_microseconds_truncated_to_millis",
                datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC),
                "2026-01-15T10:30:45.123Z",
            ),
            ("naive_datetime_assumed_utc", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04"),
            ("string_passthrough", "5b1977ade02d407011112222", "5b1977ade02d407011112222"),
        ]
    )
    def test_format_value(self, _name: str, value: object, expected: str) -> None:
        assert _format_value(value) == expected

    def test_datetime_has_no_plus_zero_offset(self) -> None:
        # Hub Planner expects a Z suffix, not the +00:00 offset isoformat() produces.
        assert "+00:00" not in _format_value(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))


class TestBuildRequestPlan:
    def test_full_refresh_endpoint_uses_unsorted_get(self) -> None:
        # No `sort` on full-refresh GET: an unsupported sort field would 400 the whole sync.
        method, path, body, sort_field = _build_request_plan(
            HUBPLANNER_ENDPOINTS["projects"], should_use_incremental_field=False, db_incremental_field_last_value=None
        )
        assert (method, path, body, sort_field) == ("GET", "/project", None, None)

    def test_incremental_endpoint_without_incremental_selected_uses_get(self) -> None:
        # A user syncing bookings via full refresh should hit the plain GET list, not search.
        method, path, body, sort_field = _build_request_plan(
            HUBPLANNER_ENDPOINTS["bookings"], should_use_incremental_field=False, db_incremental_field_last_value=None
        )
        assert method == "GET"
        assert path == "/booking"
        assert body is None

    def test_incremental_first_sync_posts_search_with_empty_body(self) -> None:
        # should_use_incremental_field=True but no stored watermark yet: fetch everything, sorted asc.
        method, path, body, sort_field = _build_request_plan(
            HUBPLANNER_ENDPOINTS["bookings"], should_use_incremental_field=True, db_incremental_field_last_value=None
        )
        assert (method, path, body, sort_field) == ("POST", "/booking/search", {}, "updatedDate")

    def test_incremental_with_watermark_filters_on_updated_date(self) -> None:
        method, path, body, sort_field = _build_request_plan(
            HUBPLANNER_ENDPOINTS["time_entries"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert method == "POST"
        assert path == "/timeentry/search"
        assert body == {"updatedDate": {"$gte": "2026-03-04T02:58:14.000Z"}}
        assert sort_field == "updatedDate"

    def test_search_only_endpoint_lists_via_search(self) -> None:
        # Milestones have no GET-all endpoint, so full refresh still POSTs to /milestone/search.
        method, path, body, sort_field = _build_request_plan(
            HUBPLANNER_ENDPOINTS["milestones"], should_use_incremental_field=False, db_incremental_field_last_value=None
        )
        assert (method, path, body, sort_field) == ("POST", "/milestone/search", {}, None)


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_short_page_terminates_without_saving_state(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"_id": "1"}, {"_id": "2"}])])

        manager = _make_manager()
        rows = _rows(hubplanner_source("k", "projects", team_id=1, job_id="j", resumable_source_manager=manager))

        assert [r["_id"] for r in rows] == ["1", "2"]
        assert session.send.call_count == 1
        # A short first page is the last page, so there's no next page to checkpoint.
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_short_page_and_saves_state_after_each_full_page(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"_id": str(i)} for i in range(PAGE_SIZE)]
        short_page = [{"_id": "last"}]
        snaps = _wire(session, [_response(full_page), _response(short_page)])

        manager = _make_manager()
        rows = _rows(hubplanner_source("k", "projects", team_id=1, job_id="j", resumable_source_manager=manager))

        assert len(rows) == PAGE_SIZE + 1
        assert [s["params"]["page"] for s in snaps] == [0, 1]
        assert [s["params"]["limit"] for s in snaps] == [PAGE_SIZE, PAGE_SIZE]
        # State saved once after the first (full) page points at page 1; the short page ends the loop.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == HubPlannerResumeConfig(page=1)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_response([{"_id": "x"}])])

        manager = _make_manager(HubPlannerResumeConfig(page=3))
        _rows(hubplanner_source("k", "projects", team_id=1, job_id="j", resumable_source_manager=manager))

        assert snaps[0]["params"]["page"] == 3

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        manager = _make_manager()
        rows = _rows(hubplanner_source("k", "projects", team_id=1, job_id="j", resumable_source_manager=manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_sync_posts_search_body(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_response([{"_id": "1"}])])

        manager = _make_manager()
        _rows(
            hubplanner_source(
                "k",
                "bookings",
                team_id=1,
                job_id="j",
                resumable_source_manager=manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            )
        )

        assert snaps[0]["method"] == "POST"
        assert snaps[0]["url"].endswith("/booking/search")
        assert snaps[0]["json"] == {"updatedDate": {"$gte": "2026-03-04T00:00:00.000Z"}}
        assert snaps[0]["params"]["sort"] == "updatedDate"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_get_sends_no_body_and_no_sort(self, MockSession) -> None:
        session = MockSession.return_value
        snaps = _wire(session, [_response([{"_id": "1"}])])

        _rows(hubplanner_source("k", "projects", team_id=1, job_id="j", resumable_source_manager=_make_manager()))

        assert snaps[0]["method"] == "GET"
        assert snaps[0]["json"] is None
        assert "sort" not in snaps[0]["params"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_response_fails_loud(self, MockSession) -> None:
        # Every list/search endpoint returns a bare JSON array; a stray object means the response
        # shape changed, so fail loud rather than syncing a garbage row.
        session = MockSession.return_value
        _wire(session, [_response({"message": "unexpected"})])

        with pytest.raises(ValueError, match="list response body"):
            _rows(hubplanner_source("k", "projects", team_id=1, job_id="j", resumable_source_manager=_make_manager()))


class TestAuth:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_authorization_header_is_raw_key_without_bearer_prefix(self, MockSession) -> None:
        # The API key rides raw on the Authorization header (Hub Planner uses no Bearer prefix).
        session = MockSession.return_value
        snaps = _wire(session, [_response([{"_id": "1"}])])

        _rows(
            hubplanner_source(
                "my-secret-key", "projects", team_id=1, job_id="j", resumable_source_manager=_make_manager()
            )
        )

        prepared = PreparedRequest()
        prepared.headers = {}
        snaps[0]["auth"](prepared)
        assert prepared.headers["Authorization"] == "my-secret-key"
        assert "Bearer" not in prepared.headers["Authorization"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_session_built_with_api_key_redacted(self, MockSession) -> None:
        # The tracked session must be given the key as a redact value — Hub Planner echoes it back
        # in auth-error bodies, so it could otherwise leak into captured samples.
        _wire(MockSession.return_value, [_response([{"_id": "1"}])])

        _rows(
            hubplanner_source(
                "my-secret-key", "projects", team_id=1, job_id="j", resumable_source_manager=_make_manager()
            )
        )

        assert MockSession.call_args.kwargs["redact_values"] == ("my-secret-key",)


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch("tenacity.nap.time.sleep", lambda *_: None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_raises_retryable_error(self, _name: str, status_code: int, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], status_code=status_code) for _ in range(5)])

        with pytest.raises(RESTClientRetryableError):
            _rows(hubplanner_source("k", "projects", team_id=1, job_id="j", resumable_source_manager=_make_manager()))

        assert session.send.call_count == 5

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_auth_error_raises_http_error(self, MockSession) -> None:
        # A 403 is non-retryable (get_non_retryable_errors maps it) and surfaces as an HTTPError.
        session = MockSession.return_value
        _wire(session, [_response({"error": "OAUTH_ERROR_TOKEN_NOT_VALID"}, status_code=403)])

        with pytest.raises(HTTPError):
            _rows(hubplanner_source("k", "projects", team_id=1, job_id="j", resumable_source_manager=_make_manager()))


class TestSourceResponse:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_partitioned_endpoint_sets_datetime_partitioning(self, MockSession) -> None:
        response = hubplanner_source("k", "bookings", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        assert response.name == "bookings"
        assert response.primary_keys == ["_id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["createdDate"]
        assert response.sort_mode == "asc"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_endpoint_without_partition_key_has_no_partitioning(self, MockSession) -> None:
        # Vacations carry no creation timestamp, so they aren't partitioned.
        response = hubplanner_source("k", "vacations", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        assert response.partition_mode is None
        assert response.partition_keys is None


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("forbidden", 403, False), ("unauthorized", 401, False)])
    @mock.patch(HUBPLANNER_SESSION_PATCH)
    def test_status_maps_to_validity(self, _name: str, status_code: int, expected: bool, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("some-key") is expected

    @mock.patch(HUBPLANNER_SESSION_PATCH)
    def test_network_error_is_invalid(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("some-key") is False

    @mock.patch(HUBPLANNER_SESSION_PATCH)
    def test_validate_credentials_redacts_api_key(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("my-secret-key")
        assert mock_session.call_args.kwargs["redact_values"] == ("my-secret-key",)
