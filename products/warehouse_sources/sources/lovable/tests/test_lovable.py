from datetime import UTC, date, datetime
from typing import Any

import time_machine

from parameterized import parameterized

from products.warehouse_sources.sources.lovable._config import LovableSourceConfig
from products.warehouse_sources.sources.lovable.lovable import (
    LovableResumeConfig,
    _ParentRef,
    analytics_window,
    breakdown_days,
    check_endpoint_permissions,
    resume_position,
    validate_credentials,
)
from products.warehouse_sources.sources.lovable.source import LovableSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, scripted_network


def _page(rows: list[dict[str, Any]], next_cursor: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(
        json={"data": rows, "pagination": {"has_more": next_cursor is not None, "next_cursor": next_cursor}}
    )


def _error(status_code: int, error_type: str = "payment_required") -> ScriptedResponse:
    return ScriptedResponse(
        status=status_code,
        json={"status": status_code, "type": error_type, "title": "Nope", "request_id": "req-1"},
    )


def _driver() -> SourceDriver:
    return SourceDriver(LovableSource(), LovableSourceConfig(api_key="lov_key"))


class TestLovableSourceTransport:
    @parameterized.expand(
        [
            ("v1_sends_no_version_header", "v1", {}),
            ("dated_version_pins_the_header", "2026-09-11", {"Lovable-Version": "2026-09-11"}),
        ]
    )
    def test_version_selects_the_header_on_the_v1_path(
        self, _name: str, api_version: str, expected_headers: dict[str, str]
    ) -> None:
        result = _driver().run("Workspaces", [_page([{"id": "ws-1"}])], api_version=api_version)

        assert result.raised is None
        assert result.urls == ["https://api.lovable.dev/v1/workspaces?limit=100"]
        assert result.requests[0].headers["accept"] == "application/json"
        assert result.requests[0].headers["lovable-api-key"] == "lov_key"
        if expected_headers:
            assert result.requests[0].headers["lovable-version"] == expected_headers["Lovable-Version"]
        else:
            assert "lovable-version" not in result.requests[0].headers

    def test_account_endpoint_follows_the_cursor(self) -> None:
        result = _driver().run(
            "Workspaces",
            [_page([{"id": "ws-1"}], next_cursor="c1"), _page([{"id": "ws-2"}])],
            api_version="v1",
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["ws-1", "ws-2"]
        assert result.urls[0] == "https://api.lovable.dev/v1/workspaces?limit=100"
        assert result.requests[1].param("cursor") == "c1"

    @parameterized.expand(
        [
            ("Projects", "https://api.lovable.dev/v1/projects?limit=100&workspace_id=ws-1"),
            ("WorkspaceMembers", "https://api.lovable.dev/v1/workspaces/ws-1/members?limit=50"),
        ]
    )
    def test_dated_version_drops_the_filters_it_no_longer_accepts(self, endpoint: str, expected_url: str) -> None:
        result = _driver().run(endpoint, [_page([{"id": "ws-1"}]), _page([{"id": "row-1"}])], api_version="2026-09-11")

        assert result.raised is None
        assert result.urls[1] == expected_url

    def test_project_endpoint_fans_out_through_workspaces_and_stamps_both_parents(self) -> None:
        result = _driver().run(
            "ProjectCollaborators",
            [
                _page([{"id": "ws-1"}]),
                _page([{"id": "p-1"}, {"id": "p-2"}]),
                _page([{"user_id": "u-1"}]),
                _page([{"user_id": "u-2"}]),
            ],
            api_version="v1",
        )

        assert result.raised is None
        assert [(row["workspace_id"], row["project_id"], row["user_id"]) for row in result.rows] == [
            ("ws-1", "p-1", "u-1"),
            ("ws-1", "p-2", "u-2"),
        ]
        assert result.paths[2:] == ["/v1/projects/p-1/collaborators", "/v1/projects/p-2/collaborators"]

    @parameterized.expand(
        [
            ("fresh_run_walks_every_scan", None, ["/v1/projects/p-1/security-scans/s-1/findings"], None),
            (
                "resume_continues_the_checkpointed_scan",
                LovableResumeConfig(workspace_id="ws-1", project_id="p-1", scan_id="s-2", cursor="c1"),
                [],
                "c1",
            ),
        ]
    )
    def test_findings_fan_out_through_scans_and_stamp_the_scan(
        self,
        _name: str,
        resume_state: LovableResumeConfig | None,
        earlier_scan_paths: list[str],
        expected_cursor: str | None,
    ) -> None:
        findings = [_page([{"id": "f-1"}])] if resume_state is None else []
        result = _driver().run(
            "ProjectSecurityScanFindings",
            [
                _page([{"id": "ws-1"}]),
                _page([{"id": "p-1"}]),
                _page([{"id": "s-1"}, {"id": "s-2"}]),
                *findings,
                _page([{"id": "f-1"}]),
            ],
            api_version="2026-09-11",
            resume_state=resume_state,
        )

        assert result.raised is None
        assert result.paths[3:] == [*earlier_scan_paths, "/v1/projects/p-1/security-scans/s-2/findings"]
        assert result.requests[-1].param("cursor") == expected_cursor
        assert [(row["project_id"], row["scan_id"], row["id"]) for row in result.rows][-1] == ("p-1", "s-2", "f-1")

    def test_project_analytics_skips_unpublished_projects(self) -> None:
        result = _driver().run(
            "ProjectAnalytics",
            [
                _page([{"id": "ws-1"}]),
                _page([{"id": "p-draft", "is_published": False}, {"id": "p-live", "is_published": True}]),
                ScriptedResponse(json={"time_series": {}}),
            ],
            api_version="2026-09-11",
        )

        assert result.raised is None
        assert result.paths[2:] == ["/v1/projects/p-live/analytics"]

    def test_analytics_pivots_each_bucket_into_one_row(self) -> None:
        result = _driver().run(
            "WorkspaceAnalytics",
            [
                _page([{"id": "ws-1"}]),
                ScriptedResponse(
                    json={
                        "time_series": {
                            "visitors": {
                                "label": "visitors",
                                "total": 5,
                                "data": [
                                    {"timestamp": "2026-10-02T00:00:00Z", "value": 3},
                                    {"timestamp": "2026-10-01T00:00:00Z", "value": 2},
                                ],
                            },
                            "bounce_rate": {
                                "label": "bounce_rate",
                                "total": 40.0,
                                "data": [{"timestamp": "2026-10-01T00:00:00Z", "value": 40.0}],
                            },
                        }
                    }
                ),
            ],
            api_version="2026-09-11",
        )

        assert result.raised is None
        assert result.rows == [
            {"timestamp": "2026-10-01T00:00:00Z", "visitors": 2, "bounce_rate": 40.0, "workspace_id": "ws-1"},
            {"timestamp": "2026-10-02T00:00:00Z", "visitors": 3, "workspace_id": "ws-1"},
        ]
        analytics_request = result.requests[1]
        assert analytics_request.path == "/v1/workspaces/ws-1/analytics"
        assert analytics_request.param("limit") is None
        assert analytics_request.param("starts_at") is not None
        assert analytics_request.param("ends_at") is not None

    @parameterized.expand(
        [
            ("fresh_run_reads_each_complete_day", None, ["2026-10-21", "2026-10-22"]),
            (
                "resume_continues_at_the_checkpointed_day",
                LovableResumeConfig(workspace_id="ws-1", project_id="p-live", cursor="2026-10-22"),
                ["2026-10-22"],
            ),
        ]
    )
    def test_breakdowns_read_one_day_per_request_and_rank_each_list(
        self, _name: str, resume_state: LovableResumeConfig | None, expected_days: list[str]
    ) -> None:
        day_bodies = {
            "2026-10-21": {
                "pages": [{"label": "/pricing", "visitors": 12}, {"label": "/", "visitors": 7}],
                "sources": [{"label": "Direct", "visitors": 9}],
                "devices": [],
                "countries": [{"label": "Unknown", "visitors": 1}, {"visitors": 4}],
            },
            "2026-10-22": {
                "pages": [],
                "sources": [],
                "devices": [{"label": "Desktop", "visitors": 3}],
                "countries": [],
            },
        }
        with time_machine.travel(datetime(2026, 10, 23, 12, 0, tzinfo=UTC), tick=False):
            result = _driver().run(
                "ProjectAnalyticsBreakdowns",
                [
                    _page([{"id": "ws-1"}]),
                    _page([{"id": "p-draft", "is_published": False}, {"id": "p-live", "is_published": True}]),
                    *[ScriptedResponse(json=day_bodies[day]) for day in expected_days],
                ],
                api_version="2026-09-11",
                incremental_field="timestamp",
                db_incremental_field_last_value="2026-10-21T00:00:00Z",
                resume_state=resume_state,
            )

        assert result.raised is None
        breakdown_requests = result.requests[2:]
        assert [request.path for request in breakdown_requests] == ["/v1/projects/p-live/analytics/breakdowns"] * len(
            expected_days
        )
        assert [
            (request.param("starts_at"), request.param("ends_at"), request.param("limit"))
            for request in breakdown_requests
        ] == [(f"{day}T00:00:00Z", f"{day}T23:59:59Z", None) for day in expected_days]
        expected_rows = [
            ("2026-10-21T00:00:00Z", "pages", 1, "/pricing", 12),
            ("2026-10-21T00:00:00Z", "pages", 2, "/", 7),
            ("2026-10-21T00:00:00Z", "sources", 1, "Direct", 9),
            ("2026-10-21T00:00:00Z", "countries", 1, "Unknown", 1),
            ("2026-10-22T00:00:00Z", "devices", 1, "Desktop", 3),
        ]
        assert [
            (row["timestamp"], row["breakdown"], row["rank"], row["label"], row["visitors"]) for row in result.rows
        ] == [row for row in expected_rows if row[0][:10] in expected_days]
        assert all((row["workspace_id"], row["project_id"]) == ("ws-1", "p-live") for row in result.rows)
        assert [state.cursor for state in result.saved_states] == [
            "2026-10-22" if day == "2026-10-21" else None for day in expected_days
        ]
        assert result.final_state is None

    def test_parents_without_an_id_are_skipped(self) -> None:
        result = _driver().run(
            "WorkspaceMembers",
            [_page([{"name": "no id here"}, {"id": "ws-2"}]), _page([{"user_id": "u-1"}])],
            api_version="v1",
        )

        assert result.raised is None
        assert [row["workspace_id"] for row in result.rows] == ["ws-2"]
        assert result.paths == ["/v1/workspaces", "/v1/workspaces/ws-2/members"]

    @parameterized.expand(
        [
            ("v1", "Workspaces", ["id"], "created_at"),
            ("v1", "Projects", ["id"], "created_at"),
            ("v1", "WorkspaceMembers", ["workspace_id", "user_id"], "invited_at"),
            ("v1", "WorkspaceCreditHistory", ["workspace_id", "id"], "occurred_at"),
            ("v1", "ProjectCollaborators", ["project_id", "user_id"], None),
            ("v1", "ProjectSecurityScans", ["project_id", "scan_id"], "started_at"),
            ("v1", "ProjectPiiLabels", ["project_id", "id"], "found_at"),
            ("2026-09-11", "Workspaces", ["id"], "created_at"),
            ("2026-09-11", "Projects", ["id"], "created_at"),
            ("2026-09-11", "WorkspaceMembers", ["workspace_id", "user_id"], None),
            ("2026-09-11", "ProjectSecurityScans", ["project_id", "id"], "started_at"),
            ("2026-09-11", "ProjectPiiLabels", ["project_id", "id"], "found_at"),
            ("2026-09-11", "WorkspaceGroups", ["workspace_id", "id"], "created_at"),
            ("2026-09-11", "ProjectSecurityScanFindings", ["project_id", "scan_id", "id"], "created_at"),
            ("2026-09-11", "ProjectAnalytics", ["project_id", "timestamp"], "timestamp"),
            ("2026-09-11", "WorkspaceAnalytics", ["workspace_id", "timestamp"], "timestamp"),
        ]
    )
    def test_primary_keys_and_partitioning_per_endpoint(
        self, api_version: str, endpoint: str, primary_keys: list[str], partition_key: str | None
    ) -> None:
        result = _driver().run(endpoint, always(_page([])), api_version=api_version)

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_keys == ([partition_key] if partition_key else None)
        assert response.partition_mode == ("datetime" if partition_key else None)


class TestAnalyticsWindow:
    @parameterized.expand(
        [
            ("full_refresh_reads_the_longest_range", False, "2026-10-20T08:00:00Z", "2025-10-24T00:00:00Z"),
            ("incremental_rereads_the_watermark_day", True, "2026-10-20T00:00:00Z", "2026-10-20T00:00:00Z"),
            (
                "incremental_accepts_a_datetime_watermark",
                True,
                datetime(2026, 10, 20, 15, 30, tzinfo=UTC),
                "2026-10-20T00:00:00Z",
            ),
            ("old_watermark_is_clamped_to_the_api_limit", True, "2024-01-01T00:00:00Z", "2025-10-24T00:00:00Z"),
            ("no_watermark_reads_the_longest_range", True, None, "2025-10-24T00:00:00Z"),
        ]
    )
    def test_window(self, _name: str, incremental: bool, last_value: Any, expected_start: str) -> None:
        now = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)

        assert analytics_window(incremental, last_value, now) == {
            "starts_at": expected_start,
            "ends_at": "2026-10-23T12:00:00Z",
        }


class TestBreakdownDays:
    @parameterized.expand(
        [
            ("full_refresh_reads_the_backfill_window_except_today", False, "2026-10-20T00:00:00Z", 89, "2026-07-26"),
            ("incremental_rereads_the_watermark_day", True, "2026-10-20T09:00:00Z", 3, "2026-10-20"),
            ("watermark_today_reads_nothing", True, "2026-10-23T01:00:00Z", 0, None),
            ("old_watermark_is_clamped_to_the_backfill", True, "2024-01-01T00:00:00Z", 89, "2026-07-26"),
            ("no_watermark_reads_the_backfill", True, None, 89, "2026-07-26"),
        ]
    )
    def test_days(
        self, _name: str, incremental: bool, last_value: Any, expected_count: int, expected_first: str | None
    ) -> None:
        days = breakdown_days(incremental, last_value, datetime(2026, 10, 23, 12, 0, tzinfo=UTC))

        assert len(days) == expected_count
        if expected_first is not None:
            assert days[0] == date.fromisoformat(expected_first)
            assert days[-1] == date(2026, 10, 22)


class TestLovableResume:
    @parameterized.expand(
        [
            ("no_saved_state", None, 0, None),
            ("cursor_resumes_that_parent", LovableResumeConfig(workspace_id="ws-2", cursor="c9"), 1, "c9"),
            ("finished_parent_moves_on", LovableResumeConfig(workspace_id="ws-2"), 2, None),
            ("unknown_parent_restarts", LovableResumeConfig(workspace_id="gone", cursor="c9"), 0, None),
        ]
    )
    def test_resume_position(
        self, _name: str, resume: LovableResumeConfig | None, expected_index: int, expected_cursor: str | None
    ) -> None:
        parents = [_ParentRef(workspace_id="ws-1"), _ParentRef(workspace_id="ws-2"), _ParentRef(workspace_id="ws-3")]

        assert resume_position(parents, resume) == (expected_index, expected_cursor)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("v1", "https://api.lovable.dev/v1/me", {"Lovable-API-Key": "lov_key"}),
            (
                "2026-09-11",
                "https://api.lovable.dev/v1/workspaces?limit=1",
                {"Lovable-API-Key": "lov_key", "Lovable-Version": "2026-09-11"},
            ),
        ]
    )
    def test_probe_targets_an_endpoint_the_version_serves(
        self, api_version: str, expected_url: str, expected_headers: dict[str, str]
    ) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_credentials("lov_key", api_version) == (True, None)

        assert network.requests_log[0].url == expected_url
        assert network.requests_log[0].headers["lovable-api-key"] == expected_headers["Lovable-API-Key"]
        if "Lovable-Version" in expected_headers:
            assert network.requests_log[0].headers["lovable-version"] == expected_headers["Lovable-Version"]
        else:
            assert "lovable-version" not in network.requests_log[0].headers

    @parameterized.expand(
        [
            (
                "plan_too_low",
                402,
                False,
                "Lovable's API needs the Business plan or higher. Upgrade the workspace in Lovable and reconnect.",
            ),
        ]
    )
    def test_status_maps_to_message(
        self,
        _name: str,
        status_code: int,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        response = ScriptedResponse(status=status_code)
        script = always(response) if status_code == 500 else [response]
        with scripted_network(script):
            assert validate_credentials("lov_key", "2026-09-11") == (expected_valid, expected_message)


class TestCheckEndpointPermissions:
    @parameterized.expand(
        [
            ("plan_gated", _error(402), "This table needs Lovable's Enterprise plan or higher."),
            (
                "forbidden",
                _error(403, "forbidden"),
                "This Lovable API key does not have permission to read this table.",
            ),
            ("readable", _page([{"user_id": "u-1"}]), None),
            # An unexpected status is not a denial, so the table must not be disabled over it.
            ("unexpected_status", _error(404, "not_found"), None),
        ]
    )
    def test_probe_status_maps_to_a_reason(
        self, _name: str, probe_response: ScriptedResponse, expected_reason: str | None
    ) -> None:
        with scripted_network([_page([{"id": "ws-1"}]), probe_response]):
            assert check_endpoint_permissions("lov_key", "v1", ["WorkspaceMembers"]) == {
                "WorkspaceMembers": expected_reason
            }

    def test_account_with_no_workspaces_reports_no_reason(self) -> None:
        with scripted_network([_page([])]):
            assert check_endpoint_permissions("lov_key", "v1", ["WorkspaceMembers"]) == {"WorkspaceMembers": None}

    def test_table_the_version_dropped_reports_no_reason_without_a_probe(self) -> None:
        with scripted_network([_page([{"id": "ws-1"}])]) as network:
            assert check_endpoint_permissions("lov_key", "2026-09-11", ["WorkspaceCreditHistory"]) == {
                "WorkspaceCreditHistory": None
            }

        assert [request.url for request in network.requests_log] == ["https://api.lovable.dev/v1/workspaces?limit=1"]

    @parameterized.expand(
        [
            ("project", "v1", "ProjectSecurityScans", [], "/v1/projects/p-1/security-scans", False),
            ("time_series", "2026-09-11", "ProjectAnalytics", [], "/v1/projects/p-1/analytics", True),
            (
                "breakdowns",
                "2026-09-11",
                "ProjectAnalyticsBreakdowns",
                [],
                "/v1/projects/p-1/analytics/breakdowns",
                True,
            ),
            (
                "scan",
                "2026-09-11",
                "ProjectSecurityScanFindings",
                [_page([{"id": "s-1"}])],
                "/v1/projects/p-1/security-scans/s-1/findings",
                False,
            ),
        ]
    )
    def test_nested_table_probes_its_parent(
        self,
        _name: str,
        api_version: str,
        endpoint: str,
        scan_pages: list[ScriptedResponse],
        expected_path: str,
        expects_date_range: bool,
    ) -> None:
        with scripted_network(
            [_page([{"id": "ws-1"}]), _page([{"id": "p-1"}]), *scan_pages, _error(402)],
        ) as network:
            permissions = check_endpoint_permissions("lov_key", api_version, [endpoint])

        assert permissions == {endpoint: "This table needs Lovable's Business plan or higher."}
        probe = network.requests_log[-1]
        assert probe.path == expected_path
        # A date-range table rejects a request without `starts_at`, so a `limit` probe would hide a plan gate.
        assert (probe.param("starts_at") is not None, probe.param("limit") is None) == (
            expects_date_range,
            expects_date_range,
        )
