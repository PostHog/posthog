"""Activities that build a labeling benchmark version: snapshot the labels, then prepare and record each case."""

import json
import hashlib
from typing import IO, cast

import zstandard
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.models import Team
from posthog.storage import object_storage
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.session_replay.rasterize_recording.activities.rasterize import rasterization_input_from_context
from posthog.temporal.session_replay.rasterize_recording.types import FINGERPRINT_EXCLUDE, RasterizationActivityInput

from products.replay_vision.backend.benchmark.labeling_api import LabelingExportClient
from products.replay_vision.backend.benchmark.layout import BenchmarkCase, BenchmarkLayout
from products.replay_vision.backend.consent import is_ai_data_processing_approved
from products.replay_vision.backend.temporal.activities.ensure_session_asset import analysis_export_context
from products.replay_vision.backend.temporal.activities.fetch_session_events import fetch_session_payload
from products.replay_vision.backend.temporal.benchmark_types import (
    BENCHMARK_CASE_ALREADY_BUILT_ERROR_TYPE,
    BENCHMARK_CASE_SKIPPED_ERROR_TYPE,
    BENCHMARK_VERSION_ALREADY_BUILT_ERROR_TYPE,
    LoadBenchmarkCasesInputs,
    LoadBenchmarkCasesOutput,
    PrepareBenchmarkCaseInputs,
    PrepareBenchmarkCaseOutput,
    RecordBenchmarkCaseInputs,
    SnapshotBenchmarkInputs,
    SnapshotBenchmarkOutput,
    WriteBenchmarkManifestInputs,
)
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.errors import IneligibleSessionError
from products.replay_vision.backend.temporal.types import ScannerLlmInputs

# The rasterizer refuses a render without a positive team id; a source render reads no team data.
BENCHMARK_RENDER_TEAM_ID = 1


def _layout(version: str) -> BenchmarkLayout:
    layout = BenchmarkLayout(version)
    if not layout.bucket:
        raise ValueError("REPLAY_VISION_BENCHMARK_BUCKET is not set")
    return layout


def benchmark_render_input(case_id: str, layout: BenchmarkLayout) -> RasterizationActivityInput:
    """The render a production scan's analysis video gets, from the case's recording instead of recording-api."""
    return rasterization_input_from_context(
        analysis_export_context(case_id),
        team_id=BENCHMARK_RENDER_TEAM_ID,
        session_id=case_id,
        s3_bucket=layout.bucket,
        s3_key_prefix=layout.case_prefix(case_id),
        output_format="mp4",
    ).model_copy(update={"source_s3_uri": layout.events_uri(case_id)})


def _write_jsonl(key: str, bucket: str, lines: list[str]) -> None:
    object_storage.write(key, "\n".join(lines) + "\n", bucket=bucket)


def _read_cases(layout: BenchmarkLayout) -> list[str]:
    body = object_storage.read(layout.cases_key, bucket=layout.bucket, missing_ok=True) or ""
    return [line for line in body.splitlines() if line.strip()]


def _snapshot(inputs: SnapshotBenchmarkInputs) -> SnapshotBenchmarkOutput:
    layout = _layout(inputs.version)
    if object_storage.head_object(layout.manifest_key, bucket=layout.bucket):
        raise ApplicationError(
            f"benchmark version {inputs.version} is already built; versions are never rewritten",
            type=BENCHMARK_VERSION_ALREADY_BUILT_ERROR_TYPE,
            non_retryable=True,
        )
    # A build that stopped partway resumes on the snapshot it took, so its cases keep describing one moment.
    if existing := _read_cases(layout):
        return SnapshotBenchmarkOutput(case_count=len(existing))

    snapshot = LabelingExportClient.from_settings().snapshot()
    cases = snapshot.cases
    if inputs.recording_limit is not None:
        # Hash order rather than id order, so a small version is a sample, not the oldest recordings.
        cases = sorted(cases, key=lambda case: hashlib.sha256(case.case_id.encode()).hexdigest())
        cases = sorted(cases[: inputs.recording_limit], key=lambda case: case.case_id)
    kept = {case.case_id for case in cases}
    cells = [cell for cell in snapshot.cells if cell.recording_id in kept]

    object_storage.write(
        layout.questions_key,
        json.dumps([question.model_dump(mode="json") for question in snapshot.questions]),
        bucket=layout.bucket,
    )
    _write_jsonl(layout.labels_key, layout.bucket, [cell.model_dump_json() for cell in cells])
    # Written last, so a snapshot that stops partway leaves no cases for a resume to trust.
    _write_jsonl(layout.cases_key, layout.bucket, [case.model_dump_json() for case in cases])
    return SnapshotBenchmarkOutput(case_count=len(cases))


