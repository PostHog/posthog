from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pagerduty import (
    PagerDutySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pagerduty.pagerduty import (
    ANALYTICS_PERSONAL_KEY_ERROR,
    ANALYTICS_READ_ONLY_KEY_ERROR,
    PAGE_SIZE,
    PagerDutyResumeConfig,
    _format_incremental_value,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pagerduty.source import PagerDutySource


def _driver() -> SourceDriver:
    return SourceDriver(PagerDutySource(), PagerDutySourceConfig(api_token="tok"))


class TestFormatIncrementalValue:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            (date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("already-a-cursor", "already-a-cursor"),
        ],
    )
    def test_format(self, value: Any, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestPagination:
    def test_empty_page_stops_iteration(self) -> None:
        # more=True but no items — a missing/empty envelope must stop rather than loop forever.
        result = _driver().run("incidents", [ScriptedResponse(json={"incidents": [], "more": True})])

        assert result.raised is None
        assert result.rows == []
        assert result.params("offset") == ["0"]

    def test_stops_before_crossing_max_offset(self) -> None:
        # PagerDuty 400s when offset + limit exceeds 10000. Full pages that always report more=True
        # must stop before requesting offset=10000 (the first page whose offset+limit would exceed).
        # Always more=True — only the offset ceiling can stop it.
        result = _driver().run("incidents", always(ScriptedResponse(json={"incidents": [{"id": "x"}], "more": True})))

        offsets = result.params("offset")
        assert result.raised is None
        assert offsets[0] == "0"
        assert offsets[-1] == "9900"
        assert "10000" not in offsets

    @pytest.mark.parametrize(
        "endpoint,expected_filter",
        [
            # Without filter=all the table could miss past or future maintenance windows.
            ("maintenance_windows", ["all", "all"]),
            ("business_services", [None, None]),
        ],
    )
    def test_walks_pages_and_sends_static_params_on_every_page(
        self, endpoint: str, expected_filter: list[str | None]
    ) -> None:
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(json={endpoint: [{"id": "R1"}], "more": True}),
                ScriptedResponse(json={endpoint: [{"id": "R2"}], "more": False}),
            ],
        )

        assert result.raised is None
        assert result.paths == [f"/{endpoint}", f"/{endpoint}"]
        assert result.params("offset") == ["0", str(PAGE_SIZE)]
        assert result.params("filter") == expected_filter
        assert [row["id"] for row in result.rows] == ["R1", "R2"]


class TestResume:
    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run(
            "incidents",
            [ScriptedResponse(json={"incidents": [{"id": "x"}], "more": False})],
            resume_state=PagerDutyResumeConfig(offset=PAGE_SIZE),
        )

        assert result.raised is None
        assert result.params("offset") == [str(PAGE_SIZE)]

    def test_fan_out_skips_parents_completed_before_resume(self) -> None:
        result = _driver().run(
            "incident_alerts",
            route(
                {
                    "/incidents": [ScriptedResponse(json={"incidents": [{"id": "P1"}, {"id": "P2"}], "more": False})],
                    "/incidents/P2/alerts": [ScriptedResponse(json={"alerts": [{"id": "A2"}], "more": False})],
                }
            ),
            resume_state=PagerDutyResumeConfig(
                fanout_state={"completed": ["/incidents/P1/alerts"], "current": None, "child_state": None}
            ),
        )

        assert result.raised is None
        assert result.paths == ["/incidents", "/incidents/P2/alerts"]
        assert [row["id"] for row in result.rows] == ["A2"]
        assert result.saved_states[-1].fanout_state["completed"] == ["/incidents/P1/alerts", "/incidents/P2/alerts"]


class TestFanOut:
    @pytest.mark.parametrize(
        "endpoint,parent_path,parent_envelope,child_envelope,parent_column,expected_user_id",
        [
            ("incident_alerts", "/incidents", "incidents", "alerts", "incident_id", None),
            ("team_members", "/teams", "teams", "members", "team_id", "U1"),
            ("incident_notes", "/incidents", "incidents", "notes", "incident_id", "U1"),
        ],
    )
    def test_reads_each_parents_children_and_tags_the_parent_id(
        self,
        endpoint: str,
        parent_path: str,
        parent_envelope: str,
        child_envelope: str,
        parent_column: str,
        expected_user_id: str | None,
    ) -> None:
        child_row = {"id": "C1", "user": {"id": "U1", "type": "user_reference"}}
        result = _driver().run(
            endpoint,
            route(
                {
                    parent_path: [
                        ScriptedResponse(json={parent_envelope: [{"id": "P1"}, {"id": "P2"}], "more": False})
                    ],
                    # P1 was removed after the parent listing; its 404 must not fail the sync.
                    f"{parent_path}/P1/{child_envelope}": [ScriptedResponse(status=404, json={"error": {}})],
                    f"{parent_path}/P2/{child_envelope}": [
                        ScriptedResponse(json={child_envelope: [child_row], "more": True}),
                        ScriptedResponse(json={child_envelope: [child_row], "more": False}),
                    ],
                }
            ),
        )

        assert result.raised is None
        assert result.paths == [
            parent_path,
            f"{parent_path}/P1/{child_envelope}",
            f"{parent_path}/P2/{child_envelope}",
            f"{parent_path}/P2/{child_envelope}",
        ]
        assert result.params("offset") == ["0", "0", "0", str(PAGE_SIZE)]
        assert [row[parent_column] for row in result.rows] == ["P2", "P2"]
        assert all(f"_{parent_envelope}_id" not in row for row in result.rows)
        assert [row.get("user_id") for row in result.rows] == [expected_user_id, expected_user_id]


