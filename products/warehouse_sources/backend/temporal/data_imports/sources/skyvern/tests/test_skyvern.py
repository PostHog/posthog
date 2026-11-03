from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.skyvern import (
    SkyvernSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.skyvern import skyvern
from products.warehouse_sources.backend.temporal.data_imports.sources.skyvern.skyvern import SkyvernResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.skyvern.source import SkyvernSource


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


class TestSourceResponse:
    @pytest.mark.parametrize(
        "endpoint,expected_primary_keys,expected_partition",
        [
            ("workflows", ["workflow_permanent_id"], "created_at"),
            ("runs", ["workflow_run_id"], "created_at"),
            ("schedules", ["workflow_schedule_id"], "created_at"),
            ("browser_profiles", ["browser_profile_id"], "created_at"),
            ("credentials", ["credential_id"], None),
        ],
    )
    def test_response_shape(self, endpoint, expected_primary_keys, expected_partition) -> None:
        response = _run(endpoint, always(ScriptedResponse(json=[]))).response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_primary_keys
        # Skyvern lists return newest-first, so the pipeline must checkpoint in desc mode.
        assert response.sort_mode == "desc"
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
