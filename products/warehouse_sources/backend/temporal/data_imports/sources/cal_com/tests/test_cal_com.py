from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, cast

import pytest
import time_machine

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.cal_com.cal_com import (
    CalComResumeConfig,
    check_organization_access,
    resolve_organization_id,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cal_com.settings import (
    BOOKING_ATTENDEES_ENDPOINT,
    BOOKINGS_WINDOW_ORIGIN,
    CAL_COM_ENDPOINTS,
    CAL_COM_HOSTS,
    ENDPOINTS,
    endpoint_requires_organization,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cal_com.source import CalComSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.calcom import CalComSourceConfig

US_BASE_URL = CAL_COM_HOSTS["us"]
ORG_ID = 77
FIRST_WINDOW_START = "1970-01-01T00:00:00.000Z"


@pytest.fixture(autouse=True)
def _clock_before_the_window_origin() -> Iterator[None]:
    # A first bookings sync is then one unbounded window, so a test that is not about windows needs
    # one response per page.
    with time_machine.travel(BOOKINGS_WINDOW_ORIGIN - timedelta(days=200), tick=False):
        yield


def _driver(region: str | None = "us") -> SourceDriver:
    # A stored connection can predate the region field and still contain None.
    config = CalComSourceConfig(api_key="cal_live_key", region=cast(Literal["us", "eu"], region))
    return SourceDriver(CalComSource(), config)


def _page(items: Any, next_cursor: str | None = None, has_more: bool = False) -> ScriptedResponse:
    return ScriptedResponse(
        json={"status": "success", "data": items, "pagination": {"nextCursor": next_cursor, "hasMore": has_more}}
    )


def _run(
    endpoint: str,
    script: Sequence[ScriptedResponse | BaseException],
    *,
    organization_id: int | None = ORG_ID,
    region: str | None = "us",
    **inputs: Any,
) -> DriveResult:
    answers = list(script)
    if endpoint_requires_organization(endpoint):
        answers.insert(0, ScriptedResponse(json={"data": {"organizationId": organization_id}}))
    return _driver(region).run(endpoint, answers, **inputs)


def _empty_response(request: RecordedRequest) -> ScriptedResponse:
    if request.path == "/v2/me":
        return ScriptedResponse(json={"data": {"id": 1, "organizationId": ORG_ID}})
    return _page([])


class TestBookingsCursorPagination:
    @staticmethod
    def _pages() -> list[ScriptedResponse]:
        return [_page([{"id": 1}], next_cursor="c2", has_more=True), _page([{"id": 2}])]

    def test_a_first_sync_walks_created_at_windows_oldest_first(self) -> None:
        with time_machine.travel(BOOKINGS_WINDOW_ORIGIN + timedelta(days=45), tick=False):
            result = _run(
                "bookings",
                [
                    _page([]),
                    _page([{"id": 1}], next_cursor="c2", has_more=True),
                    _page([{"id": 2}]),
                    _page([{"id": 3}]),
                ],
            )

        assert result.raised is None
        assert result.rows == [{"id": 1}, {"id": 2}, {"id": 3}]
        assert result.queries == [
            {
                "limit": ("50",),
                "afterCreatedAt": (FIRST_WINDOW_START,),
                "beforeCreatedAt": ("2020-12-31T23:59:59.999Z",),
            },
            {
                "limit": ("50",),
                "afterCreatedAt": ("2021-01-01T00:00:00.000Z",),
                "beforeCreatedAt": ("2021-01-30T23:59:59.999Z",),
            },
            {
                "limit": ("50",),
                "afterCreatedAt": ("2021-01-01T00:00:00.000Z",),
                "beforeCreatedAt": ("2021-01-30T23:59:59.999Z",),
                "cursor": ("c2",),
            },
            {"limit": ("50",), "afterCreatedAt": ("2021-01-31T00:00:00.000Z",)},
        ]
        assert [(state.window_start, state.cursor) for state in result.saved_states] == [
            ("2021-01-01T00:00:00.000Z", None),
            ("2021-01-01T00:00:00.000Z", "c2"),
            ("2021-01-31T00:00:00.000Z", None),
        ]

    @parameterized.expand(
        [
            (
                "windowed_state",
                CalComResumeConfig(cursor="c2", window_start="2020-01-01T00:00:00.000Z"),
                {"afterCreatedAt": "2020-01-01T00:00:00.000Z", "cursor": "c2"},
            ),
            ("cursor_without_window", CalComResumeConfig(cursor="c2"), {"afterCreatedAt": FIRST_WINDOW_START}),
        ]
    )
    def test_resumes_from_saved_state(
        self, _name: str, resume_state: CalComResumeConfig, expected_params: dict[str, Any]
    ) -> None:
        result = _run("bookings", [_page([{"id": 2}])], resume_state=resume_state)

        assert result.raised is None
        assert result.rows == [{"id": 2}]
        assert result.queries == [{"limit": ("50",), **{name: (value,) for name, value in expected_params.items()}}]

    def test_incremental_created_at_maps_to_after_created_at(self) -> None:
        result = _run(
            "bookings",
            self._pages(),
            db_incremental_field_last_value=date(2026, 1, 2),
            incremental_field="createdAt",
        )

        assert result.raised is None
        assert result.requests[0].param("afterCreatedAt") == "2026-01-02T00:00:00.000Z"
        assert result.requests[0].param("afterUpdatedAt") is None

    def test_unknown_incremental_field_raises(self) -> None:
        result = _run(
            "bookings",
            [],
            db_incremental_field_last_value="2026-01-01",
            incremental_field="startTime",
        )

        assert isinstance(result.raised, ValueError)
        assert "no server-side filter" in str(result.raised)
        assert result.requests == []

    @parameterized.expand(
        [
            ("incremental_disabled", False, "2026-01-01"),
            ("no_last_value", True, None),
        ]
    )
    def test_no_filter_param_without_watermark(self, _name: str, should_use: bool, last_value: Any) -> None:
        result = _run(
            "bookings",
            self._pages(),
            should_use_incremental_field=should_use,
            db_incremental_field_last_value=last_value,
            incremental_field="updatedAt" if should_use else None,
        )

        assert result.raised is None
        assert result.requests[0].param("afterUpdatedAt") is None


class TestWebhooksOffsetPagination:
    def test_resumes_from_saved_offset(self) -> None:
        result = _run(
            "webhooks",
            [ScriptedResponse(json={"data": [{"id": "resumed"}]})],
            resume_state=CalComResumeConfig(skip=500),
        )

        assert result.raised is None
        assert result.rows == [{"id": "resumed"}]
        assert result.params("skip") == ["500"]


class TestSingleFetchEndpoints:
    @parameterized.expand([("event_types",), ("schedules",), ("teams",)])
    def test_list_endpoints_yield_single_batch(self, endpoint: str) -> None:
        result = _run(endpoint, [ScriptedResponse(json={"data": [{"id": 1}, {"id": 2}]})])

        assert result.raised is None
        assert result.rows == [{"id": 1}, {"id": 2}]
        assert len(result.requests) == 1
        assert result.saved_states == []

    @parameterized.expand(
        [
            ("bookings", "2026-05-01"),
            ("event_types", "2024-06-14"),
            ("schedules", "2024-06-11"),
            ("teams", None),
        ]
    )
    def test_endpoint_versions_pinned_in_headers(self, endpoint: str, expected_version: str | None) -> None:
        # Omitting cal-api-version silently falls back to legacy endpoint behavior, so the
        # versioned endpoints must pin it.
        result = _run(endpoint, [_page([])])

        assert result.raised is None
        assert result.requests[0].headers.get("cal-api-version") == expected_version


class TestErrorHandling:
    @parameterized.expand([("bare_list", [{"id": 1}]), ("missing_data", {"status": "success"})])
    def test_unexpected_payload_shape_fails_loudly(self, _name: str, body: Any) -> None:
        # A 200 body without `data` means the response shape changed — fail loud, not silently 0 rows.
        result = _run("me", [ScriptedResponse(json=body)])

        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)

    @parameterized.expand(
        [("unauthorized", 401, "Unauthorized"), ("forbidden", 403, "Forbidden"), ("not_found", 404, "Not Found")]
    )
    def test_client_errors_raise_http_error_with_base_url(self, _name: str, status: int, reason: str) -> None:
        result = _run("bookings", [ScriptedResponse(status=status, json={})])

        assert isinstance(result.raised, requests.HTTPError)
        # The base URL must be in the message so `get_non_retryable_errors()` can match on it.
        assert f"{status} Client Error: {reason} for url: {US_BASE_URL}/bookings" in str(result.raised)


class TestRegionHost:
    @parameterized.expand(
        [
            ("us", "us", "https://api.cal.com/v2/bookings"),
            ("eu", "eu", "https://api.cal.eu/v2/bookings"),
            # An account created before the region field existed has no stored value.
            ("unset", None, "https://api.cal.com/v2/bookings"),
        ]
    )
    def test_region_selects_the_api_host(self, _name: str, region: str | None, expected_url: str) -> None:
        result = _run("bookings", [_page([{"id": 1}])], region=region)

        assert result.raised is None
        assert [url.split("?", 1)[0] for url in result.urls] == [expected_url]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_valid: bool, expected_message: str | None) -> None:
        script = always(ScriptedResponse(status=status)) if status == 500 else [ScriptedResponse(status=status)]
        with scripted_network(script) as network:
            assert validate_credentials("cal_live_key") == (expected_valid, expected_message)
        assert network.requests_log[0].path == "/v2/me"

    def test_connection_error_is_swallowed(self) -> None:
        with scripted_network(always(requests.ConnectionError("boom"))) as network:
            assert validate_credentials("cal_live_key") == (False, "Could not connect to Cal.com")
        assert {request.path for request in network.requests_log} == {"/v2/me"}

    @parameterized.expand([("us", "us", "https://api.cal.com/v2/me"), ("eu", "eu", "https://api.cal.eu/v2/me")])
    def test_probes_the_host_for_the_selected_region(self, _name: str, region: str, expected_url: str) -> None:
        # An EU key probed against the US host comes back 401, which reads as a bad key.
        with scripted_network([ScriptedResponse()]) as network:
            assert validate_credentials("cal_live_key", region) == (True, None)
        assert network.requests_log[0].url == expected_url


class TestCalComSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_every_endpoint_builds_a_response_named_after_its_schema(self, endpoint: str) -> None:
        # The name is the Delta subdirectory: a wrong one writes where nothing reads.
        result = _driver().run(endpoint, _empty_response)

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint

    def test_partition_keys_are_creation_timestamps(self) -> None:
        # Partitioning on an updated-at style field rewrites every partition on every sync.
        keys = [config.partition_key for config in CAL_COM_ENDPOINTS.values() if config.partition_key]
        assert [key for key in keys if "updated" in key.lower()] == []

    def test_fanned_out_endpoints_key_on_their_parent_too(self) -> None:
        # A key unique only within one parent seeds duplicates every later merge multi-matches.
        children = [name for name, config in CAL_COM_ENDPOINTS.items() if config.fanout] + [BOOKING_ATTENDEES_ENDPOINT]
        assert [name for name in children if len(CAL_COM_ENDPOINTS[name].primary_keys) < 2] == []


class TestOrganizationEndpoints:
    @parameterized.expand(
        [
            ("organization_memberships", f"{US_BASE_URL}/organizations/{ORG_ID}/memberships"),
            ("organization_users", f"{US_BASE_URL}/organizations/{ORG_ID}/users"),
            ("routing_forms", f"{US_BASE_URL}/organizations/{ORG_ID}/routing-forms"),
        ]
    )
    def test_resolved_org_id_replaces_the_path_placeholder(self, endpoint: str, expected_url: str) -> None:
        result = _run(endpoint, [ScriptedResponse(json={"data": [{"id": 1}]})])

        assert result.raised is None
        assert result.rows == [{"id": 1}]
        assert result.paths == ["/v2/me", expected_url.removeprefix("https://api.cal.com")]

    @parameterized.expand(
        [
            ("organization_memberships",),
            ("organization_users",),
            ("routing_forms",),
            # Reached through an organization-scoped parent rather than its own path.
            ("routing_form_responses",),
        ]
    )
    def test_organization_tables_refuse_to_sync_without_one(self, endpoint: str) -> None:
        result = _run(endpoint, [], organization_id=None)

        assert isinstance(result.raised, ValueError)
        assert "not in a Cal.com organization" in str(result.raised)
        assert result.paths == ["/v2/me"]

    def test_org_listings_walk_skip_and_take(self) -> None:
        page_size = CAL_COM_ENDPOINTS["organization_users"].page_size
        full_page = [{"id": i} for i in range(page_size)]
        result = _run(
            "organization_users",
            [ScriptedResponse(json={"data": full_page}), ScriptedResponse(json={"data": [{"id": "last"}]})],
        )

        assert result.raised is None
        assert len(result.rows) == page_size + 1
        assert result.params("skip") == [None, "0", str(page_size)]
        assert result.requests[1].param("take") == str(page_size)


