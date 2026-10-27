from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.clockodo.clockodo import (
    EXTERNAL_APPLICATION_NAME,
    ClockodoResumeConfig,
    _endpoint_params,
    _format_z,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clockodo.settings import (
    CLOCKODO_API_VERSION_V2,
    CLOCKODO_API_VERSION_V3,
    CLOCKODO_ENDPOINTS_V2,
    USER_REPORTS_FIRST_YEAR,
    endpoints_for_version,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clockodo.source import ClockodoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clockodo import (
    ClockodoSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(ClockodoSource(), ClockodoSourceConfig(api_user="me@example.com", api_key="key123"))


def _response(
    items: list[dict[str, Any]] | None,
    *,
    data_key: str = "customers",
    count_pages: int | None = None,
) -> ScriptedResponse:
    body: dict[str, Any] = {data_key: items or []}
    if count_pages is not None:
        body["paging"] = {"count_pages": count_pages}
    return ScriptedResponse(json=body)


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
    def test_empty_page_terminates_before_count_pages(self) -> None:
        result = _driver().run(
            "customers",
            [_response([{"id": 1}], count_pages=3), _response([], count_pages=3)],
            api_version=CLOCKODO_API_VERSION_V2,
        )

        # An empty page ends the walk even when the paging block promises more pages.
        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1]
        assert result.params("page") == ["1", "2"]

    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "customers",
            [_response([{"id": 3}], count_pages=2)],
            resume_state=ClockodoResumeConfig(next_page=2),
            api_version=CLOCKODO_API_VERSION_V2,
        )

        # Picks up at the saved page rather than restarting at page 1.
        assert result.raised is None
        assert result.params("page") == ["2"]
        assert [row["id"] for row in result.rows] == [3]


class TestClockodoSourceResponse:
    @parameterized.expand([("customers",), ("entries",), ("users",)])
    def test_primary_keys_default_to_id(self, endpoint: str) -> None:
        result = _driver().run(
            endpoint,
            [_response([{"id": 1}], data_key=endpoint, count_pages=1)],
            api_version=CLOCKODO_API_VERSION_V2,
        )

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == ["id"]


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
    def test_pin_routes_to_versioned_path_and_envelope(
        self, api_version: str, endpoint: str, data_key: str, expected_path: str
    ) -> None:
        result = _driver().run(
            endpoint,
            [_response([{"id": 1}], data_key=data_key, count_pages=1)],
            api_version=api_version,
        )

        # Wrong path hits a decommissioned endpoint; wrong envelope key yields zero rows.
        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1]
        assert result.paths == [expected_path]

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
    @time_machine.travel("2024-06-29T12:00:00Z", tick=False)
    def test_co_worker_list_follows_the_pinned_version(
        self, api_version: str, users_data_key: str, expected_users_path: str
    ) -> None:
        result = _driver().run(
            "work_times",
            [
                _response([{"id": 7}], data_key=users_data_key, count_pages=1),
                _response([{"users_id": 7, "date": "2024-06-03"}], data_key="work_time_days"),
            ],
            api_version=api_version,
        )

        # A v2 path or envelope under a v3 pin reaches a decommissioned endpoint or yields no
        # co-workers, which would sweep no work times at all.
        assert result.raised is None
        assert result.paths == [expected_users_path, "/api/v2/workTimes"]
        assert [row["users_id"] for row in result.rows] == [7]


class TestUserReportsSweep:
    @time_machine.travel("2026-06-29T12:00:00Z", tick=False)
    def test_walks_every_year_and_stamps_it_on_each_row(self) -> None:
        years = list(range(USER_REPORTS_FIRST_YEAR, 2027))
        result = _driver().run(
            "user_reports",
            [_response([{"users_id": 3}], data_key="userreports") for _ in years],
        )

        # The API requires an explicit year and returns it on no row, so without the stamp
        # every year would merge onto the same primary key.
        assert result.raised is None
        assert result.params("year") == [str(year) for year in years]
        assert [row["year"] for row in result.rows] == years
        assert {row["users_id"] for row in result.rows} == {3}
        # Year level only — the deeper report types nest month, week and day arrays per row.
        assert set(result.params("type")) == {"0"}


class TestSinglePageEndpoints:
    @parameterized.expand(
        [
            ("absences", "data", "/api/v4/absences"),
            ("target_hours", "targethours", "/api/targethours"),
        ]
    )
    def test_reads_the_whole_collection_in_one_request(self, endpoint: str, data_key: str, expected_path: str) -> None:
        result = _driver().run(endpoint, [_response([{"id": 1}, {"id": 2}], data_key=data_key)])

        assert result.raised is None
        assert result.paths == [expected_path]
        # Neither endpoint documents a page param, and neither returns a paging block.
        assert result.params("page") == [None]
        assert [row["id"] for row in result.rows] == [1, 2]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_validate_credentials_status_mapping(self, _name: str, status: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            actual = validate_credentials("u", "k", CLOCKODO_API_VERSION_V3)

        assert actual is expected
        assert [request.path for request in network.requests_log] == ["/api/v3/users"]

    @parameterized.expand(
        [
            (CLOCKODO_API_VERSION_V2, "https://my.clockodo.com/api/v2/users"),
            # A new source defaults to v3; probing v2/users would fail once it is decommissioned.
            (CLOCKODO_API_VERSION_V3, "https://my.clockodo.com/api/v3/users"),
        ]
    )
    def test_probe_targets_version_users_path(self, api_version: str, expected_url: str) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_credentials("me@example.com", "key123", api_version)

        assert network.requests_log[0].url == expected_url
        headers = network.requests_log[0].headers
        assert headers["x-clockodoapiuser"] == "me@example.com"
        assert headers["x-clockodoapikey"] == "key123"
        assert headers["x-clockodo-external-application"] == f"{EXTERNAL_APPLICATION_NAME};me@example.com"
