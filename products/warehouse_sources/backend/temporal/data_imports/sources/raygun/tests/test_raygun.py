from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.raygun import RaygunSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.raygun.raygun import RaygunResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.raygun.source import RaygunSource

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.raygun.raygun"


def _run(endpoint: str, script: Script, **inputs: Any) -> DriveResult:
    return SourceDriver(RaygunSource(), RaygunSourceConfig(personal_access_token="tok")).run(endpoint, script, **inputs)


class TestTopLevelPagination:
    @patch(f"{MODULE}.PAGE_SIZE", 2)
    def test_offset_advances_and_saves_between_pages(self) -> None:
        # Two full pages then a short terminal page for /applications.
        pages = {
            "0": [{"identifier": "app-1"}, {"identifier": "app-2"}],
            "2": [{"identifier": "app-3"}, {"identifier": "app-4"}],
            "4": [{"identifier": "app-5"}],
        }

        result = _run("applications", lambda request: ScriptedResponse(json=pages[request.param("offset") or "0"]))

        assert result.params("offset") == ["0", "2", "4"]
        assert len(result.rows) == 5
        # Sync sessions carry PII-bearing bodies, so sample capture must stay off.
        assert result.session_options
        assert all(option["capture"] is False for option in result.session_options)
        assert all("tok" in option["redact_values"] for option in result.session_options)
        # State is saved pointing at the next unfetched offset after each non-terminal page only.
        assert result.saved_states == [RaygunResumeConfig(offset=2), RaygunResumeConfig(offset=4)]

    @patch(f"{MODULE}.PAGE_SIZE", 2)
    def test_resume_starts_from_saved_offset(self) -> None:
        result = _run(
            "applications",
            [ScriptedResponse(json=[{"identifier": "app-9"}])],
            resume_state=RaygunResumeConfig(offset=4),
        )

        assert result.params("offset") == ["4"]

    @patch(f"{MODULE}.PAGE_SIZE", 2)
    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = _run("applications", [ScriptedResponse(json=[{"identifier": "app-9"}])])

        assert result.params("offset") == ["0"]


class TestFanOutPagination:
    def _fan_out_script(self, apps: list[str], child_rows: dict[str, list[dict[str, Any]]]) -> Script:
        def script(request: Any) -> ScriptedResponse:
            offset = request.param("offset") or "0"
            if request.path.endswith("/applications"):
                # One full page of apps then a terminal empty page.
                return ScriptedResponse(json=[{"identifier": a} for a in apps] if offset == "0" else [])
            for app in apps:
                if f"/applications/{app}/" in request.path:
                    return ScriptedResponse(json=child_rows.get(app, []) if offset == "0" else [])
            return ScriptedResponse(json=[])

        return script

    @patch(f"{MODULE}.PAGE_SIZE", 2)
    def test_resume_skips_completed_app_and_starts_bookmarked_app_at_offset(self) -> None:
        apps = ["app-1", "app-2"]
        child_rows = {"app-2": [{"identifier": "eg-2", "applicationIdentifier": "app-2"}]}

        result = _run(
            "error_groups",
            self._fan_out_script(apps, child_rows),
            resume_state=RaygunResumeConfig(
                fanout_state={
                    "completed": ["/applications/app-1/error-groups"],
                    "current": "/applications/app-2/error-groups",
                    "child_state": {"offset": 6},
                }
            ),
        )

        child_requests = [
            r for r in result.requests if "/applications/app-1/" in r.path or "/applications/app-2/" in r.path
        ]
        # app-1 is skipped entirely; the first child fetch targets app-2 at the saved offset.
        assert all("/applications/app-2/" in r.path for r in child_requests)
        assert child_requests[0].param("offset") == "6"