class TestFanoutEndpoints:
    def test_routing_form_responses_filter_each_form_at_the_watermark(self) -> None:
        result = _run(
            "routing_form_responses",
            [
                ScriptedResponse(json={"data": [{"id": "f1"}]}),
                ScriptedResponse(json={"data": [{"id": 1, "formId": "f1"}]}),
            ],
            db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
            incremental_field="createdAt",
        )

        assert result.raised is None
        assert result.rows == [{"id": 1, "formId": "f1"}]
        # The parent listing takes no watermark of its own; only the child is windowed.
        assert result.requests[1].param("afterCreatedAt") is None
        assert result.requests[2].param("afterCreatedAt") == "2026-01-02T03:04:05.000Z"
        assert result.requests[2].param("sortCreatedAt") == "asc"


class TestBookingAttendees:
    BOOKING = {"uid": "bk1", "createdAt": "2026-01-01T00:00:00.000Z", "updatedAt": "2026-01-05T00:00:00.000Z"}

    def test_a_booking_removed_mid_sync_does_not_fail_the_run(self) -> None:
        result = _run(
            BOOKING_ATTENDEES_ENDPOINT,
            [
                _page([self.BOOKING, {**self.BOOKING, "uid": "bk2"}]),
                ScriptedResponse(status=404, json={}),
                ScriptedResponse(json={"data": [{"id": 6}]}),
            ],
        )

        assert result.raised is None
        assert [row["bookingUid"] for row in result.rows] == ["bk2"]
        assert result.paths == ["/v2/bookings", "/v2/bookings/bk1/attendees", "/v2/bookings/bk2/attendees"]

    def test_incremental_sync_bounds_the_bookings_walk(self) -> None:
        # Without the window every sync re-reads every booking's attendees, one request each.
        result = _run(
            BOOKING_ATTENDEES_ENDPOINT,
            [_page([self.BOOKING]), ScriptedResponse(json={"data": [{"id": 5}]})],
            db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
            incremental_field="bookingUpdatedAt",
        )

        assert result.raised is None
        assert result.requests[0].param("afterUpdatedAt") == "2026-01-02T03:04:05.000Z"

    def test_resumes_at_the_bookings_page_it_stopped_on(self) -> None:
        result = _run(
            BOOKING_ATTENDEES_ENDPOINT,
            [_page([self.BOOKING]), ScriptedResponse(json={"data": [{"id": 5}]})],
            resume_state=CalComResumeConfig(cursor="c2", window_start=FIRST_WINDOW_START),
        )

        assert result.raised is None
        assert result.requests[0].param("cursor") == "c2"

    def test_unexpected_payload_shape_fails_loudly(self) -> None:
        result = _run(
            BOOKING_ATTENDEES_ENDPOINT,
            [_page([self.BOOKING]), ScriptedResponse(json={"status": "success"})],
        )

        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)


class TestOrganizationLookup:
    @parameterized.expand(
        [
            ("in_an_organization", {"id": 1, "organizationId": 77}, 77),
            ("personal_account", {"id": 1}, None),
            ("explicit_null", {"id": 1, "organizationId": None}, None),
        ]
    )
    def test_organization_id_comes_from_the_keys_own_profile(
        self, _name: str, profile: dict[str, Any], expected: int | None
    ) -> None:
        with scripted_network([ScriptedResponse(json={"data": profile})]) as network:
            assert resolve_organization_id("cal_live_key") == expected
        assert network.requests_log[0].path == "/v2/me"

    @parameterized.expand(
        [
            ("admin", 200, None),
            # A plain org member gets a valid-key 403; the fix is a different key, not a retry.
            ("member", 403, "organization member without admin access"),
        ]
    )
    def test_organization_access_probe(self, _name: str, status: int, expected: str | None) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            reason = check_organization_access("cal_live_key", ORG_ID)

        assert (reason is None) if expected is None else (expected in (reason or ""))
        assert network.requests_log[0].url == f"{US_BASE_URL}/organizations/{ORG_ID}/memberships"
