from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Optional

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.aftership.aftership import (
    API_KEY_HEADER,
    AftershipResumeConfig,
    _to_aftership_datetime,
    check_access,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aftership.settings import DEFAULT_VERSION
from products.warehouse_sources.backend.temporal.data_imports.sources.aftership.source import AftershipSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.aftership import (
    AftershipSourceConfig,
)

BASE_URL = f"https://api.aftership.com/tracking/{DEFAULT_VERSION}"


def _page(
    key: str,
    items: Optional[list[dict[str, Any]]] = None,
    *,
    next_cursor: Optional[str] = None,
    status_code: int = 200,
) -> ScriptedResponse:
    data: dict[str, Any] = {key: items or []}
    if next_cursor is not None:
        data["pagination"] = {"next_cursor": next_cursor, "has_next_page": True}
    return ScriptedResponse(status=status_code, json={"meta": {"code": 200}, "data": data})


def _driver() -> SourceDriver:
    return SourceDriver(AftershipSource(), AftershipSourceConfig(api_key="key"))


class TestToAftershipDatetime:
    @parameterized.expand(
        [
            ("aware_utc", datetime(2026, 1, 15, 12, 30, 45, tzinfo=UTC), "2026-01-15T12:30:45+00:00"),
            ("naive_treated_as_utc", datetime(2026, 1, 15, 12, 30, 45), "2026-01-15T12:30:45+00:00"),
            (
                "other_offset_converted",
                datetime(2026, 1, 15, 20, 30, 45, tzinfo=timezone(timedelta(hours=8))),
                "2026-01-15T12:30:45+00:00",
            ),
            (
                "microseconds_dropped",
                datetime(2026, 1, 15, 12, 30, 45, 123456, tzinfo=UTC),
                "2026-01-15T12:30:45+00:00",
            ),
            ("zulu_string_rewritten", "2026-01-15T12:30:45Z", "2026-01-15T12:30:45+00:00"),
            ("offset_string", "2026-01-15T20:30:45+08:00", "2026-01-15T12:30:45+00:00"),
            ("garbage_string", "not-a-date", None),
            ("non_datetime_type", 12345, None),
        ]
    )
    def test_coercion(self, _name: str, value: Any, expected: Optional[str]) -> None:
        # AfterShip validates these params against ^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$,
        # so a trailing Z or fractional seconds is a 400.
        assert _to_aftership_datetime(value) == expected


class TestPagination:
    def test_couriers_is_single_page_and_never_sends_a_cursor(self) -> None:
        # A next_cursor in the body must not restart pagination for an endpoint that has none.
        result = _driver().run("couriers", [_page("couriers", [{"slug": "usps"}], next_cursor="cur-1")])

        assert result.raised is None
        assert [row["slug"] for row in result.rows] == ["usps"]
        assert result.urls == [f"{BASE_URL}/couriers"]
        assert result.queries == [{}]


class TestIncrementalFiltering:
    @parameterized.expand(
        [
            ("updated_at", "updated_at", "updated_at_min"),
            ("created_at", "created_at", "created_at_min"),
        ]
    )
    def test_users_incremental_field_picks_the_server_side_filter(
        self, _name: str, incremental_field_name: str, expected_param: str
    ) -> None:
        result = _driver().run(
            "trackings",
            [_page("trackings", [{"id": "1"}])],
            incremental_field=incremental_field_name,
            db_incremental_field_last_value=datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param(expected_param) == "2026-01-15T12:00:00+00:00"
        assert len([key for key in result.queries[0] if key.endswith("_min")]) == 1

    @parameterized.expand(
        [
            ("unmapped_field_on_incremental_endpoint", "trackings", "shipment_delivery_date"),
            ("full_refresh_endpoint", "courier_connections", "updated_at"),
        ]
    )
    def test_no_filter_sent_when_the_field_has_no_server_side_param(
        self, _name: str, endpoint: str, incremental_field_name: str
    ) -> None:
        result = _driver().run(
            endpoint,
            [_page(endpoint, [])],
            incremental_field=incremental_field_name,
            db_incremental_field_last_value=datetime(2026, 1, 15, tzinfo=UTC),
        )

        assert result.raised is None
        assert not [key for key in result.queries[0] if key.endswith("_min")]

    def test_filter_is_resent_on_every_page(self) -> None:
        result = _driver().run(
            "trackings",
            [_page("trackings", [{"id": "1"}], next_cursor="cur-1"), _page("trackings", [{"id": "2"}])],
            incremental_field="updated_at",
            db_incremental_field_last_value=datetime(2026, 1, 15, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.params("updated_at_min") == ["2026-01-15T00:00:00+00:00"] * 2


class TestResume:
    def test_saves_cursor_and_window_after_yielding_each_page(self) -> None:
        result = _driver().run(
            "trackings",
            [_page("trackings", [{"id": "1"}], next_cursor="cur-1"), _page("trackings", [{"id": "2"}])],
            incremental_field="updated_at",
            db_incremental_field_last_value=datetime(2026, 1, 15, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.saved_states == [
            AftershipResumeConfig(cursor="cur-1", incremental_start="2026-01-15T00:00:00+00:00")
        ]
        assert result.committed_states == result.saved_states

    def test_resumes_from_saved_cursor_and_reuses_the_saved_window(self) -> None:
        result = _driver().run(
            "trackings",
            [_page("trackings", [{"id": "9"}])],
            resume_state=AftershipResumeConfig(cursor="cur-8", incremental_start="2026-01-01T00:00:00+00:00"),
            incremental_field="updated_at",
            # The watermark advanced from committed batches; narrowing the window mid-walk
            # would leave the saved cursor pointing outside the filtered result set.
            db_incremental_field_last_value=datetime(2026, 2, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["9"]
        assert result.params("cursor") == ["cur-8"]
        assert result.params("updated_at_min") == ["2026-01-01T00:00:00+00:00"]


class TestSourceResponse:
    @parameterized.expand(
        [
            ("trackings", "trackings", ["id"], ["created_at"]),
            ("couriers", "couriers", ["slug"], None),
            ("courier_connections", "courier_connections", ["id"], None),
        ]
    )
    def test_primary_keys_and_partitioning(
        self, _name: str, endpoint: str, expected_keys: list[str], expected_partition_keys: Optional[list[str]]
    ) -> None:
        result = _driver().run(endpoint, [_page(endpoint, [])])
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        assert response.partition_keys == expected_partition_keys
        # AfterShip documents no ordering and offers no sort param, so the watermark is only
        # committed once at the end of the sync.
        assert response.sort_mode == "desc"


class TestRequestShape:
    def test_api_key_is_sent_in_the_as_api_key_header(self) -> None:
        result = _driver().run("trackings", [_page("trackings", [])])

        assert result.raised is None
        # The legacy `aftership-api-key` header stopped working at API version 2023-10.
        assert result.requests[0].headers[API_KEY_HEADER] == "key"

    def test_api_version_is_a_path_segment(self) -> None:
        result = _driver().run("trackings", [_page("trackings", [])], api_version="2026-01")

        assert result.raised is None
        assert result.paths == ["/tracking/2026-01/trackings"]

    @parameterized.expand([(401,), (403,)])
    def test_auth_errors_raise_a_matchable_http_error(self, status_code: int) -> None:
        result = _driver().run("trackings", [_page("trackings", [], status_code=status_code)])

        assert isinstance(result.raised, HTTPError)
        assert f"{status_code} Client Error" in str(result.raised)


class TestCourierConnectionRedaction:
    def test_carrier_credentials_never_reach_the_warehouse(self) -> None:
        result = _driver().run(
            "courier_connections",
            [
                _page(
                    "courier_connections",
                    [
                        {
                            "id": "conn-1",
                            "courier_slug": "dhl-api",
                            "credentials": {"api_key": "carrier-secret", "password": "hunter2"},
                            "created_at": "2026-01-01T00:00:00+00:00",
                        }
                    ],
                )
            ],
        )

        assert result.raised is None
        assert result.rows == [{"id": "conn-1", "courier_slug": "dhl-api", "created_at": "2026-01-01T00:00:00+00:00"}]


class TestCheckAccess:
    @parameterized.expand(
        [
            ("token_only", None, f"{BASE_URL}/trackings?limit=1"),
            ("cursor_endpoint", "courier_connections", f"{BASE_URL}/courier-connections?limit=1"),
            ("single_page_endpoint", "couriers", f"{BASE_URL}/couriers"),
        ]
    )
    def test_probe_url_per_schema(self, _name: str, schema_name: Optional[str], expected_url: str) -> None:
        with scripted_network([ScriptedResponse()]) as network:
            assert check_access("key", schema_name) == (True, 200)

        assert network.requests_log[0].url == expected_url

    def test_probe_does_not_follow_redirects(self) -> None:
        redirect = ScriptedResponse(status=302, headers={"Location": "https://example.com/elsewhere"})
        with scripted_network([redirect]) as network:
            assert check_access("key") == (False, 302)

        # The key rides a custom header, which requests would replay to a redirect target.
        assert len(network.requests_log) == 1
        assert network.requests_log[0].headers[API_KEY_HEADER] == "key"
