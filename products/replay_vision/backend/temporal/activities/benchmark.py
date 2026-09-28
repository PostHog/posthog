"""Activities that build a labeling benchmark version: snapshot the labels, then prepare and record each case."""

import json
import asyncio
import hashlib

import zstandard
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.models import Team
from posthog.storage import object_storage
from posthog.sync import database_sync_to_async

from products.replay_vision.backend.benchmark.labeling_api import LabelingExportClient
from products.replay_vision.backend.benchmark.layout import BenchmarkCase, BenchmarkLayout
from products.replay_vision.backend.temporal.activities.ensure_session_asset import analysis_export_context
from products.replay_vision.backend.temporal.activities.fetch_session_events import fetch_session_payload
from products.replay_vision.backend.temporal.benchmark_types import (
    BENCHMARK_CASE_SKIPPED_ERROR_TYPE,
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


def _layout(version: str) -> BenchmarkLayout:
    layout = BenchmarkLayout(version)
    if not layout.bucket:
        raise ValueError("REPLAY_VISION_BENCHMARK_BUCKET is not set")
    return layout


def _write_jsonl(key: str, bucket: str, lines: list[str]) -> None:
    object_storage.write(key, "\n".join(lines) + "\n", bucket=bucket)


def _snapshot(inputs: SnapshotBenchmarkInputs) -> SnapshotBenchmarkOutput:
    layout = _layout(inputs.version)
    if object_storage.head_object(layout.manifest_key, bucket=layout.bucket):
        raise ValueError(f"benchmark version {inputs.version} is already built; versions are never rewritten")
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
    _write_jsonl(layout.cases_key, layout.bucket, [case.model_dump_json() for case in cases])
    return SnapshotBenchmarkOutput(case_count=len(cases), cell_count=len(cells))


@activity.defn
@track_activity()
async def snapshot_benchmark_labels_activity(inputs: SnapshotBenchmarkInputs) -> SnapshotBenchmarkOutput:
    return await asyncio.to_thread(_snapshot, inputs)


def _load_cases(inputs: LoadBenchmarkCasesInputs) -> LoadBenchmarkCasesOutput:
    layout = _layout(inputs.version)
    body = object_storage.read(layout.cases_key, bucket=layout.bucket) or ""
    lines = [line for line in body.splitlines() if line.strip()]
    window = lines[inputs.offset : inputs.offset + inputs.limit]
    return LoadBenchmarkCasesOutput(cases=[BenchmarkCase.model_validate_json(line) for line in window])


@activity.defn
@track_activity()
async def load_benchmark_cases_activity(inputs: LoadBenchmarkCasesInputs) -> LoadBenchmarkCasesOutput:
    return await asyncio.to_thread(_load_cases, inputs)


def _production_inputs(case: BenchmarkCase) -> ScannerLlmInputs:
    """The inputs a production scan of this session gets, from the same fetch; a session it would not scan is skipped."""
    try:
        payload = fetch_session_payload(case.team_id, case.session_id)
    except IneligibleSessionError as error:
        raise _skip(f"ineligible: {error.kind}") from error
    except Team.DoesNotExist as error:
        raise _skip("team no longer exists") from error
    if payload is None:
        raise _skip("no analytics events")
    return payload


def _skip(reason: str) -> ApplicationError:
    return ApplicationError(reason, type=BENCHMARK_CASE_SKIPPED_ERROR_TYPE, non_retryable=True)


def _prepare_case(layout: BenchmarkLayout, case: BenchmarkCase) -> PrepareBenchmarkCaseOutput:
    # Inputs first: a skipped session costs the labeling app nothing.
    inputs = _production_inputs(case)
    playable = LabelingExportClient.from_settings().playable(case.case_id)
    object_storage.write(
        layout.events_key(case.case_id), zstandard.ZstdCompressor().compress(playable.jsonl), bucket=layout.bucket
    )
    object_storage.write(layout.inputs_key(case.case_id), inputs.model_dump_json(), bucket=layout.bucket)
    return PrepareBenchmarkCaseOutput(
        source_s3_uri=layout.events_uri(case.case_id),
        output_bucket=layout.bucket,
        output_prefix=layout.case_prefix(case.case_id),
        image_refs=playable.image_refs,
        images_resolved=playable.images_resolved,
    )


@activity.defn
@track_activity()
async def prepare_benchmark_case_activity(inputs: PrepareBenchmarkCaseInputs) -> PrepareBenchmarkCaseOutput:
    # Production's fetch reads Postgres and ClickHouse, so it runs where Django manages the connection.
    return await database_sync_to_async(_prepare_case, thread_sensitive=False)(_layout(inputs.version), inputs.case)


def _record_case(inputs: RecordBenchmarkCaseInputs) -> None:
    layout = _layout(inputs.version)
    status = {
        "case_id": inputs.case_id,
        "ok": inputs.render is not None,
        "render": inputs.render,
        "error": inputs.error,
        "image_refs": inputs.image_refs,
        "images_resolved": inputs.images_resolved,
        "skipped": inputs.skipped,
    }
    object_storage.write(layout.status_key(inputs.case_id), json.dumps(status), bucket=layout.bucket)


@activity.defn
@track_activity()
async def record_benchmark_case_activity(inputs: RecordBenchmarkCaseInputs) -> None:
    await asyncio.to_thread(_record_case, inputs)


def _render_settings() -> dict[str, object]:
    return {key: value for key, value in analysis_export_context("").items() if key != "session_recording_id"}


def _write_manifest(inputs: WriteBenchmarkManifestInputs, built_at: str) -> None:
    layout = _layout(inputs.version)
    manifest = {
        "version": inputs.version,
        "built_at": built_at,
        "case_count": inputs.case_count,
        "built": inputs.built,
        "failed": inputs.failed,
        "skipped": inputs.skipped,
        "render_settings": _render_settings(),
    }
    object_storage.write(layout.manifest_key, json.dumps(manifest), bucket=layout.bucket)


@activity.defn
@track_activity()
async def write_benchmark_manifest_activity(inputs: WriteBenchmarkManifestInputs) -> None:
    await asyncio.to_thread(_write_manifest, inputs, activity.info().current_attempt_scheduled_time.isoformat())