@activity.defn
@track_activity()
async def snapshot_benchmark_labels_activity(inputs: SnapshotBenchmarkInputs) -> SnapshotBenchmarkOutput:
    return await database_sync_to_async_pool(_snapshot)(inputs)


def _load_cases(inputs: LoadBenchmarkCasesInputs) -> LoadBenchmarkCasesOutput:
    window = _read_cases(_layout(inputs.version))[inputs.offset : inputs.offset + inputs.limit]
    return LoadBenchmarkCasesOutput(cases=[BenchmarkCase.model_validate_json(line) for line in window])


@activity.defn
@track_activity()
async def load_benchmark_cases_activity(inputs: LoadBenchmarkCasesInputs) -> LoadBenchmarkCasesOutput:
    return await database_sync_to_async_pool(_load_cases)(inputs)


def _skip(reason: str) -> ApplicationError:
    return ApplicationError(reason, type=BENCHMARK_CASE_SKIPPED_ERROR_TYPE, non_retryable=True)


def _production_inputs(case: BenchmarkCase) -> ScannerLlmInputs:
    """The inputs a production scan of this session gets, from the same fetch; a session it would not scan is skipped."""
    # The same gate a production scan passes before anything leaves for Gemini.
    if not is_ai_data_processing_approved(case.team_id):
        raise _skip("no AI data processing consent")
    try:
        payload = fetch_session_payload(case.team_id, case.session_id)
    except IneligibleSessionError as error:
        raise _skip(f"ineligible: {error.kind}") from error
    except Team.DoesNotExist as error:
        raise _skip("team no longer exists") from error
    if payload is None:
        raise _skip("no analytics events")
    return payload


def _already_built(layout: BenchmarkLayout, case: BenchmarkCase) -> bool:
    status = object_storage.read(layout.status_key(case.case_id), bucket=layout.bucket, missing_ok=True)
    return status is not None and json.loads(status).get("outcome") == "built"


def _prepare_case(layout: BenchmarkLayout, case: BenchmarkCase) -> PrepareBenchmarkCaseOutput:
    # A resumed build keeps what an earlier run of this version rendered instead of rendering it again.
    if _already_built(layout, case):
        raise ApplicationError("already built", type=BENCHMARK_CASE_ALREADY_BUILT_ERROR_TYPE, non_retryable=True)
    # Inputs first: a skipped session costs the labeling app nothing.
    inputs = _production_inputs(case)
    with LabelingExportClient.from_settings().playable(case.case_id) as playable:
        # The reader only calls read(), which GzipBody provides.
        with zstandard.ZstdCompressor().stream_reader(cast(IO[bytes], playable.stream)) as compressed:
            object_storage.write_stream(layout.events_key(case.case_id), compressed, bucket=layout.bucket)
    object_storage.write(layout.inputs_key(case.case_id), inputs.model_dump_json(), bucket=layout.bucket)
    return PrepareBenchmarkCaseOutput(
        render_input=benchmark_render_input(case.case_id, layout),
        image_refs=playable.image_refs,
        images_resolved=playable.images_resolved,
    )


@activity.defn
@track_activity()
async def prepare_benchmark_case_activity(inputs: PrepareBenchmarkCaseInputs) -> PrepareBenchmarkCaseOutput:
    return await database_sync_to_async_pool(_prepare_case)(_layout(inputs.version), inputs.case)


def _record_case(inputs: RecordBenchmarkCaseInputs) -> None:
    layout = _layout(inputs.version)
    object_storage.write(
        layout.status_key(inputs.case_id), inputs.model_dump_json(exclude={"version"}), bucket=layout.bucket
    )


@activity.defn
@track_activity()
async def record_benchmark_case_activity(inputs: RecordBenchmarkCaseInputs) -> None:
    await database_sync_to_async_pool(_record_case)(inputs)


def _write_manifest(inputs: WriteBenchmarkManifestInputs, built_at: str) -> None:
    layout = _layout(inputs.version)
    # The render every case got, without the parts that name one case.
    render_settings = benchmark_render_input("", layout).model_dump(
        exclude=FINGERPRINT_EXCLUDE, mode="json", exclude_none=True
    )
    manifest = {
        "version": inputs.version,
        "built_at": built_at,
        "case_count": inputs.case_count,
        "built": inputs.built,
        "failed": inputs.failed,
        "skipped": inputs.skipped,
        "render_settings": render_settings,
    }
    object_storage.write(layout.manifest_key, json.dumps(manifest), bucket=layout.bucket)


@activity.defn
@track_activity()
async def write_benchmark_manifest_activity(inputs: WriteBenchmarkManifestInputs) -> None:
    built_at = activity.info().current_attempt_scheduled_time.isoformat()
    await database_sync_to_async_pool(_write_manifest)(inputs, built_at)
