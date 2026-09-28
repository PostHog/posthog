"""Build one labeling benchmark version: snapshot the labels, then prepare and render every labeled recording.

Each case renders on the shared rasterizer at the lowest priority, so customer scans go first. A session
production would not scan is skipped and a case that fails is recorded; the version is built from the rest. The workflow continues as
new after each batch, so history stays bounded however many cases a version holds.
"""

import asyncio
import datetime as dt
from collections import Counter
from typing import Any, Literal

from temporalio import (
    common,
    workflow as wf,
)
from temporalio.common import Priority
from temporalio.exceptions import ActivityError, ApplicationError

from posthog.temporal.common.base import PostHogWorkflow

with wf.unsafe.imports_passed_through():
    from django.conf import settings

    from posthog.temporal.session_replay.rasterize_recording.types import (
        RASTERIZE_RENDER_MAX_ATTEMPTS,
        RASTERIZE_RENDER_TIMEOUT,
        RasterizationActivityInput,
    )

    from products.replay_vision.backend.benchmark.layout import BenchmarkCase
    from products.replay_vision.backend.temporal.activities.benchmark import (
        load_benchmark_cases_activity,
        prepare_benchmark_case_activity,
        record_benchmark_case_activity,
        snapshot_benchmark_labels_activity,
        write_benchmark_manifest_activity,
    )
    from products.replay_vision.backend.temporal.activities.ensure_session_asset import analysis_export_context
    from products.replay_vision.backend.temporal.benchmark_types import (
        BENCHMARK_CASE_SKIPPED_ERROR_TYPE,
        BuildBenchmarkInputs,
        LoadBenchmarkCasesInputs,
        LoadBenchmarkCasesOutput,
        PrepareBenchmarkCaseInputs,
        PrepareBenchmarkCaseOutput,
        RecordBenchmarkCaseInputs,
        SnapshotBenchmarkInputs,
        SnapshotBenchmarkOutput,
        WriteBenchmarkManifestInputs,
    )
    from products.replay_vision.backend.temporal.constants import BUILD_BENCHMARK_WORKFLOW_NAME

# Cases per run before continue-as-new. Each case adds about a dozen history events.
CASES_PER_RUN = 200
# Temporal's lowest priority, so benchmark renders queue behind every customer render.
BENCHMARK_RENDER_PRIORITY = Priority(priority_key=5)
# The rasterizer refuses a render without a positive team id; a source render reads no team data.
BENCHMARK_RENDER_TEAM_ID = 1

_RETRY = common.RetryPolicy(maximum_attempts=3)

CaseOutcome = Literal["built", "failed", "skipped"]


def _render_input(case_id: str, prepared: PrepareBenchmarkCaseOutput) -> dict[str, Any]:
    """A render with the same settings a production scan's analysis video uses."""
    render_settings = {
        key: value for key, value in analysis_export_context(case_id).items() if key != "session_recording_id"
    }
    return RasterizationActivityInput.model_validate(
        {
            **render_settings,
            "session_id": case_id,
            "team_id": BENCHMARK_RENDER_TEAM_ID,
            "source_s3_uri": prepared.source_s3_uri,
            "s3_bucket": prepared.output_bucket,
            "s3_key_prefix": prepared.output_prefix,
        }
    ).model_dump(exclude_none=True)


@wf.defn(name=BUILD_BENCHMARK_WORKFLOW_NAME)
class BuildBenchmarkWorkflow(PostHogWorkflow):
    inputs_cls = BuildBenchmarkInputs

    @wf.run
    async def run(self, inputs: BuildBenchmarkInputs) -> None:
        if inputs.case_count is None:
            snapshot: SnapshotBenchmarkOutput = await wf.execute_activity(
                snapshot_benchmark_labels_activity,
                SnapshotBenchmarkInputs(version=inputs.version, recording_limit=inputs.recording_limit),
                start_to_close_timeout=dt.timedelta(minutes=30),
                retry_policy=_RETRY,
            )
            inputs = inputs.model_copy(update={"case_count": snapshot.case_count})
        assert inputs.case_count is not None

        batch: LoadBenchmarkCasesOutput = await wf.execute_activity(
            load_benchmark_cases_activity,
            LoadBenchmarkCasesInputs(version=inputs.version, offset=inputs.offset, limit=CASES_PER_RUN),
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=_RETRY,
        )
        slots = asyncio.Semaphore(inputs.max_concurrent_renders)
        outcomes = Counter(
            await asyncio.gather(*(self._build_case(inputs.version, case, slots) for case in batch.cases))
        )
        built = inputs.built + outcomes["built"]
        failed = inputs.failed + outcomes["failed"]
        skipped = inputs.skipped + outcomes["skipped"]

        next_offset = inputs.offset + len(batch.cases)
        if batch.cases and next_offset < inputs.case_count:
            wf.continue_as_new(
                inputs.model_copy(update={"offset": next_offset, "built": built, "failed": failed, "skipped": skipped})
            )

        await wf.execute_activity(
            write_benchmark_manifest_activity,
            WriteBenchmarkManifestInputs(
                version=inputs.version, case_count=inputs.case_count, built=built, failed=failed, skipped=skipped
            ),
            start_to_close_timeout=dt.timedelta(minutes=2),
            retry_policy=_RETRY,
        )

    async def _build_case(self, version: str, case: BenchmarkCase, slots: asyncio.Semaphore) -> CaseOutcome:
        async with slots:
            record = RecordBenchmarkCaseInputs(version=version, case_id=case.case_id)
            try:
                prepared: PrepareBenchmarkCaseOutput = await wf.execute_activity(
                    prepare_benchmark_case_activity,
                    PrepareBenchmarkCaseInputs(version=version, case=case),
                    start_to_close_timeout=dt.timedelta(minutes=10),
                    retry_policy=_RETRY,
                )
                record = record.model_copy(
                    update={"image_refs": prepared.image_refs, "images_resolved": prepared.images_resolved}
                )
                render: dict[str, Any] = await wf.execute_activity(
                    "rasterize-recording",
                    _render_input(case.case_id, prepared),
                    # Not replay-checked, like the rasterize workflow's own task queue setting.
                    task_queue=settings.RASTERIZATION_TASK_QUEUE,
                    start_to_close_timeout=RASTERIZE_RENDER_TIMEOUT,
                    heartbeat_timeout=dt.timedelta(seconds=30),
                    retry_policy=common.RetryPolicy(maximum_attempts=RASTERIZE_RENDER_MAX_ATTEMPTS),
                    priority=BENCHMARK_RENDER_PRIORITY,
                )
                record = record.model_copy(update={"render": render})
            except ActivityError as error:
                cause = error.cause
                if isinstance(cause, ApplicationError) and cause.type == BENCHMARK_CASE_SKIPPED_ERROR_TYPE:
                    record = record.model_copy(update={"skipped": cause.message})
                else:
                    record = record.model_copy(update={"error": str(cause or error)})
            await wf.execute_activity(
                record_benchmark_case_activity,
                record,
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=_RETRY,
            )
            if record.render is not None:
                return "built"
            return "skipped" if record.skipped else "failed"
