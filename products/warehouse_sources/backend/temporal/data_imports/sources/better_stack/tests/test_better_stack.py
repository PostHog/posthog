from datetime import UTC, date, datetime
from typing import Any

import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.better_stack.better_stack import (
    BETTER_STACK_BASE_URL,
    BetterStackResumeConfig,
    BetterStackUntrustedURLError,
    _explode_response_times,
    _format_from_date,
    _validate_pagination_url,
    probe_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.better_stack.settings import (
    BETTER_STACK_ORG_BASE_URL,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.better_stack.source import BetterStackSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.betterstack import (
    BetterStackSourceConfig,
)


def _response(
    items: list[dict[str, Any]] | None, next_url: str | None = None, *, drop_data: bool = False
) -> ScriptedResponse:
    body: dict[str, Any] = {"pagination": {"next": next_url}}
    if not drop_data:
        body["data"] = items or []
    return ScriptedResponse(json=body)


def _driver() -> SourceDriver:
    return SourceDriver(BetterStackSource(), BetterStackSourceConfig(api_token="bs_test"))


class TestFormatFromDate:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04"),
            ("date_value", date(2026, 3, 4), "2026-03-04"),
            ("string_passthrough", "2026-03-04", "2026-03-04"),
        ]
    )
    def test_formats_as_date_only(self, _name: str, value: object, expected: str) -> None:
        # Better Stack's `from` filter takes YYYY-MM-DD, not a full timestamp.
        assert _format_from_date(value) == expected


class TestValidatePaginationUrl:
    @parameterized.expand(
        [
            ("uptime_host", "https://uptime.betterstack.com/api/v3/incidents?page=2&per_page=50"),
            # Team members paginate on the account-level host.
            ("org_host", "https://betterstack.com/api/v2/team-members?page=2"),
        ]
    )
    def test_api_origin_url_is_returned_unchanged(self, _name: str, url: str) -> None:
        assert _validate_pagination_url(url) == url

    @parameterized.expand(
        [
            ("other_host", "https://evil.example.com/api/v3/incidents"),
            ("http_downgrade", "http://uptime.betterstack.com/api/v3/incidents"),
            ("userinfo_confusion", "https://uptime.betterstack.com@evil.example.com/api/v3/incidents"),
            ("wrong_path", "https://uptime.betterstack.com/steal-token"),
        ]
    )
    def test_off_origin_urls_are_refused(self, _name: str, url: str) -> None:
        # A poisoned resume state or hostile response must not retarget the bearer-token request.
        with pytest.raises(BetterStackUntrustedURLError):
            _validate_pagination_url(url)


class TestPagination:
    def test_follows_pagination_next_and_flattens(self) -> None:
        second = "https://uptime.betterstack.com/api/v3/incidents?page=2&per_page=50"
        result = _driver().run(
            "incidents",
            [
                _response([{"id": "1", "type": "incident", "attributes": {"cause": "Timeout"}}], next_url=second),
                _response([{"id": "2", "type": "incident", "attributes": {"cause": "Status 500"}}]),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"id": "1", "type": "incident", "cause": "Timeout"},
            {"id": "2", "type": "incident", "cause": "Status 500"},
        ]
        assert result.requests[0].path == "/api/v3/incidents"
        assert result.requests[0].param("per_page") == "50"
        # The next-page URL is self-contained; the original params must not be re-appended.
        assert result.urls[1] == second
        assert result.queries[1] == {"page": ("2",), "per_page": ("50",)}

    def test_resumes_from_saved_next_url(self) -> None:
        resume_url = "https://uptime.betterstack.com/api/v3/incidents?page=3&per_page=50"
        result = _driver().run(
            "incidents",
            [_response([{"id": "9", "attributes": {"cause": "Z"}}])],
            resume_state=BetterStackResumeConfig(next_url=resume_url),
        )

        # Starts at the resumed URL, not the freshly-built first page.
        assert result.raised is None
        assert result.rows == [{"id": "9", "cause": "Z"}]
        assert result.urls == [resume_url]

    @parameterized.expand(
        [
            ("empty_collection", False),
            # Old envelope always carries `data`; a body without it is treated as an empty page.
            ("missing_data_key", True),
        ]
    )
    def test_empty_collection_yields_nothing(self, _name: str, drop_data: bool) -> None:
        result = _driver().run("incidents", [_response([], drop_data=drop_data)])
        assert result.raised is None
        assert result.rows == []
        assert len(result.requests) == 1
        assert result.saved_states == []

    def test_off_origin_next_url_is_refused(self) -> None:
        result = _driver().run(
            "incidents",
            [_response([{"id": "1", "attributes": {}}], next_url="https://evil.example.com/api/v3/incidents?page=2")],
        )

        assert isinstance(result.raised, BetterStackUntrustedURLError)
        assert len(result.requests) == 1

    def test_poisoned_resume_url_is_refused(self) -> None:
        result = _driver().run(
            "incidents",
            [],
            resume_state=BetterStackResumeConfig(next_url="https://evil.example.com/api/v3/incidents"),
        )
        assert isinstance(result.raised, BetterStackUntrustedURLError)
        # Refused before any request carries the bearer token off-origin.
        assert result.requests == []