class TestIncidentAnalytics:
    @pytest.mark.parametrize(
        "should_use_incremental_field,last_value,expected_filters",
        [
            (False, None, None),
            # The first incremental sync has no watermark yet, so it reads the full default window.
            (True, None, None),
            (True, datetime(2026, 1, 1, tzinfo=UTC), {"updated_after": "2026-01-01T00:00:00+00:00"}),
        ],
    )
    def test_walks_body_cursor_pages_until_more_is_false(
        self, should_use_incremental_field: bool, last_value: datetime | None, expected_filters: Any
    ) -> None:
        result = _driver().run(
            "incident_analytics",
            [
                ScriptedResponse(json={"data": [{"id": "I1"}, {"id": "I2"}], "last": "c2", "more": True}),
                # The final page still carries its `last` cursor.
                ScriptedResponse(json={"data": [{"id": "I3"}], "last": "c3", "more": False}),
            ],
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert [request.method for request in result.requests] == ["POST", "POST"]
        assert result.paths == ["/analytics/raw/incidents", "/analytics/raw/incidents"]
        bodies = [request.json() for request in result.requests]
        assert [body.get("starting_after") for body in bodies] == [None, "c2"]
        assert all(body["order"] == "asc" and body["order_by"] == "created_at" for body in bodies)
        assert [body.get("filters") for body in bodies] == [expected_filters, expected_filters]
        assert [row["id"] for row in result.rows] == ["I1", "I2", "I3"]
        assert result.saved_states == [PagerDutyResumeConfig(cursor="c2")]
        assert result.response is not None
        assert result.response.sort_mode is None

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "incident_analytics",
            [ScriptedResponse(json={"data": [{"id": "I3"}], "last": "c3", "more": False})],
            resume_state=PagerDutyResumeConfig(cursor="c2"),
        )

        assert result.raised is None
        assert [request.json().get("starting_after") for request in result.requests] == ["c2"]
        assert [row["id"] for row in result.rows] == ["I3"]


class TestOncalls:
    @pytest.mark.parametrize(
        "oncall,expected_id,expected_schedule_id",
        [
            (
                {
                    "escalation_policy": {"id": "EP1"},
                    "escalation_level": 1,
                    "user": {"id": "U1"},
                    "schedule": {"id": "S1"},
                    "start": "2026-01-05T09:00:00Z",
                    "end": "2026-01-12T09:00:00Z",
                },
                "EP1:1:U1:S1:2026-01-05T09:00:00Z",
                "S1",
            ),
            (
                # A direct user target on an escalation rule: no schedule and a permanent on-call.
                {
                    "escalation_policy": {"id": "EP1"},
                    "escalation_level": 2,
                    "user": {"id": "U2"},
                    "schedule": None,
                    "start": None,
                    "end": None,
                },
                "EP1:2:U2::",
                None,
            ),
        ],
    )
    def test_rows_get_flat_reference_ids_and_a_derived_id(
        self, oncall: dict[str, Any], expected_id: str, expected_schedule_id: str | None
    ) -> None:
        result = _driver().run("oncalls", [ScriptedResponse(json={"oncalls": [oncall], "more": False})])

        assert result.raised is None
        assert result.paths == ["/oncalls"]
        [row] = result.rows
        assert row["id"] == expected_id
        assert row["escalation_policy_id"] == "EP1"
        assert row["user_id"] == oncall["user"]["id"]
        assert row["schedule_id"] == expected_schedule_id


