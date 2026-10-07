import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
import time_machine
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.cal_com.cal_com import (
    CalComResumeConfig,
    cal_com_source,
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
)

US_BASE_URL = CAL_COM_HOSTS["us"]
ORG_ID = 77
FIRST_WINDOW_START = "1970-01-01T00:00:00.000Z"
REJECTED_MESSAGE = (
    "Cal.com rejected this API key. Check the key, and check that the selected region matches your Cal.com account."
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the cal_com module.
CAL_COM_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.cal_com.cal_com.make_tracked_session"
)


@pytest.fixture(autouse=True)
def _clock_before_the_window_origin():
    # A first bookings sync is then one unbounded window, so a test that is not about windows needs
    # one response per page.
    with time_machine.travel(BOOKINGS_WINDOW_ORIGIN - timedelta(days=200), tick=False):
        yield


def _response(body: Any, status_code: int = 200, url: str | None = None, reason: str = "OK") -> Response:
    resp = Response()
    resp.status_code = status_code
    resp.reason = reason
    resp.url = url or f"{US_BASE_URL}/bookings"
    resp._content = json.dumps(body).encode()
    return resp


def _page(items: Any, next_cursor: str | None = None, has_more: bool = False) -> Response:
    return _response(
        {"status": "success", "data": items, "pagination": {"nextCursor": next_cursor, "hasMore": has_more}}
    )