class TestIncrementalParams:
    @parameterized.expand(
        [
            (
                "incremental_endpoint_filters_from_watermark_date",
                "incidents",
                True,
                datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
                {"per_page": 50, "from": "2026-03-04"},
            ),
            ("incremental_first_sync_has_no_filter", "incidents", True, None, {"per_page": 50}),
            ("incremental_disabled_has_no_filter", "incidents", False, datetime(2026, 3, 4), {"per_page": 50}),
            (
                "full_refresh_endpoint_never_filters",
                "monitors",
                True,
                datetime(2026, 3, 4, tzinfo=UTC),
                {"per_page": 250},
            ),
        ]
    )
    def test_initial_request_params(
        self,
        _name: str,
        endpoint: str,
        should_use_incremental_field: bool,
        last_value: Any,
        expected_params: dict[str, Any],
    ) -> None:
        result = _driver().run(
            endpoint,
            [_response([{"id": "1", "attributes": {}}])],
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert result.requests[0].query == {key: (str(value),) for key, value in expected_params.items()}


class TestProbeCredentials:
    @parameterized.expand([("ok", 200), ("unauthorized", 401), ("forbidden", 403)])
    def test_returns_status_code(self, _name: str, status_code: int) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            assert probe_credentials("bs_test", "v3", "incidents") == status_code
        assert network.requests_log[0].path == "/api/v3/incidents"


def _object_response(data: dict[str, Any] | list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json={"data": data})


class TestExplodeResponseTimes:
    def test_one_row_per_region_measurement(self) -> None:
        rows = _explode_response_times(
            {
                "id": "270985",
                "type": "monitor_response_times",
                "monitor_id": "270985",
                "attributes": {
                    "regions": [
                        {
                            "region": "us",
                            "response_times": [
                                {"at": "2026-04-03T11:00:57.000Z", "response_time": 0.47273},
                                {"at": "2026-04-03T11:03:57.000Z", "response_time": 0.51},
                            ],
                        },
                        {"region": "eu", "response_times": [{"at": "2026-04-03T11:00:59.000Z", "response_time": 0.19}]},
                    ]
                },
            }
        )

        # `id`/`type` are dropped: `id` only repeats the monitor id, which `monitor_id` carries.
        assert rows == [
            {"monitor_id": "270985", "region": "us", "at": "2026-04-03T11:00:57.000Z", "response_time": 0.47273},
            {"monitor_id": "270985", "region": "us", "at": "2026-04-03T11:03:57.000Z", "response_time": 0.51},
            {"monitor_id": "270985", "region": "eu", "at": "2026-04-03T11:00:59.000Z", "response_time": 0.19},
        ]

    @parameterized.expand([("no_regions", {}), ("empty_regions", {"regions": []}), ("null_regions", {"regions": None})])
    def test_monitor_without_measurements_yields_no_rows(self, _name: str, attributes: dict[str, Any]) -> None:
        assert _explode_response_times({"id": "1", "monitor_id": "1", "attributes": attributes}) == []


class TestOrganizationHost:
    @parameterized.expand([("team_members", "/v2/team-members"), ("roles", "/v2/roles")])
    def test_account_level_endpoints_use_the_org_host(self, endpoint: str, path: str) -> None:
        result = _driver().run(endpoint, [_response([{"id": "101", "type": "team_member", "attributes": {}}])])

        # The Uptime subdomain 404s both routes; they are served from betterstack.com.
        assert result.raised is None
        assert result.requests[0].origin == "https://betterstack.com"
        assert result.requests[0].path == f"/api{path}"


class TestApiVersionDispatch:
    @parameterized.expand(
        [
            ("policies_v2", "escalation_policies", "v2", "/api/v2/policies"),
            ("policies_v3", "escalation_policies", "v3", "/api/v3/policies"),
            ("policies_unpinned_uses_default", "escalation_policies", None, "/api/v3/policies"),
            ("incidents_v2", "incidents", "v2", "/api/v3/incidents"),
            ("incidents_v3", "incidents", "v3", "/api/v3/incidents"),
            ("monitors_v2", "monitors", "v2", "/api/v2/monitors"),
            ("monitors_v3", "monitors", "v3", "/api/v2/monitors"),
        ]
    )
    def test_request_path_follows_the_pin(
        self, _name: str, endpoint: str, api_version: str | None, expected_path: str
    ) -> None:
        result = _driver().run(endpoint, [_response([{"id": "1", "attributes": {}}])], api_version=api_version)

        assert result.raised is None
        assert result.paths == [expected_path]


class TestFanout:
    @parameterized.expand(
        [
            # (endpoint, parent path, child path, parent id column)
            ("heartbeat_availability", "/v2/heartbeats", "/v2/heartbeats/1/availability", "heartbeat_id"),
            ("status_page_resources", "/v2/status-pages", "/v2/status-pages/1/resources", "status_page_id"),
        ]
    )
    def test_child_is_bound_to_its_parent(
        self, endpoint: str, parent_path: str, child_path: str, parent_key: str
    ) -> None:
        result = _driver().run(
            endpoint,
            [
                _response([{"id": "1", "attributes": {}}]),
                _object_response({"id": "9", "attributes": {"availability": 99.5}}),
            ],
        )

        # Each parent has its own resolve param, so a wrong one leaves the path placeholder unbound.
        assert result.raised is None
        assert result.paths == [f"/api{parent_path}", f"/api{child_path}"]
        assert result.requests[0].param("per_page") == "250"
        assert result.rows == [{"id": "9", parent_key: "1", "availability": 99.5}]

    @parameterized.expand(
        [
            # The comment watermark floors the incidents walk, so a sync only re-fetches comments
            # for incidents that started on or after the newest comment already collected.
            (
                "incremental_bounds_the_incidents_walk",
                True,
                datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
                {"per_page": 50, "from": "2026-03-04"},
            ),
            ("first_sync_walks_every_incident", True, None, {"per_page": 50}),
            ("full_refresh_walks_every_incident", False, datetime(2026, 3, 4, tzinfo=UTC), {"per_page": 50}),
        ]
    )
    def test_incident_comments_parent_window(
        self, _name: str, should_use_incremental_field: bool, last_value: Any, expected: dict[str, Any]
    ) -> None:
        result = _driver().run(
            "incident_comments",
            [_response([])],
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert result.requests[0].query == {key: (str(value),) for key, value in expected.items()}

    def test_fanout_state_is_saved_and_resumed_per_parent(self) -> None:
        result = _driver().run(
            "monitor_availability",
            [
                _response([{"id": "1", "attributes": {}}, {"id": "2", "attributes": {}}]),
                _object_response({"id": "1", "attributes": {"availability": 99.0}}),
                _object_response({"id": "2", "attributes": {"availability": 98.0}}),
            ],
        )

        assert result.raised is None
        saved = result.saved_states[-1].fanout_state
        assert saved["completed"] == ["/v2/monitors/1/sla", "/v2/monitors/2/sla"]

        # A rerun seeded with that state skips both parents and issues no child request.
        resumed = _driver().run(
            "monitor_availability",
            [_response([{"id": "1", "attributes": {}}, {"id": "2", "attributes": {}}])],
            resume_state=BetterStackResumeConfig(fanout_state=saved),
        )

        assert resumed.raised is None
        assert resumed.rows == []
        assert resumed.paths == ["/api/v2/monitors"]


class TestProbeCredentialsForFanoutEndpoints:
    @parameterized.expand(
        [
            ("monitor_availability", "v3", f"{BETTER_STACK_BASE_URL}/v2/monitors?per_page=1"),
            ("monitor_response_times", "v3", f"{BETTER_STACK_BASE_URL}/v2/monitors?per_page=1"),
            ("incident_comments", "v3", f"{BETTER_STACK_BASE_URL}/v3/incidents?per_page=1"),
            ("heartbeat_availability", "v3", f"{BETTER_STACK_BASE_URL}/v2/heartbeats?per_page=1"),
            ("status_page_resources", "v3", f"{BETTER_STACK_BASE_URL}/v2/status-pages?per_page=1"),
            ("on_call_events", "v3", f"{BETTER_STACK_BASE_URL}/v2/on-calls?per_page=1"),
            ("on_call_rotations", "v3", f"{BETTER_STACK_BASE_URL}/v2/on-calls?per_page=1"),
            ("team_members", "v3", f"{BETTER_STACK_ORG_BASE_URL}/v2/team-members?per_page=1"),
            ("escalation_policies", "v2", f"{BETTER_STACK_BASE_URL}/v2/policies?per_page=1"),
            ("escalation_policies", "v3", f"{BETTER_STACK_BASE_URL}/v3/policies?per_page=1"),
        ]
    )
    def test_probes_a_reachable_collection(self, endpoint: str, api_version: str, expected_url: str) -> None:
        with scripted_network([ScriptedResponse()]) as network:
            probe_credentials("bs_test", api_version, endpoint)

        # A fan-out child has no collection of its own, so its parent is probed instead.
        assert network.requests_log[0].url == expected_url
