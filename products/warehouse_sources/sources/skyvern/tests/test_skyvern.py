from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from products.warehouse_sources.sources.sdk.testing import (
    DriveResult,
    RecordedRequest,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
)
from products.warehouse_sources.sources.skyvern import skyvern
from products.warehouse_sources.sources.skyvern._config import SkyvernSourceConfig
from products.warehouse_sources.sources.skyvern.skyvern import SkyvernResumeConfig
from products.warehouse_sources.sources.skyvern.source import SkyvernSource


def _run(endpoint: str, script: Script, **kwargs: Any) -> DriveResult:
    return SourceDriver(SkyvernSource(), SkyvernSourceConfig(api_key="key")).run(endpoint, script, **kwargs)


def _page_one_only(rows: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json=rows)


class TestSimplePagination:
    def test_resumes_from_saved_page(self) -> None:
        def handler(request: RecordedRequest) -> ScriptedResponse:
            return _page_one_only([{"id": "x"}] if request.param("page") == "5" else [])

        result = _run("browser_profiles", handler, resume_state=SkyvernResumeConfig(page=5))

        assert result.requests[0].param("page") == "5"


class TestFanOutRuns:
    def test_clamps_future_watermark_to_now(self) -> None:
        # A future-dated watermark would filter out every existing run; clamping keeps the sync valid.
        def handler(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/v1/agents":
                return _page_one_only([{"workflow_permanent_id": "wpid_1"}] if request.param("page") == "1" else [])
            return _page_one_only([{"workflow_run_id": "wr_1"}] if request.param("page") == "1" else [])

        result = _run(
            "runs",
            handler,
            incremental_field="created_at",
            db_incremental_field_last_value=datetime(2999, 1, 1, tzinfo=UTC),
        )

        run_requests = [request for request in result.requests if request.path.endswith("/runs")]
        sent = run_requests[0].param("created_at_start")
        assert sent is not None
        parsed = datetime.fromisoformat(sent.replace("Z", "+00:00"))
        assert parsed <= datetime.now(UTC) + timedelta(seconds=1)

    def test_resumes_skipping_completed_workflow(self) -> None:
        # A saved fan-out checkpoint must skip already-completed workflows, not restart from the first.
        def handler(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/v1/agents":
                return _page_one_only(
                    [{"workflow_permanent_id": "wpid_1"}, {"workflow_permanent_id": "wpid_2"}]
                    if request.param("page") == "1"
                    else []
                )
            return _page_one_only([{"workflow_run_id": "wr_1"}] if request.param("page") == "1" else [])

        result = _run(
            "runs",
            handler,
            resume_state=SkyvernResumeConfig(
                fanout_state={"completed": ["/v1/agents/wpid_1/runs"], "current": None, "child_state": None}
            ),
        )

        run_paths = [path for path in result.paths if path.endswith("/runs")]
        assert run_paths
        assert all("wpid_2" in path for path in run_paths)
        assert not any("wpid_1" in path for path in run_paths)

    def test_legacy_resume_state_still_deserializes(self) -> None:
        # State persisted by the pre-migration fan-out carried page + workflow_permanent_id; it must
        # still parse (ResumableSourceManager does dataclass(**saved)) after adding fanout_state.
        restored = SkyvernResumeConfig(**cast("dict[str, Any]", {"page": 3, "workflow_permanent_id": "wpid_9"}))
        assert restored.page == 3
        assert restored.fanout_state is None


def _workflows_then(child: Any) -> Any:
    def handler(request: RecordedRequest) -> ScriptedResponse:
        if request.path == "/v1/agents":
            return _page_one_only(
                [{"workflow_permanent_id": "wpid_1"}, {"workflow_permanent_id": "wpid_2"}]
                if request.param("page") == "1"
                else []
            )
        return child(request)

    return handler


class TestFanOutPerWorkflow:
    @pytest.mark.parametrize(
        "endpoint,suffix,child_body,expected_rows",
        [
            (
                "workflow_tags",
                "/tags",
                lambda wpid: {
                    "workflow_permanent_id": wpid,
                    "tags": [{"key": "env", "value": "prod"}, {"key": None, "value": "nightly"}],
                },
                [
                    {"workflow_permanent_id": "wpid_1", "key": "env", "value": "prod"},
                    {"workflow_permanent_id": "wpid_1", "key": None, "value": "nightly"},
                    {"workflow_permanent_id": "wpid_2", "key": "env", "value": "prod"},
                    {"workflow_permanent_id": "wpid_2", "key": None, "value": "nightly"},
                ],
            ),
            (
                "workflow_versions",
                "/versions",
                lambda wpid: [
                    {"workflow_id": f"{wpid}_v1", "workflow_permanent_id": wpid, "version": 1},
                    {"workflow_id": f"{wpid}_v2", "workflow_permanent_id": wpid, "version": 2},
                ],
                [
                    {"workflow_id": "wpid_1_v1", "workflow_permanent_id": "wpid_1", "version": 1},
                    {"workflow_id": "wpid_1_v2", "workflow_permanent_id": "wpid_1", "version": 2},
                    {"workflow_id": "wpid_2_v1", "workflow_permanent_id": "wpid_2", "version": 1},
                    {"workflow_id": "wpid_2_v2", "workflow_permanent_id": "wpid_2", "version": 2},
                ],
            ),
        ],
    )
    def test_reads_each_workflow_once(self, endpoint, suffix, child_body, expected_rows) -> None:
        # These children take no page params, so a second request per workflow would re-read the same rows.
        def child(request: RecordedRequest) -> ScriptedResponse:
            return ScriptedResponse(json=child_body(request.path.split("/")[3]))

        result = _run(endpoint, _workflows_then(child))

        assert result.raised is None
        assert [path for path in result.paths if path.endswith(suffix)] == [
            f"/v1/agents/wpid_1{suffix}",
            f"/v1/agents/wpid_2{suffix}",
        ]
        assert result.rows == expected_rows

    def test_resumes_skipping_completed_workflow(self) -> None:
        result = _run(
            "workflow_versions",
            _workflows_then(lambda request: ScriptedResponse(json=[])),
            resume_state=SkyvernResumeConfig(
                fanout_state={"completed": ["/v1/agents/wpid_1/versions"], "current": None, "child_state": None}
            ),
        )

        assert [path for path in result.paths if path.endswith("/versions")] == ["/v1/agents/wpid_2/versions"]


class TestRunTimeline:
    @staticmethod
    def _handler(runs: list[dict[str, Any]], timelines: dict[str, Any]) -> Any:
        def child(request: RecordedRequest) -> ScriptedResponse:
            if request.path.endswith("/runs"):
                return _page_one_only(runs if request.param("page") == "1" and "wpid_1" in request.path else [])
            run_id = request.path.split("/")[3]
            if run_id not in timelines:
                return ScriptedResponse(status=404, json={"detail": "not found"})
            return ScriptedResponse(json=timelines[run_id])

        return _workflows_then(child)

    def test_flattens_nested_entries_and_skips_purged_runs(self) -> None:
        timeline = [
            {
                "type": "block",
                "block": {"workflow_run_block_id": "wrb_loop"},
                "thought": None,
                "created_at": "2026-01-01T00:00:00Z",
                "children": [
                    {
                        "type": "block",
                        "block": {"workflow_run_block_id": "wrb_inner"},
                        "created_at": "2026-01-01T00:00:01Z",
                        "children": [
                            {
                                "type": "thought",
                                "thought": {"thought_id": "th_1"},
                                "created_at": "2026-01-01T00:00:02Z",
                                "children": [],
                            }
                        ],
                    }
                ],
            },
            {"type": "thought", "thought": {"thought_id": "th_2"}, "created_at": "2026-01-01T00:00:03Z"},
        ]

        result = _run(
            "run_timeline",
            self._handler([{"workflow_run_id": "wr_1"}, {"workflow_run_id": "wr_gone"}], {"wr_1": timeline}),
        )

        assert result.raised is None
        assert [
            (row["workflow_run_id"], row["timeline_entry_id"], row["parent_timeline_entry_id"]) for row in result.rows
        ] == [
            ("wr_1", "wrb_loop", None),
            ("wr_1", "wrb_inner", "wrb_loop"),
            ("wr_1", "th_1", "wrb_inner"),
            ("wr_1", "th_2", None),
        ]
        assert all("children" not in row and "_runs_workflow_run_id" not in row for row in result.rows)

    @pytest.mark.parametrize(
        "incremental_value,expected_created_at_start",
        [
            (None, None),
            (datetime(2026, 1, 10, tzinfo=UTC), "2026-01-07T00:00:00.000Z"),
        ],
    )
    def test_incremental_windows_the_runs_listing(self, incremental_value, expected_created_at_start) -> None:
        inputs: dict[str, Any] = (
            {"incremental_field": "created_at", "db_incremental_field_last_value": incremental_value}
            if incremental_value
            else {}
        )

        result = _run("run_timeline", self._handler([{"workflow_run_id": "wr_1"}], {"wr_1": []}), **inputs)

        assert result.raised is None
        run_requests = [request for request in result.requests if request.path.endswith("/runs")]
        assert run_requests
        assert {request.param("created_at_start") for request in run_requests} == {expected_created_at_start}
        assert [path for path in result.paths if path.endswith("/timeline")] == ["/v1/runs/wr_1/timeline"]


class TestSourceResponse:
    @pytest.mark.parametrize(
        "endpoint,expected_primary_keys,expected_partition,expected_sort_mode",
        [
            ("workflows", ["workflow_permanent_id"], "created_at", "desc"),
            ("runs", ["workflow_run_id"], "created_at", "desc"),
            ("schedules", ["workflow_schedule_id"], "created_at", "desc"),
            ("browser_profiles", ["browser_profile_id"], "created_at", "desc"),
            ("credentials", ["credential_id"], None, "desc"),
            ("folders", ["folder_id"], "created_at", "desc"),
            ("workflow_tags", ["workflow_permanent_id", "key", "value"], None, "desc"),
            ("workflow_versions", ["workflow_id"], "created_at", "desc"),
            # Timeline rows of many runs arrive in no global order, so no sort mode is promised.
            ("run_timeline", ["workflow_run_id", "timeline_entry_id"], "created_at", None),
        ],
    )
    def test_response_shape(self, endpoint, expected_primary_keys, expected_partition, expected_sort_mode) -> None:
        response = _run(endpoint, always(ScriptedResponse(json=[]))).response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_primary_keys
        # Skyvern lists return newest-first, so the pipeline must checkpoint in desc mode.
        assert response.sort_mode == expected_sort_mode
        if expected_partition is None:
            assert response.partition_keys is None
            assert response.partition_mode is None
        else:
            assert response.partition_keys == [expected_partition]
            assert response.partition_mode == "datetime"


def test_skyvern_module_exposes_page_constants() -> None:
    # The per-workflow page cap only guards incremental runs; a full refresh must page unbounded.
    assert skyvern.PAGE_SIZE == 100
    assert skyvern.MAX_PAGES_PER_WORKFLOW == 100