def _make_manager(resume_state: CalComResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list that captures each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _source(endpoint: str, manager: mock.MagicMock | None = None, **kwargs: Any):
    return cal_com_source(
        api_key="cal_live_key",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager if manager is not None else _make_manager(),
        **kwargs,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestBookingsCursorPagination:
    def _pages(self) -> list[Response]:
        return [
            _page([{"id": 1}], next_cursor="c2", has_more=True),
            _page([{"id": 2}], next_cursor=None, has_more=False),
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_a_first_sync_walks_created_at_windows_oldest_first(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _page([]),
                _page([{"id": 1}], next_cursor="c2", has_more=True),
                _page([{"id": 2}]),
                _page([{"id": 3}]),
            ],
        )
        manager = _make_manager()

        with time_machine.travel(BOOKINGS_WINDOW_ORIGIN + timedelta(days=45), tick=False):
            rows = _rows(_source("bookings", manager))

        assert rows == [{"id": 1}, {"id": 2}, {"id": 3}]
        assert params == [
            {"limit": 50, "afterCreatedAt": FIRST_WINDOW_START, "beforeCreatedAt": "2020-12-31T23:59:59.999Z"},
            {"limit": 50, "afterCreatedAt": "2021-01-01T00:00:00.000Z", "beforeCreatedAt": "2021-01-30T23:59:59.999Z"},
            {
                "limit": 50,
                "afterCreatedAt": "2021-01-01T00:00:00.000Z",
                "beforeCreatedAt": "2021-01-30T23:59:59.999Z",
                "cursor": "c2",
            },
            {"limit": 50, "afterCreatedAt": "2021-01-31T00:00:00.000Z"},
        ]
        assert [(call.args[0].window_start, call.args[0].cursor) for call in manager.save_state.call_args_list] == [
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
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state(
        self, _name: str, resume_state: CalComResumeConfig, expected_params: dict[str, Any], MockSession
    ) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page([{"id": 2}], next_cursor=None, has_more=False)])

        rows = _rows(_source("bookings", _make_manager(resume_state)))

        assert rows == [{"id": 2}]
        assert session.send.call_count == 1
        assert params[0] == {"limit": 50, **expected_params}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_created_at_maps_to_after_created_at(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, self._pages())

        _rows(
            _source(
                "bookings",
                should_use_incremental_field=True,
                db_incremental_field_last_value=date(2026, 1, 2),
                incremental_field="createdAt",
            )
        )

        assert params[0]["afterCreatedAt"] == "2026-01-02T00:00:00.000Z"
        assert "afterUpdatedAt" not in params[0]

    def test_unknown_incremental_field_raises(self) -> None:
        with pytest.raises(ValueError, match="no server-side filter"):
            _source(
                "bookings",
                should_use_incremental_field=True,
                db_incremental_field_last_value="2026-01-01",
                incremental_field="startTime",
            )

    @parameterized.expand(
        [
            ("incremental_disabled", False, "2026-01-01"),
            ("no_last_value", True, None),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_filter_param_without_watermark(
        self, _name: str, should_use: bool, last_value: Any, MockSession
    ) -> None:
        session = MockSession.return_value
        params = _wire(session, self._pages())

        _rows(
            _source(
                "bookings",
                should_use_incremental_field=should_use,
                db_incremental_field_last_value=last_value,
                incremental_field="updatedAt",
            )
        )

        assert "afterUpdatedAt" not in params[0]


class TestWebhooksOffsetPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response({"data": [{"id": "resumed"}]})])

        manager = _make_manager(CalComResumeConfig(skip=500))
        rows = _rows(_source("webhooks", manager))

        assert rows == [{"id": "resumed"}]
        assert params[0]["skip"] == 500


class TestSingleFetchEndpoints:
    @parameterized.expand([("event_types",), ("schedules",), ("teams",)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_list_endpoints_yield_single_batch(self, endpoint: str, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"data": [{"id": 1}, {"id": 2}]})])

        manager = _make_manager()
        rows = _rows(_source(endpoint, manager))

        assert rows == [{"id": 1}, {"id": 2}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @parameterized.expand(
        [
            ("bookings", "2026-05-01"),
            ("event_types", "2024-06-14"),
            ("schedules", "2024-06-11"),
            ("teams", None),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_endpoint_versions_pinned_in_headers(
        self, endpoint: str, expected_version: str | None, MockSession
    ) -> None:
        # Omitting cal-api-version silently falls back to legacy endpoint behavior, so the
        # versioned endpoints must pin it.
        session = MockSession.return_value
        session.headers = {}

        _source(endpoint)

        assert session.headers.get("cal-api-version") == expected_version


class TestErrorHandling:
    @parameterized.expand(
        [
            ("bare_list", [{"id": 1}]),
            ("missing_data", {"status": "success"}),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unexpected_payload_shape_fails_loudly(self, _name: str, body: Any, MockSession) -> None:
        # A 200 body without `data` means the response shape changed — fail loud, not silently 0 rows.
        session = MockSession.return_value
        _wire(session, [_response(body)])

        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_source("me"))

    @parameterized.expand(
        [
            ("unauthorized", 401, "Unauthorized"),
            ("forbidden", 403, "Forbidden"),
            ("not_found", 404, "Not Found"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_raise_http_error_with_base_url(
        self, _name: str, status: int, reason: str, MockSession
    ) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [_response({}, status_code=status, url=f"{US_BASE_URL}/bookings?limit=100", reason=reason)],
        )

        with pytest.raises(requests.HTTPError) as exc_info:
            _rows(_source("bookings"))

        # The base URL must be in the message so `get_non_retryable_errors()` can match on it.
        assert f"{status} Client Error: {reason} for url: {US_BASE_URL}/bookings" in str(exc_info.value)


class TestRegionHost:
    @parameterized.expand(
        [
            ("us", "us", "https://api.cal.com/v2/bookings"),
            ("eu", "eu", "https://api.cal.eu/v2/bookings"),
            # An account created before the region field existed has no stored value.
            ("unset", None, "https://api.cal.com/v2/bookings"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_region_selects_the_api_host(self, _name: str, region: str | None, expected_url: str, MockSession) -> None:
        session = MockSession.return_value
        requested_urls: list[str] = []

        def _prepare(request: Any) -> mock.MagicMock:
            requested_urls.append(request.url)
            return mock.MagicMock()

        session.headers = {}
        session.prepare_request.side_effect = _prepare
        session.send.side_effect = [_page([{"id": 1}], next_cursor=None, has_more=False)]

        kwargs: dict[str, Any] = {} if region is None else {"region": region}
        _rows(_source("bookings", **kwargs))

        assert requested_urls == [expected_url]


class TestValidateCredentials:
    def _session(self, response: Any) -> mock.MagicMock:
        session = mock.MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        return session

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, REJECTED_MESSAGE),
            ("forbidden", 403, False, REJECTED_MESSAGE),
            ("server_error", 500, False, "Cal.com returned HTTP 500"),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_valid: bool, expected_message: str | None) -> None:
        response = mock.MagicMock(status_code=status)
        with mock.patch(CAL_COM_SESSION_PATCH, return_value=self._session(response)):
            assert validate_credentials("cal_live_key") == (expected_valid, expected_message)

    def test_connection_error_is_swallowed(self) -> None:
        session = self._session(requests.ConnectionError("boom"))
        with mock.patch(CAL_COM_SESSION_PATCH, return_value=session):
            assert validate_credentials("cal_live_key") == (False, "Could not connect to Cal.com")

    @parameterized.expand(
        [
            ("us", "us", "https://api.cal.com/v2/me"),
            ("eu", "eu", "https://api.cal.eu/v2/me"),
        ]
    )
    def test_probes_the_host_for_the_selected_region(self, _name: str, region: str, expected_url: str) -> None:
        # An EU key probed against the US host comes back 401, which reads as a bad key.
        session = self._session(mock.MagicMock(status_code=200))
        with mock.patch(CAL_COM_SESSION_PATCH, return_value=session):
            assert validate_credentials("cal_live_key", region) == (True, None)

        assert session.get.call_args.args[0] == expected_url


class TestCalComSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_every_endpoint_builds_a_response_named_after_its_schema(self, endpoint: str, MockSession) -> None:
        # The name is the Delta subdirectory: a wrong one writes where nothing reads.
        MockSession.return_value.headers = {}
        response = _source(endpoint, organization_id=ORG_ID)
        assert response.name == endpoint

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
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resolved_org_id_replaces_the_path_placeholder(self, endpoint: str, expected_url: str, MockSession) -> None:
        session = MockSession.return_value
        requested_urls: list[str] = []

        def _prepare(request: Any) -> mock.MagicMock:
            requested_urls.append(request.url)
            return mock.MagicMock()

        session.headers = {}
        session.prepare_request.side_effect = _prepare
        session.send.side_effect = [_response({"data": [{"id": 1}]})]

        assert _rows(_source(endpoint, organization_id=ORG_ID)) == [{"id": 1}]
        assert requested_urls == [expected_url]

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
        with pytest.raises(ValueError, match="not in a Cal.com organization"):
            _source(endpoint)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_org_listings_walk_skip_and_take(self, MockSession) -> None:
        session = MockSession.return_value
        page_size = CAL_COM_ENDPOINTS["organization_users"].page_size
        full_page = [{"id": i} for i in range(page_size)]
        params = _wire(session, [_response({"data": full_page}), _response({"data": [{"id": "last"}]})])

        rows = _rows(_source("organization_users", organization_id=ORG_ID))

        assert len(rows) == page_size + 1
        assert [p["skip"] for p in params] == [0, page_size]
        assert params[0]["take"] == page_size


class TestFanoutEndpoints:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_routing_form_responses_filter_each_form_at_the_watermark(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response({"data": [{"id": "f1"}]}),
                _response({"data": [{"id": 1, "formId": "f1"}]}),
            ],
        )

        rows = _rows(
            _source(
                "routing_form_responses",
                organization_id=ORG_ID,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
                incremental_field="createdAt",
            )
        )

        assert rows == [{"id": 1, "formId": "f1"}]
        # The parent listing takes no watermark of its own; only the child is windowed.
        assert params[1]["afterCreatedAt"] == "2026-01-02T03:04:05.000Z"
        assert params[1]["sortCreatedAt"] == "asc"


class TestBookingAttendees:
    BOOKING = {"uid": "bk1", "createdAt": "2026-01-01T00:00:00.000Z", "updatedAt": "2026-01-05T00:00:00.000Z"}

    def _attendee_session(self, *responses: Response) -> mock.MagicMock:
        session = mock.MagicMock()
        session.get.side_effect = list(responses)
        return session

    @mock.patch(CLIENT_SESSION_PATCH)
    @mock.patch(CAL_COM_SESSION_PATCH)
    def test_a_booking_removed_mid_sync_does_not_fail_the_run(self, MockCalSession, MockClientSession) -> None:
        _wire(MockClientSession.return_value, [_page([self.BOOKING, {**self.BOOKING, "uid": "bk2"}])])
        MockCalSession.return_value = self._attendee_session(
            _response({}, status_code=404, reason="Not Found"),
            _response({"data": [{"id": 6}]}),
        )

        assert [row["bookingUid"] for row in _rows(_source(BOOKING_ATTENDEES_ENDPOINT))] == ["bk2"]

    @mock.patch(CLIENT_SESSION_PATCH)
    @mock.patch(CAL_COM_SESSION_PATCH)
    def test_incremental_sync_bounds_the_bookings_walk(self, MockCalSession, MockClientSession) -> None:
        # Without the window every sync re-reads every booking's attendees, one request each.
        params = _wire(MockClientSession.return_value, [_page([self.BOOKING])])
        MockCalSession.return_value = self._attendee_session(_response({"data": [{"id": 5}]}))

        _rows(
            _source(
                BOOKING_ATTENDEES_ENDPOINT,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
                incremental_field="bookingUpdatedAt",
            )
        )

        assert params[0]["afterUpdatedAt"] == "2026-01-02T03:04:05.000Z"

    @mock.patch(CLIENT_SESSION_PATCH)
    @mock.patch(CAL_COM_SESSION_PATCH)
    def test_resumes_at_the_bookings_page_it_stopped_on(self, MockCalSession, MockClientSession) -> None:
        params = _wire(MockClientSession.return_value, [_page([self.BOOKING])])
        MockCalSession.return_value = self._attendee_session(_response({"data": [{"id": 5}]}))

        manager = _make_manager(CalComResumeConfig(cursor="c2", window_start=FIRST_WINDOW_START))
        _rows(_source(BOOKING_ATTENDEES_ENDPOINT, manager))

        assert params[0]["cursor"] == "c2"

    @mock.patch(CLIENT_SESSION_PATCH)
    @mock.patch(CAL_COM_SESSION_PATCH)
    def test_unexpected_payload_shape_fails_loudly(self, MockCalSession, MockClientSession) -> None:
        _wire(MockClientSession.return_value, [_page([self.BOOKING])])
        MockCalSession.return_value = self._attendee_session(_response({"status": "success"}))

        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_source(BOOKING_ATTENDEES_ENDPOINT))


class TestOrganizationLookup:
    def _session(self, response: Any) -> mock.MagicMock:
        session = mock.MagicMock()
        session.get.return_value = response
        return session

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
        session = self._session(_response({"data": profile}))
        with mock.patch(CAL_COM_SESSION_PATCH, return_value=session):
            assert resolve_organization_id("cal_live_key") == expected

    @parameterized.expand(
        [
            ("admin", 200, None),
            # A plain org member gets a valid-key 403; the fix is a different key, not a retry.
            ("member", 403, "organization member without admin access"),
        ]
    )
    def test_organization_access_probe(self, _name: str, status: int, expected: str | None) -> None:
        session = self._session(mock.MagicMock(status_code=status))
        with mock.patch(CAL_COM_SESSION_PATCH, return_value=session):
            reason = check_organization_access("cal_live_key", ORG_ID)

        assert (reason is None) if expected is None else (expected in (reason or ""))
        assert session.get.call_args.args[0] == f"{US_BASE_URL}/organizations/{ORG_ID}/memberships"