class TestIncremental:
    def test_incremental_endpoint_sends_since_and_sort(self) -> None:
        result = _driver().run(
            "incidents",
            [ScriptedResponse(json={"incidents": [{"id": "1"}], "more": False})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.params("sort_by") == ["created_at:asc"]
        assert result.params("since") == ["2026-01-01T00:00:00+00:00"]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code,expected_ok,expected_status",
        [
            (403, False, 403),
        ],
    )
    def test_status_mapping(self, status_code: int, expected_ok: bool, expected_status: int) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            ok, status, _error = validate_credentials("tok")

        assert ok is expected_ok
        assert status == expected_status
        assert {request.path for request in network.requests_log} == {"/users"}

    @pytest.mark.parametrize(
        "endpoint,expected_path",
        [
            ("change_events", "/change_events"),
            # A fan-out child path carries an `{id}` placeholder, so the probe reads the parent list.
            ("incident_alerts", "/incidents"),
            ("team_members", "/teams"),
            ("incident_notes", "/incidents"),
        ],
    )
    def test_probe_path(self, endpoint: str, expected_path: str) -> None:
        with scripted_network(always(ScriptedResponse(status=200))) as network:
            ok, _status, _error = validate_credentials("tok", endpoint)

        assert ok is True
        assert [request.path for request in network.requests_log] == [expected_path]

    @pytest.mark.parametrize(
        "status_code,expected_ok,expected_error",
        [
            (200, True, None),
            # PagerDuty restricts read-only keys to GET requests.
            (403, False, ANALYTICS_READ_ONLY_KEY_ERROR),
            # Personal keys must send a team_ids or service_ids filter.
            (400, False, ANALYTICS_PERSONAL_KEY_ERROR),
        ],
    )
    def test_analytics_probe_posts_to_the_analytics_endpoint(
        self, status_code: int, expected_ok: bool, expected_error: str | None
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))) as network:
            ok, status, error = validate_credentials("tok", "incident_analytics")

        assert (ok, status, error) == (expected_ok, status_code, expected_error)
        [request] = network.requests_log
        assert (request.method, request.path) == ("POST", "/analytics/raw/incidents")

    def test_transport_failure_returns_zero_status(self) -> None:
        with scripted_network(always(ConnectionError("no network"))) as network:
            ok, status, error = validate_credentials("tok")

        assert ok is False
        assert status == 0
        assert error is not None
        assert {request.path for request in network.requests_log} == {"/users"}


class TestPlanGatedEndpoints:
    @pytest.mark.parametrize(
        "endpoint,status_code,body,feature,expected_path",
        [
            # The statuses PagerDuty answers on an account whose plan lacks the feature. The 402
            # body keeps PagerDuty's documented error code 2014, which the client appends to the
            # raised message as "api error: code=2014".
            (
                "teams",
                402,
                {"error": {"code": 2014, "message": "Required abilities are unavailable"}},
                "teams",
                "/teams",
            ),
            ("priorities", 404, {"error": {"message": "Not Found"}}, "incident priorities", "/priorities"),
            # The fan-out parent request fails first, inside the child resource.
            (
                "team_members",
                402,
                {"error": {"code": 2014, "message": "Required abilities are unavailable"}},
                "teams",
                "/teams",
            ),
        ],
    )
    def test_plan_gated_endpoint_syncs_no_rows_and_warns(
        self, endpoint: str, status_code: int, body: dict[str, Any], feature: str, expected_path: str
    ) -> None:
        logger = MagicMock()
        result = _driver().run(endpoint, [ScriptedResponse(status=status_code, json=body)], logger=logger)

        assert result.raised is None
        assert result.rows == []
        assert result.paths == [expected_path]
        warning = logger.warning.call_args.args[0]
        assert f"does not include {feature}" in warning
        assert f"the {endpoint} table synced no rows" in warning

    def test_ungated_endpoint_still_fails_on_404(self) -> None:
        # Only endpoints declaring a plan-gated feature swallow a 404; elsewhere it is a real
        # failure the sync must surface.
        result = _driver().run("users", [ScriptedResponse(status=404, json={"error": {"message": "boom"}})])

        assert isinstance(result.raised, HTTPError)
        assert result.paths == ["/users"]

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_plan_gated_endpoint_still_fails_on_other_statuses(self, status_code: int) -> None:
        # Only 402 and 404 mean "your plan does not include this"; a credential problem on a gated
        # endpoint must still fail rather than be reported as an empty table.
        logger = MagicMock()
        result = _driver().run(
            "teams", [ScriptedResponse(status=status_code, json={"error": {"message": "boom"}})], logger=logger
        )

        assert isinstance(result.raised, HTTPError)
        assert result.paths == ["/teams"]
        logger.warning.assert_not_called()

    @pytest.mark.parametrize(
        "endpoint,wrong_status",
        [
            # teams is plan-gated at 402, not 404; priorities is plan-gated at 404, not 402. The
            # gated status is endpoint-specific, so the other status on that same endpoint is a
            # genuine failure and must still raise rather than being read as "plan lacks it".
            ("teams", 404),
            ("priorities", 402),
        ],
    )
    def test_plan_gated_endpoint_fails_on_the_other_endpoints_gated_status(
        self, endpoint: str, wrong_status: int
    ) -> None:
        logger = MagicMock()
        result = _driver().run(
            endpoint, [ScriptedResponse(status=wrong_status, json={"error": {"message": "boom"}})], logger=logger
        )

        assert isinstance(result.raised, HTTPError)
        assert result.paths == [f"/{endpoint}"]
        logger.warning.assert_not_called()