class TestNestedFanOut:
    @patch(f"{MODULE}.PAGE_SIZE", 2)
    def test_incremental_skips_quiet_groups_and_stops_paging_at_the_watermark(self) -> None:
        groups = [
            {"identifier": "eg-old", "lastOccurredAt": "2026-01-01T00:00:00Z"},
            {"identifier": "eg-new", "lastOccurredAt": "2026-03-01T00:00:00Z"},
        ]
        instances = {
            "0": [
                {"identifier": "i-3", "occurredOn": "2026-03-01T00:00:00Z"},
                {"identifier": "i-2", "occurredOn": "2026-02-20T00:00:00Z"},
            ],
            "2": [
                {"identifier": "i-1", "occurredOn": "2026-02-10T00:00:00Z"},
                {"identifier": "i-0", "occurredOn": "2026-01-10T00:00:00Z"},
            ],
        }

        def script(request: Any) -> ScriptedResponse:
            offset = request.param("offset") or "0"
            if request.path.endswith("/applications"):
                return ScriptedResponse(json=[{"identifier": "app-1"}] if offset == "0" else [])
            if request.path.endswith("/error-groups"):
                return ScriptedResponse(json=groups if offset == "0" else [])
            assert "/error-groups/eg-new/instances" in request.path
            return ScriptedResponse(json=instances.get(offset, []))

        result = _run(
            "error_instances",
            script,
            incremental_field="occurredOn",
            db_incremental_field_last_value=datetime(2026, 2, 1, tzinfo=UTC),
        )

        instance_requests = [r for r in result.requests if r.path.endswith("/instances")]
        # The group last seen before the watermark is never read, and paging stops on the page that
        # reaches below the watermark instead of reading the group's whole history.
        assert [r.param("offset") for r in instance_requests] == ["0", "2"]
        assert all(r.param("orderby") == "occurredOn desc" for r in instance_requests)
        assert [row["identifier"] for row in result.rows] == ["i-3", "i-2", "i-1", "i-0"]
        assert {(row["applicationIdentifier"], row["errorGroupIdentifier"]) for row in result.rows} == {
            ("app-1", "eg-new")
        }

    @patch(f"{MODULE}.PAGE_SIZE", 2)
    def test_resume_continues_at_the_saved_state_filter_and_child_offset(self) -> None:
        def script(request: Any) -> ScriptedResponse:
            offset = request.param("offset") or "0"
            if request.path.endswith("/applications"):
                return ScriptedResponse(
                    json=[{"identifier": "app-1"}, {"identifier": "app-2"}] if offset == "0" else []
                )
            if request.path.endswith("/deployments"):
                return ScriptedResponse(json=[{"identifier": "d-1"}] if offset == "0" else [])
            return ScriptedResponse(json=[{"identifier": f"eg-{offset}", "applicationIdentifier": "app-2"}])

        result = _run(
            "deployment_error_groups",
            script,
            resume_state=RaygunResumeConfig(
                nested_application_identifier="app-2", nested_state_index=1, nested_child_offset=4
            ),
        )

        child_requests = [r for r in result.requests if r.path.endswith("/error-groups")]
        # app-1 and the `new` filter of app-2 were done before the interruption.
        assert [(r.path, r.param("filter"), r.param("offset")) for r in child_requests] == [
            ("/v3/applications/app-2/deployments/d-1/error-groups", "state eq regressed", "4")
        ]
        assert result.rows == [
            {
                "identifier": "eg-4",
                "applicationIdentifier": "app-2",
                "deploymentIdentifier": "d-1",
                "deploymentState": "regressed",
            }
        ]
        assert result.final_state == RaygunResumeConfig(nested_application_identifier="app-2", nested_parent_index=1)


class TestMetrics:
    @pytest.mark.parametrize("incremental", [True, False])
    def test_request_window_and_row_shape(self, incremental: bool) -> None:
        def script(request: Any) -> ScriptedResponse:
            if request.path.endswith("/applications"):
                return ScriptedResponse(json=[{"identifier": "app-1"}] if request.param("offset") == "0" else [])
            return ScriptedResponse(
                json=[
                    {
                        "aggregation": "count",
                        "metric": "errorInstances",
                        "series": [{"time": "2026-10-31T10:00:00Z", "value": 3}],
                    }
                ]
            )

        watermark = datetime.now(UTC) - timedelta(days=2, minutes=17)
        inputs: dict[str, Any] = (
            {"incremental_field": "time", "db_incremental_field_last_value": watermark} if incremental else {}
        )
        result = _run("error_metrics", script, **inputs)

        bodies = [r.json() for r in result.requests if r.method == "POST"]
        assert len(bodies) == 1
        start = datetime.fromisoformat(bodies[0]["start"])
        end = datetime.fromisoformat(bodies[0]["end"])
        expected_start = watermark if incremental else end - timedelta(days=30)
        assert start == expected_start.replace(minute=0, second=0, microsecond=0)
        assert (end.minute, end.second) == (0, 0)
        assert bodies[0]["granularity"] == "1h"
        assert bodies[0]["metrics"] == ["errorInstances"]
        assert result.rows == [
            {
                "applicationIdentifier": "app-1",
                "metric": "errorInstances",
                "aggregation": "count",
                "time": "2026-10-31T10:00:00Z",
                "value": 3,
            }
        ]


class TestRaygunSource:
    def test_primary_keys_and_partitioning_per_endpoint(self) -> None:
        def response_of(endpoint: str) -> Any:
            response = _run(endpoint, always(ScriptedResponse(json=[]))).response
            assert response is not None
            return response

        applications = response_of("applications")
        assert applications.primary_keys == ["identifier"]
        assert applications.partition_mode is None

        error_groups = response_of("error_groups")
        assert error_groups.primary_keys == ["applicationIdentifier", "identifier"]
        assert error_groups.partition_mode == "datetime"
        assert error_groups.partition_keys == ["createdAt"]

        sessions = response_of("sessions")
        assert sessions.partition_keys == ["startedAt"]

        # A fan-out endpoint without a guaranteed create-time field is left unpartitioned.
        deployments = response_of("deployments")
        assert deployments.primary_keys == ["applicationIdentifier", "identifier"]
        assert deployments.partition_mode is None
