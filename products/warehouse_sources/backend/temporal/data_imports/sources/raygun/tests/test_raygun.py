from typing import Any

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
