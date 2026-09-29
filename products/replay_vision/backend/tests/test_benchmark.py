import io
import gzip
import json
import uuid
import pathlib
import datetime as dt
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import temporalio.worker
from parameterized import parameterized
from temporalio import (
    activity,
    workflow as wf,
)
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.temporal.session_replay.rasterize_recording.types import (
    RasterizationActivityInput,
    RasterizationActivityOutput,
    RasterizeRecordingInputs,
)

from products.replay_vision.backend.benchmark import labeling_api
from products.replay_vision.backend.benchmark.labeling_api import LabelingExportClient, build_snapshot
from products.replay_vision.backend.benchmark.labels import Question, comparable_answer
from products.replay_vision.backend.benchmark.layout import BenchmarkCase, BenchmarkLayout
from products.replay_vision.backend.benchmark.local import LocalBenchmark, pull_version
from products.replay_vision.backend.benchmark.questions import WHOLE_QUESTION, answer_from_outputs, scan_requests
from products.replay_vision.backend.benchmark.scoring import labeler_agreement, similarity
from products.replay_vision.backend.error_kinds import IneligibleSessionKind
from products.replay_vision.backend.temporal import benchmark_workflow
from products.replay_vision.backend.temporal.activities import benchmark as benchmark_activities
from products.replay_vision.backend.temporal.benchmark_types import (
    BENCHMARK_CASE_ALREADY_BUILT_ERROR_TYPE,
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
from products.replay_vision.backend.temporal.benchmark_workflow import BuildBenchmarkWorkflow
from products.replay_vision.backend.temporal.constants import BUILD_BENCHMARK_WORKFLOW_NAME
from products.replay_vision.backend.temporal.errors import IneligibleSessionError
from products.replay_vision.backend.temporal.scanners import scanner_from_snapshot
from products.replay_vision.backend.temporal.types import EventTable, ScannerLlmInputs, SessionMetadata

REC_1, REC_2, REC_3 = (f"00000000-0000-4000-8000-00000000000{i}" for i in range(1, 4))
CASE_IDS = [f"00000000-0000-4000-8000-0000000000a{i}" for i in range(6)]


def _question(kind: str, **definition: Any) -> Question:
    return Question(question_id="q1", version=3, type=kind, definition=definition)


@parameterized.expand(
    [
        ("binary_keeps_a_real_boolean", _question("binary"), {"choice": True}, {"choice": True}),
        ("binary_without_a_choice_is_no_answer", _question("binary"), {"choice": None}, None),
        (
            "single_choice_with_two_picks_is_no_answer",
            _question("multiple_choice", options=[{}, {}, {}]),
            {"choiceIndices": [0, 2]},
            None,
        ),
        (
            "choice_outside_the_options_is_no_answer",
            _question("multiple_choice", multiple=True, options=[{}, {}]),
            {"choiceIndices": [0, 5]},
            None,
        ),
        (
            "rating_that_is_not_an_integer_or_is_off_scale_is_dropped",
            _question("multiple_choice", optionScale={"max": 5}, options=[{"optionId": "a"}]),
            {"ratings": {"a": 4, "b": None, "c": 9, "d": True}},
            {"ratings": {"a": 4}},
        ),
        (
            "span_with_a_boolean_edge_is_dropped",
            _question("itemized"),
            {"items": [{"startMs": 1_000, "endMs": 4_000}, {"startMs": True, "endMs": 9}]},
            {"present": True, "moments": [{"startMs": 1_000, "endMs": 4_000}]},
        ),
        (
            "no_markers_means_absent",
            _question("timeline_marking"),
            {"markers": []},
            {"present": False, "moments": []},
        ),
        ("free_text_is_not_comparable", _question("freeform_long"), {"response": "a"}, None),
    ]
)
def test_comparable_answer(
    _name: str, question: Question, label: dict[str, Any], expected: dict[str, Any] | None
) -> None:
    assert comparable_answer(question, label) == expected


def _moments(*spans: tuple[int, int]) -> dict[str, Any]:
    return {"present": bool(spans), "moments": [{"startMs": start, "endMs": end} for start, end in spans]}


@parameterized.expand(
    [
        (
            "ordinal_scores_by_distance_on_the_scale",
            _question("multiple_choice", ordinal=True, options=[{}, {}, {}, {}, {}]),
            {"choiceIndices": [1]},
            {"choiceIndices": [3]},
            0.5,
        ),
        (
            "multi_select_scores_the_overlap",
            _question("multiple_choice", multiple=True, options=[{}, {}, {}]),
            {"choiceIndices": [0, 1]},
            {"choiceIndices": [1, 2]},
            1 / 3,
        ),
        (
            "ratings_compare_only_options_both_rated",
            _question("multiple_choice", optionScale={"max": 5}, options=[{"optionId": "a"}, {"optionId": "b"}]),
            {"ratings": {"a": 5, "b": 1}},
            {"ratings": {"a": 4}},
            0.75,
        ),
        ("spans_disagreeing_on_presence_score_zero", _question("itemized"), _moments((0, 1)), _moments(), 0.0),
        ("spans_both_absent_agree", _question("itemized"), _moments(), _moments(), 1.0),
        (
            # A citation within the tolerance of a marked moment hits it; the second marked moment is missed.
            "citation_near_a_moment_counts_and_a_missed_moment_costs_recall",
            _question("timeline_marking"),
            _moments((5_500, 5_500)),
            _moments((1_000, 4_000), (30_000, 31_000)),
            2 / 3,
        ),
    ]
)
def test_similarity(
    _name: str, question: Question, answer: dict[str, Any], reference: dict[str, Any], expected: float
) -> None:
    assert similarity(question, answer, reference) == pytest.approx(expected)


@parameterized.expand(
    [
        ("each_labeler_against_the_others", [{"choice": True}, {"choice": True}, {"choice": False}], 1 / 3),
        ("one_labeler_has_nobody_to_agree_with", [{"choice": True}], None),
    ]
)
def test_labeler_agreement(_name: str, labels: list[dict[str, Any]], expected: float | None) -> None:
    assert labeler_agreement(_question("binary"), labels) == (pytest.approx(expected) if expected is not None else None)


@parameterized.expand(
    [
        (
            "monitor_citations_become_moments",
            _question("timeline_marking"),
            {
                WHOLE_QUESTION: {
                    "verdict": "yes",
                    "reasoning_segments": [{"kind": "text", "value": "x"}, {"kind": "chip", "timestamp_ms": 12_000}],
                }
            },
            {"present": True, "moments": [{"startMs": 12_000, "endMs": 12_000}]},
        ),
        (
            "classifier_picking_two_options_on_a_single_choice_is_no_answer",
            _question("multiple_choice", options=[{"label": "Pricing"}, {"label": "Docs"}]),
            {WHOLE_QUESTION: {"tags": ["Pricing", "Docs"]}},
            None,
        ),
        (
            "scores_round_onto_the_rating_scale",
            _question("multiple_choice", optionScale={"max": 5}, options=[{"optionId": "a"}, {"optionId": "b"}]),
            {"a": {"score": 3.6}, "b": {"score": 7.0}},
            {"ratings": {"a": 4, "b": 5}},
        ),
    ]
)
def test_answer_from_outputs(
    _name: str, question: Question, outputs: dict[str, dict[str, Any]], expected: dict[str, Any] | None
) -> None:
    assert answer_from_outputs(question, outputs) == expected


@parameterized.expand(
    [
        ("binary_runs_one_monitor", "binary", {}, [WHOLE_QUESTION]),
        ("timeline_runs_one_monitor", "timeline_marking", {}, [WHOLE_QUESTION]),
        (
            "choice_runs_one_classifier",
            "multiple_choice",
            {"options": [{"label": "A"}, {"label": "B"}]},
            [WHOLE_QUESTION],
        ),
        (
            "rating_scale_runs_one_scorer_per_option",
            "multiple_choice",
            {"optionScale": {"max": 5}, "options": [{"optionId": "a", "label": "A"}, {"optionId": "b", "label": "B"}]},
            ["a", "b"],
        ),
        # The classifier pins its options as an enum, so a repeated label would fail every scan of the question.
        (
            "repeated_option_labels_cannot_be_asked",
            "multiple_choice",
            {"options": [{"label": "Y"}, {"label": "Y"}]},
            [],
        ),
    ]
)
def test_scan_requests(_name: str, kind: str, definition: dict[str, Any], expected_keys: list[str]) -> None:
    requests = scan_requests(_question(kind, prompt="How was it?", **definition), "gemini-3-flash-preview")

    assert [request.key for request in requests] == expected_keys
    # Each config must pass the production scanner validation, or every scan of the question fails.
    for request in requests:
        scanner_from_snapshot(request.snapshot)


def _raw(body: bytes) -> MagicMock:
    stream = io.BytesIO(body)
    raw = MagicMock()
    raw.read.side_effect = lambda size, decode_content: stream.read(size)
    return raw


def test_playable_refuses_a_body_cut_before_its_gzip_trailer() -> None:
    cut = MagicMock(status_code=200, raw=_raw(gzip.compress(b'{"type":4}\n' * 100)[:-8]), headers={})
    client = LabelingExportClient("https://labeling.example.com", "lbl_test")
    with patch.object(labeling_api.requests, "get", return_value=cut), client.playable(REC_1) as playable:
        with pytest.raises(OSError, match="gzip trailer"):
            playable.stream.read()


def test_playable_waits_out_a_busy_labeling_app() -> None:
    busy = MagicMock(status_code=429)
    ready = MagicMock(status_code=200, raw=_raw(gzip.compress(b"{}\n")), headers={"x-benchmark-images-resolved": "3"})
    client = LabelingExportClient("https://labeling.example.com", "lbl_test")
    with (
        patch.object(labeling_api.requests, "get", side_effect=[busy, busy, ready]),
        patch.object(labeling_api.time, "sleep"),
        client.playable(REC_1) as playable,
    ):
        body = playable.stream.read()

    assert (body, playable.images_resolved) == (b"{}\n", 3)
    busy.raise_for_status.assert_not_called()


def test_snapshot_keeps_v2_recordings_and_current_question_versions() -> None:
    questions = [{"questionId": "q1", "version": 2, "question": {"questionId": "q1", "type": "binary"}}]

    def answer(coder: int, version: int | None, choice: bool) -> dict[str, Any]:
        return {"questionId": "q1", "questionVersion": version, "coder": coder, "label": {"choice": choice}}

    recording = {
        "recordingId": REC_1,
        "split": "validation",
        "domain": "example.com",
        "teamRef": "2",
        "sessionRef": "s1",
        "idKind": "real",
        "siteBrief": None,
        # Two current answers say no; the two answers to the old wording must not be pooled with them.
        "labels": [answer(0, 2, False), answer(1, 2, False), answer(2, 1, True), answer(3, None, True)],
    }
    unanswered_now = {**recording, "recordingId": REC_2, "labels": [answer(0, 1, True), answer(1, 1, True)]}
    # Answered like rec-1, but its pseudonymous ids join to no production inputs.
    v1 = {**recording, "recordingId": REC_3, "teamRef": "0123456789abcdef0123456789abcdef", "idKind": "pseudonym"}

    snapshot = build_snapshot(questions, [recording, unanswered_now, v1])

    assert [(cell.recording_id, cell.answers) for cell in snapshot.cells] == [(REC_1, [{"choice": False}] * 2)]
    assert [(case.case_id, case.team_id, case.session_id) for case in snapshot.cases] == [(REC_1, 2, "s1")]


class _FakeS3:
    class exceptions:
        class ClientError(Exception):
            def __init__(self, code: str) -> None:
                self.response = {"Error": {"Code": code}}

        class NoSuchKey(Exception):
            pass

    def __init__(self, objects: dict[tuple[str, str], bytes]) -> None:
        self.objects = objects

    def head_object(self, Bucket: str, Key: str) -> None:
        if (Bucket, Key) not in self.objects:
            raise self.exceptions.ClientError("404")

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        if (Bucket, Key) not in self.objects:
            raise self.exceptions.NoSuchKey()
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def download_file(self, bucket: str, key: str, path: str) -> None:
        pathlib.Path(path).write_bytes(self.objects[(bucket, key)])


def test_a_pulled_copy_holds_only_built_cases_and_expires(tmp_path: pathlib.Path) -> None:
    layout = BenchmarkLayout("v1", bucket="bench", prefix="rvb")
    built, failed, unrecorded = CASE_IDS[:3]
    render = RasterizationActivityOutput(s3_uri="s3://videos/built.mp4", video_duration_s=10, playback_speed=1)
    objects = {
        (layout.bucket, layout.manifest_key): b"{}",
        (layout.bucket, layout.questions_key): b"[]",
        (layout.bucket, layout.labels_key): b"",
        (layout.bucket, layout.cases_key): "\n".join(
            BenchmarkCase(case_id=case_id, split=None, domain=None, team_id=2, session_id="s").model_dump_json()
            for case_id in (built, failed, unrecorded)
        ).encode(),
        (layout.bucket, layout.status_key(built)): json.dumps(
            {"outcome": "built", "render": render.model_dump(mode="json")}
        ).encode(),
        (layout.bucket, layout.status_key(failed)): b'{"outcome": "failed"}',
        (layout.bucket, layout.inputs_key(built)): PRODUCTION_INPUTS.model_dump_json().encode(),
        ("videos", "built.mp4"): b"mp4",
    }
    pulled_at = dt.datetime(2026, 9, 1, tzinfo=dt.UTC)

    pull_version(_FakeS3(objects), layout, "full", tmp_path, pulled_at)
    copy = LocalBenchmark.load(tmp_path, pulled_at + dt.timedelta(days=1))

    assert [case.case_id for case in copy.cases] == [built]
    assert copy.video_path(built).read_bytes() == b"mp4"
    with pytest.raises(RuntimeError, match="older than 30 days"):
        LocalBenchmark.load(tmp_path, pulled_at + dt.timedelta(days=31))


PRODUCTION_INPUTS = ScannerLlmInputs(
    session_id="sess-1",
    team_id=2,
    events=EventTable(columns=["event_uuid"], rows=[]),
    metadata=SessionMetadata(start_time="2026-09-01T00:00:00Z", end_time="2026-09-01T00:05:00Z", duration_seconds=300),
)


@parameterized.expand(
    [
        ("no_consent", False, PRODUCTION_INPUTS, "no AI data processing consent"),
        (
            "production_would_not_scan_it",
            True,
            IneligibleSessionError("too short", kind=IneligibleSessionKind.TOO_SHORT),
            f"ineligible: {IneligibleSessionKind.TOO_SHORT}",
        ),
        ("no_analytics_events", True, None, "no analytics events"),
    ]
)
def test_a_session_without_production_inputs_is_skipped(
    _name: str, consented: bool, fetched: Any, expected_reason: str
) -> None:
    case = BenchmarkCase(case_id=REC_1, split="validation", domain=None, team_id=2, session_id="sess-1")
    with (
        patch.object(benchmark_activities, "is_ai_data_processing_approved", return_value=consented),
        patch.object(benchmark_activities, "fetch_session_payload", side_effect=[fetched]),
        pytest.raises(ApplicationError) as raised,
    ):
        benchmark_activities._production_inputs(case)

    assert (raised.value.type, raised.value.message) == (BENCHMARK_CASE_SKIPPED_ERROR_TYPE, expected_reason)


@wf.defn(name="rasterize-recording")
class _FakeRasterizeWorkflow:
    @wf.run
    async def run(self, inputs: RasterizeRecordingInputs) -> RasterizationActivityOutput:
        assert inputs.render_input is not None
        session_id = inputs.render_input.session_id
        if session_id == CASE_IDS[1]:
            raise ApplicationError("render crashed", type="RENDER_FAILED", non_retryable=True)
        if session_id == CASE_IDS[3]:
            raise ApplicationError("nothing to draw", type="NO_SNAPSHOTS", non_retryable=True)
        return RasterizationActivityOutput(
            s3_uri=f"s3://bench/{session_id}/video.mp4", video_duration_s=10, playback_speed=8
        )


@pytest.mark.asyncio
async def test_build_continues_past_failed_and_skipped_cases_and_counts_them() -> None:
    cases = [
        BenchmarkCase(case_id=case_id, split="validation", domain=None, team_id=2, session_id=f"s{i}")
        for i, case_id in enumerate(CASE_IDS)
    ]
    recorded: list[RecordBenchmarkCaseInputs] = []
    manifests: list[WriteBenchmarkManifestInputs] = []

    @activity.defn(name="snapshot_benchmark_labels_activity")
    async def snapshot(inputs: SnapshotBenchmarkInputs) -> SnapshotBenchmarkOutput:
        return SnapshotBenchmarkOutput(case_count=len(cases))

    @activity.defn(name="load_benchmark_cases_activity")
    async def load(inputs: LoadBenchmarkCasesInputs) -> LoadBenchmarkCasesOutput:
        return LoadBenchmarkCasesOutput(cases=cases[inputs.offset : inputs.offset + inputs.limit])

    @activity.defn(name="prepare_benchmark_case_activity")
    async def prepare(inputs: PrepareBenchmarkCaseInputs) -> PrepareBenchmarkCaseOutput:
        if inputs.case.case_id == CASE_IDS[2]:
            raise ApplicationError("ineligible: too_short", type=BENCHMARK_CASE_SKIPPED_ERROR_TYPE, non_retryable=True)
        if inputs.case.case_id == CASE_IDS[4]:
            raise ApplicationError("already built", type=BENCHMARK_CASE_ALREADY_BUILT_ERROR_TYPE, non_retryable=True)
        render_input = RasterizationActivityInput(
            session_id=inputs.case.case_id, team_id=1, s3_bucket="bench", s3_key_prefix=inputs.case.case_id
        )
        return PrepareBenchmarkCaseOutput(render_input=render_input, image_refs=1, images_resolved=1)

    @activity.defn(name="record_benchmark_case_activity")
    async def record(inputs: RecordBenchmarkCaseInputs) -> None:
        if inputs.case_id == CASE_IDS[5]:
            raise ApplicationError("bucket unavailable", non_retryable=True)
        recorded.append(inputs)

    @activity.defn(name="write_benchmark_manifest_activity")
    async def manifest(inputs: WriteBenchmarkManifestInputs) -> None:
        manifests.append(inputs)

    workflow_queue = str(uuid.uuid4())
    render_queue = str(uuid.uuid4())
    runner = temporalio.worker.UnsandboxedWorkflowRunner()
    with (
        patch.object(benchmark_workflow, "CASES_PER_RUN", 2),
        patch.object(benchmark_workflow.settings, "SESSION_REPLAY_TASK_QUEUE", render_queue),
    ):
        async with await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter) as env:
            async with (
                Worker(
                    env.client,
                    task_queue=workflow_queue,
                    workflows=[BuildBenchmarkWorkflow],
                    activities=[snapshot, load, prepare, record, manifest],
                    workflow_runner=runner,
                ),
                Worker(env.client, task_queue=render_queue, workflows=[_FakeRasterizeWorkflow], workflow_runner=runner),
            ):
                await env.client.execute_workflow(
                    BUILD_BENCHMARK_WORKFLOW_NAME,
                    BuildBenchmarkInputs(version="v1"),
                    id=str(uuid.uuid4()),
                    task_queue=workflow_queue,
                )

    by_case = {r.case_id: (r.outcome, r.reason) for r in recorded}
    assert by_case[CASE_IDS[0]] == ("built", None)
    assert by_case[CASE_IDS[1]][0] == "failed"
    # Skipped before rendering, and a recording production would gate as ineligible.
    assert by_case[CASE_IDS[2]] == ("skipped", "ineligible: too_short")
    assert by_case[CASE_IDS[3]] == ("skipped", "render: NO_SNAPSHOTS")
    # Built by an earlier run, so counted without a second render or record; a failed record fails one case.
    assert CASE_IDS[4] not in by_case and CASE_IDS[5] not in by_case
    assert [(m.case_count, m.built, m.failed, m.skipped) for m in manifests] == [(6, 2, 2, 2)]
