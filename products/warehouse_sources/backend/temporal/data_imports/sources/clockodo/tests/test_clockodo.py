import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
import time_machine
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.clockodo.clockodo import (
    EXTERNAL_APPLICATION_NAME,
    ClockodoResumeConfig,
    _endpoint_params,
    _format_z,
    _work_time_windows,
    clockodo_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clockodo.settings import (
    CLOCKODO_API_VERSION_V2,
    CLOCKODO_API_VERSION_V3,
    CLOCKODO_ENDPOINTS_V2,
    CLOCKODO_SUPPORTED_VERSIONS,
    ENDPOINTS,
    USER_REPORTS_FIRST_YEAR,
    WORK_TIMES_FIRST_DATE,
    WORK_TIMES_WINDOW_DAYS,
    endpoints_for_version,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the clockodo module.
CLOCKODO_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.clockodo.clockodo.make_tracked_session"
)


def _response(
    items: list[dict[str, Any]] | None,
    *,
    data_key: str = "customers",
    count_pages: int | None = None,
    drop_data: bool = False,
) -> Response:
    body: dict[str, Any] = {}
    if count_pages is not None:
        body["paging"] = {"count_pages": count_pages}
    if not drop_data:
        body[data_key] = items or []
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: ClockodoResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], list[Any], list[str]]:
    """Wire a mock session; capture each request's params, auth, and URL AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []
    auth_snapshots: list[Any] = []
    url_snapshots: list[str] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        auth_snapshots.append(request.auth)
        url_snapshots.append(request.url)
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots, auth_snapshots, url_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock, api_version: str = CLOCKODO_API_VERSION_V2):
    return clockodo_source(
        api_user="me@example.com",
        api_key="key123",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        api_version=api_version,
    )


class TestFormatZ:
    @parameterized.expand(
        [
            ("utc", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("with_micros_truncated", datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30:45Z"),
        ]
    )
    def test_format_z(self, _name: str, value: datetime, expected: str) -> None:
        assert _format_z(value) == expected


class TestEndpointParams:
    @time_machine.travel("2026-06-29T12:00:00Z", tick=False)
    def test_entries_requires_time_window(self) -> None:
        params = _endpoint_params("entries", CLOCKODO_ENDPOINTS_V2["entries"])
        # Listing entries without a time range is rejected by the API.
        assert params["time_since"] == "2000-01-01T00:00:00Z"
        # time_until is pushed a year past now to also capture planned (future) entries.
        assert params["time_until"] == "2027-06-29T12:00:00Z"

    @parameterized.expand([("customers",), ("projects",), ("services",), ("users",)])
    def test_non_entries_have_no_time_window(self, endpoint: str) -> None:
        params = _endpoint_params(endpoint, CLOCKODO_ENDPOINTS_V2[endpoint])
        assert "time_since" not in params
        assert "time_until" not in params


class TestHeadersAndAuth:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_identification_headers_and_api_key_auth(self, MockSession) -> None:
        session = MockSession.return_value
        _params, auths, _urls = _wire(session, [_response([{"id": 1}], count_pages=1)])

        _rows(_source("customers", _make_manager()))

        # The API rejects every request without the identification headers.
        assert session.headers["X-ClockodoApiUser"] == "me@example.com"
        assert session.headers["X-Clockodo-External-Application"] == f"{EXTERNAL_APPLICATION_NAME};me@example.com"
        # The API key travels via the framework auth config so its value is redacted from logs.
        auth = auths[0]
        assert isinstance(auth, APIKeyAuth)
        assert auth.name == "X-ClockodoApiKey"
        assert auth.api_key == "key123"
        assert auth.location == "header"


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginated_walks_all_pages_and_saves_state(self, MockSession) -> None:
        session = MockSession.return_value
        params, _auths, _urls = _wire(
            session,
            [
                _response([{"id": 1}, {"id": 2}], count_pages=2),
                _response([{"id": 3}], count_pages=2),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("customers", manager))

        assert [r["id"] for r in rows] == [1, 2, 3]
        assert params[0]["page"] == 1
        assert params[1]["page"] == 2
        # Checkpoint saved after the first page (points at the next page to fetch); the paging
        # block says page 2 is the last, so no further checkpoint is written.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == ClockodoResumeConfig(next_page=2)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_after_count_pages_without_extra_request(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}], count_pages=1)])

        manager = _make_manager()
        rows = _rows(_source("customers", manager))

        assert [r["id"] for r in rows] == [1]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_terminates_before_count_pages(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": 1}], count_pages=3),
                _response([], count_pages=3),
            ],
        )

        rows = _rows(_source("customers", _make_manager()))

        # An empty page ends the walk even when the paging block promises more pages.
        assert [r["id"] for r in rows] == [1]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        params, _auths, _urls = _wire(session, [_response([{"id": 3}], count_pages=2)])

        manager = _make_manager(ClockodoResumeConfig(next_page=2))
        rows = _rows(_source("customers", manager))

        # Picks up at the saved page rather than restarting at page 1.
        assert params[0]["page"] == 2
        assert [r["id"] for r in rows] == [3]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_paginated_single_fetch(self, MockSession) -> None:
        session = MockSession.return_value
        params, _auths, _urls = _wire(session, [_response([{"id": 1}, {"id": 2}], data_key="services")])

        manager = _make_manager()
        rows = _rows(_source("services", manager))

        assert session.send.call_count == 1
        # Non-paginated endpoints never send a page param.
        assert "page" not in params[0]
        assert [r["id"] for r in rows] == [1, 2]
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    @time_machine.travel("2026-06-29T12:00:00Z", tick=False)
    def test_entries_sends_time_window(self, MockSession) -> None:
        session = MockSession.return_value
        params, _auths, _urls = _wire(session, [_response([{"id": 1}], data_key="entries", count_pages=1)])

        _rows(_source("entries", _make_manager()))

        assert params[0]["time_since"] == "2000-01-01T00:00:00Z"
        assert params[0]["time_until"] == "2027-06-29T12:00:00Z"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_response_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], count_pages=1)])

        rows = _rows(_source("customers", _make_manager()))

        assert rows == []

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_yields_no_rows(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(None, count_pages=1, drop_data=True)])

        rows = _rows(_source("customers", _make_manager()))

        assert rows == []


class TestClockodoSourceResponse:
    @parameterized.expand([("customers",), ("entries",), ("users",)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_primary_keys_default_to_id(self, endpoint: str, MockSession) -> None:
        response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == ["id"]


class TestVersionDispatch:
    @parameterized.expand(
        [
            # v2 serves each resource under its own key; the successors return rows under "data".
            (CLOCKODO_API_VERSION_V2, "customers", "customers", "/api/v2/customers"),
            (CLOCKODO_API_VERSION_V3, "customers", "data", "/api/v3/customers"),
            (CLOCKODO_API_VERSION_V3, "projects", "data", "/api/v4/projects"),
            (CLOCKODO_API_VERSION_V3, "lumpsum_services", "data", "/api/v4/lumpSumServices"),
            (CLOCKODO_API_VERSION_V3, "teams", "data", "/api/v3/teams"),
            # surcharges is not decommissioned, so it stays on the v2 path under either pin.
            (CLOCKODO_API_VERSION_V3, "surcharges", "surcharges", "/api/v2/surcharges"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_pin_routes_to_versioned_path_and_envelope(
        self, api_version: str, endpoint: str, data_key: str, expected_path: str, MockSession
    ) -> None:
        session = MockSession.return_value
        _params, _auths, urls = _wire(session, [_response([{"id": 1}], data_key=data_key, count_pages=1)])

        rows = _rows(_source(endpoint, _make_manager(), api_version=api_version))

        # Wrong path hits a decommissioned endpoint; wrong envelope key yields zero rows.
        assert [r["id"] for r in rows] == [1]
        assert expected_path in urls[0]

    def test_every_supported_version_covers_all_tables(self) -> None:
        # clockodo_source indexes the version map by table name, so a table missing from any
        # version map would KeyError mid-sync instead of routing to a path.
        for version in CLOCKODO_SUPPORTED_VERSIONS:
            assert set(endpoints_for_version(version)) == set(ENDPOINTS)

    def test_unknown_version_raises(self) -> None:
        with pytest.raises(ValueError):
            endpoints_for_version("v99")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_v3_paginates_a_resource_v2_served_in_one_page(self, MockSession) -> None:
        # v2/users returns the whole collection in one response; v3/users paginates, so a
        # single-page fetch would silently drop every user past the first page.
        session = MockSession.return_value
        params, _auths, _urls = _wire(
            session,
            [
                _response([{"id": 1}], data_key="data", count_pages=2),
                _response([{"id": 2}], data_key="data", count_pages=2),
            ],
        )

        rows = _rows(_source("users", _make_manager(), api_version=CLOCKODO_API_VERSION_V3))

        assert [r["id"] for r in rows] == [1, 2]
        assert params[0]["page"] == 1
        assert params[1]["page"] == 2


class TestWorkTimeWindows:
    @time_machine.travel("2026-06-29T12:00:00Z", tick=False)
    def test_windows_tile_the_reported_period_without_gaps(self) -> None:
        windows = list(_work_time_windows(date(2026, 6, 29)))

        # A gap between windows silently drops the attendance days inside it, an overlap
        # re-fetches them, and a window longer than the API's page would truncate one.
        assert windows[0].date_since == WORK_TIMES_FIRST_DATE
        assert windows[-1].date_until == date(2026, 6, 29)
        for window, next_window in zip(windows, windows[1:]):
            assert next_window.date_since == window.date_until + timedelta(days=1)
        for window in windows:
            assert window.date_since <= window.date_until
            assert (window.date_until - window.date_since).days < WORK_TIMES_WINDOW_DAYS


class TestWorkTimesSweep:
    @mock.patch(CLIENT_SESSION_PATCH)
    @time_machine.travel("2024-06-29T12:00:00Z", tick=False)
    def test_fans_out_over_co_workers_and_windows(self, MockSession) -> None:
        session = MockSession.return_value
        params, _auths, urls = _wire(
            session,
            [
                _response([{"id": 7}, {"id": 9}], data_key="users"),
                _response([{"users_id": 7, "date": "2024-06-03"}], data_key="work_time_days"),
                _response([{"users_id": 9, "date": "2024-06-04"}], data_key="work_time_days"),
            ],
        )

        rows = _rows(_source("work_times", _make_manager()))

        # The endpoint reaches one co-worker at a time, so the co-worker list is the only way
        # to cover the account.
        assert "/api/v2/users" in urls[0]
        assert [p.get("users_id") for p in params[1:]] == [7, 9]
        assert all(p["date_since"] == WORK_TIMES_FIRST_DATE.isoformat() for p in params[1:])
        assert all(p["date_until"] == "2024-06-29" for p in params[1:])
        assert [(r["users_id"], r["date"]) for r in rows] == [(7, "2024-06-03"), (9, "2024-06-04")]

    @parameterized.expand(
        [
            (CLOCKODO_API_VERSION_V2, "users", "/api/v2/users"),
            (CLOCKODO_API_VERSION_V3, "data", "/api/v3/users"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    @time_machine.travel("2024-06-29T12:00:00Z", tick=False)
    def test_co_worker_list_follows_the_pinned_version(
        self, api_version: str, users_data_key: str, expected_users_path: str, MockSession
    ) -> None:
        session = MockSession.return_value
        _params, _auths, urls = _wire(
            session,
            [
                _response([{"id": 7}], data_key=users_data_key, count_pages=1),
                _response([{"users_id": 7, "date": "2024-06-03"}], data_key="work_time_days"),
            ],
        )

        rows = _rows(_source("work_times", _make_manager(), api_version=api_version))

        # A v2 path or envelope under a v3 pin reaches a decommissioned endpoint or yields no
        # co-workers, which would sweep no work times at all.
        assert expected_users_path in urls[0]
        assert "/api/v2/workTimes" in urls[1]
        assert [r["users_id"] for r in rows] == [7]

    @mock.patch(CLIENT_SESSION_PATCH)
    @time_machine.travel("2024-06-29T12:00:00Z", tick=False)
    def test_no_co_workers_sweeps_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], data_key="users")])

        assert _rows(_source("work_times", _make_manager())) == []
        assert session.send.call_count == 1


class TestUserReportsSweep:
    @mock.patch(CLIENT_SESSION_PATCH)
    @time_machine.travel("2026-06-29T12:00:00Z", tick=False)
    def test_walks_every_year_and_stamps_it_on_each_row(self, MockSession) -> None:
        session = MockSession.return_value
        years = list(range(USER_REPORTS_FIRST_YEAR, 2027))
        params, _auths, _urls = _wire(
            session,
            [_response([{"users_id": 3}], data_key="userreports") for _ in years],
        )

        rows = _rows(_source("user_reports", _make_manager()))

        # The API requires an explicit year and returns it on no row, so without the stamp
        # every year would merge onto the same primary key.
        assert [p["year"] for p in params] == years
        assert [r["year"] for r in rows] == years
        assert {r["users_id"] for r in rows} == {3}
        # Year level only — the deeper report types nest month, week and day arrays per row.
        assert {p["type"] for p in params} == {0}


class TestSinglePageEndpoints:
    @parameterized.expand(
        [
            ("absences", "data", "/api/v4/absences"),
            ("target_hours", "targethours", "/api/targethours"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_reads_the_whole_collection_in_one_request(
        self, endpoint: str, data_key: str, expected_path: str, MockSession
    ) -> None:
        session = MockSession.return_value
        params, _auths, urls = _wire(session, [_response([{"id": 1}, {"id": 2}], data_key=data_key)])

        rows = _rows(_source(endpoint, _make_manager()))

        assert expected_path in urls[0]
        assert session.send.call_count == 1
        # Neither endpoint documents a page param, and neither returns a paging block.
        assert "page" not in params[0]
        assert [r["id"] for r in rows] == [1, 2]


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    @mock.patch(CLOCKODO_SESSION_PATCH)
    def test_validate_credentials_status_mapping(self, _name: str, status: int, expected: bool, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("u", "k", CLOCKODO_API_VERSION_V3) is expected

    @mock.patch(CLOCKODO_SESSION_PATCH)
    def test_validate_credentials_swallows_transport_errors(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("u", "k", CLOCKODO_API_VERSION_V3) is False

    @parameterized.expand(
        [
            (CLOCKODO_API_VERSION_V2, "https://my.clockodo.com/api/v2/users"),
            # A new source defaults to v3; probing v2/users would fail once it is decommissioned.
            (CLOCKODO_API_VERSION_V3, "https://my.clockodo.com/api/v3/users"),
        ]
    )
    @mock.patch(CLOCKODO_SESSION_PATCH)
    def test_probe_targets_version_users_path(self, api_version: str, expected_url: str, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("me@example.com", "key123", api_version)
        args, kwargs = mock_session.return_value.get.call_args
        assert args[0] == expected_url
        headers = kwargs["headers"]
        assert headers["X-ClockodoApiUser"] == "me@example.com"
        assert headers["X-ClockodoApiKey"] == "key123"
        assert headers["X-Clockodo-External-Application"] == f"{EXTERNAL_APPLICATION_NAME};me@example.com"
