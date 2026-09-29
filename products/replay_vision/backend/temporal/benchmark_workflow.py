"""Build one labeling benchmark version: snapshot the labels, then prepare and render every labeled recording.

Each case renders through the rasterize workflow, the same path production renders take, at the lowest priority
so customer scans go first. A session production would not scan is skipped and a case that fails is recorded;
the version is built from the rest. The workflow continues as new after each batch, so history stays bounded
however many cases a version holds.
"""

import asyncio
import datetime as dt
from collections import Counter

from temporalio import (
    common,
    workflow as wf,
)
from temporalio.common import Priority, WorkflowIDReusePolicy
from temporalio.exceptions import ApplicationError

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.errors import unwrap_temporal_cause

with wf.unsafe.imports_passed_through():
    from django.conf import settings

    from posthog.temporal.session_replay.rasterize_recording.types import (
        RasterizationActivityOutput,
        RasterizeRecordingInputs,
    )

    from products.replay_vision.backend.benchmark.layout import BenchmarkCase
    from products.replay_vision.backend.temporal.activities.benchmark import (
        load_benchmark_cases_activity,
        prepare_benchmark_case_activity,
        record_benchmark_case_activity,
        snapshot_benchmark_labels_activity,
        write_benchmark_manifest_activity,
    )
    from products.replay_vision.backend.temporal.benchmark_types import (
        BENCHMARK_CASE_ALREADY_BUILT_ERROR_TYPE,
        BENCHMARK_CASE_SKIPPED_ERROR_TYPE,
        BuildBenchmarkInputs,
        CaseOutcome,
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
# Temporal's lowest priority, so benchmark renders queue behind every customer render. The child's
# render activity inherits it.
BENCHMARK_RENDER_PRIORITY = Priority(priority_key=5)
# Rasterizer codes for a recording production gates as ineligible rather than failed: nothing to draw, or
# too large to render. The benchmark skips those the same way.
_INELIGIBLE_RENDER_TYPES = frozenset({"NO_SNAPSHOTS", "RECORDING_TOO_LARGE"})
# A render at the lowest priority waits behind any production backlog, and that wait counts against the child's
# execution timeout, so it gets hours rather than the single render attempt production callers budget for.
BENCHMARK_RENDER_TIMEOUT = dt.timedelta(hours=6)

_RETRY = common.RetryPolicy(maximum_attempts=3)


def _skip_reason(error: BaseException) -> str | None:
    cause = error if isinstance(error, ApplicationError) else unwrap_temporal_cause(error)
    if cause is None:
        return None
    if cause.type == BENCHMARK_CASE_SKIPPED_ERROR_TYPE:
        return cause.message
    if cause.type in _INELIGIBLE_RENDER_TYPES:
        return f"render: {cause.type}"
    return None


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
            outcome: CaseOutcome = "built"
            render: RasterizationActivityOutput | None = None
            reason: str | None = None
            image_refs = images_resolved = 0
            try:
                prepared: PrepareBenchmarkCaseOutput = await wf.execute_activity(
                    prepare_benchmark_case_activity,
                    PrepareBenchmarkCaseInputs(version=version, case=case),
                    start_to_close_timeout=dt.timedelta(minutes=10),
                    retry_policy=_RETRY,
                )
                image_refs, images_resolved = prepared.image_refs, prepared.images_resolved
                render = await wf.execute_child_workflow(
                    "rasterize-recording",
                    RasterizeRecordingInputs(render_input=prepared.render_input, product="replay_vision_benchmark"),
                    result_type=RasterizationActivityOutput,
                    id=f"{BUILD_BENCHMARK_WORKFLOW_NAME}-{version}-{case.case_id}",
                    # Not replay-checked, like the rasterize workflow's own task queue setting.
                    task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
                    retry_policy=common.RetryPolicy(maximum_attempts=1),
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                    execution_timeout=BENCHMARK_RENDER_TIMEOUT,
                    priority=BENCHMARK_RENDER_PRIORITY,
                )
            except Exception as error:
                cause = unwrap_temporal_cause(error)
                if cause is not None and cause.type == BENCHMARK_CASE_ALREADY_BUILT_ERROR_TYPE:
                    return "built"
                reason = _skip_reason(error)
                outcome = "skipped" if reason else "failed"
                reason = reason or str(cause or error)
            try:
                await wf.execute_activity(
                    record_benchmark_case_activity,
                    RecordBenchmarkCaseInputs(
                        version=version,
                        case_id=case.case_id,
                        outcome=outcome,
                        render=render,
                        reason=reason,
                        image_refs=image_refs,
                        images_resolved=images_resolved,
                    ),
                    start_to_close_timeout=dt.timedelta(minutes=2),
                    retry_policy=_RETRY,
                )
            except Exception:
                # One case whose status could not be written must not fail the batch and the renders beside it.
                return "failed"
            return outcome
