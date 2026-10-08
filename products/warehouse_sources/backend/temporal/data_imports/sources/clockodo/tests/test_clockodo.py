import json
from datetime import UTC, datetime
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
    clockodo_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clockodo.settings import (
    CLOCKODO_API_VERSION_V2,
    CLOCKODO_API_VERSION_V3,
    CLOCKODO_ENDPOINTS_V2,
    USER_REPORTS_FIRST_YEAR,
    endpoints_for_version,
)

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
    @parameterized.expand([("customers",), ("projects",), ("services",), ("users",)])
    def test_non_entries_have_no_time_window(self, endpoint: str) -> None:
        params = _endpoint_params(endpoint, CLOCKODO_ENDPOINTS_V2[endpoint])
        assert "time_since" not in params
        assert "time_until" not in params


class TestPagination:
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

    def test_unknown_version_raises(self) -> None:
        with pytest.raises(ValueError):
            endpoints_for_version("v99")


class TestWorkTimesSweep:
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
