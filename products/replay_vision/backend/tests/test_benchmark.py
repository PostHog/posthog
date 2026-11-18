import io
import gzip
import uuid
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
from products.replay_vision.backend.benchmark.consensus import Question, cell_consensus
from products.replay_vision.backend.benchmark.labeling_api import LabelingExportClient, build_snapshot
from products.replay_vision.backend.benchmark.layout import BenchmarkCase
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
from products.replay_vision.backend.temporal.types import EventTable, ScannerLlmInputs, SessionMetadata

REC_1, REC_2, REC_3 = (f"00000000-0000-4000-8000-00000000000{i}" for i in range(1, 4))
CASE_IDS = [f"00000000-0000-4000-8000-0000000000a{i}" for i in range(6)]


def _question(kind: str, **definition: Any) -> Question:
    return Question(question_id="q1", version=3, type=kind, definition=definition)


def _span_label(*spans: tuple[int, int]) -> dict[str, Any]:
    return {"items": [{"itemId": str(i), "startMs": start, "endMs": end} for i, (start, end) in enumerate(spans)]}


@parameterized.expand(
    [
        ("binary_majority", _question("binary"), [{"choice": True}] * 2 + [{"choice": False}], {"choice": True}),
        ("binary_tie_is_not_ground_truth", _question("binary"), [{"choice": True}, {"choice": False}], None),
        (
            "ordinal_takes_the_median",
            _question("multiple_choice", ordinal=True, options=[{}, {}, {}, {}]),
            [{"choiceIndices": [0]}, {"choiceIndices": [2]}, {"choiceIndices": [3]}],
            {"choiceIndices": [2]},
        ),
        (
            "multi_select_keeps_options_most_labelers_chose",
            _question("multiple_choice", multiple=True, options=[{}, {}, {}]),
            [{"choiceIndices": [0, 1]}, {"choiceIndices": [0]}, {"choiceIndices": [0, 2]}],
            {"choiceIndices": [0]},
        ),
        (
            "multi_select_disagreement_is_not_consensus",
            _question("multiple_choice", multiple=True, options=[{}, {}, {}]),
            [{"choiceIndices": [0, 1]}, {"choiceIndices": [2]}],
            None,
        ),
        (
            "multi_select_most_choosing_none_is_an_answer",
            _question("multiple_choice", multiple=True, options=[{}, {}, {}]),
            [{"choiceIndices": []}, {"choiceIndices": []}, {"choiceIndices": [1]}],
            {"choiceIndices": []},
        ),
        (
            "span_moment_needs_two_labelers",
            _question("itemized"),
            [_span_label((1_000, 4_000), (30_000, 31_000)), _span_label((1_500, 5_000)), {"items": []}],
            {"present": True, "moments": [{"startMs": 1_250, "endMs": 4_500, "labelers": 2}]},
        ),
        (
            "ordinal_split_between_two_values_is_not_consensus",
            _question("multiple_choice", ordinal=True, options=[{}, {}, {}, {}]),
            [{"choiceIndices": [0]}, {"choiceIndices": [3]}],
            None,
        ),
        (
            "span_with_a_boolean_edge_is_dropped",
            _question("itemized"),
            [_span_label((1_000, 4_000)), _span_label((1_500, 5_000)), {"items": [{"startMs": True, "endMs": 9}]}],
            {"present": True, "moments": [{"startMs": 1_250, "endMs": 4_500, "labelers": 2}]},
        ),
        (
            "rating_that_is_not_an_integer_or_is_off_scale_is_no_answer",
            _question("multiple_choice", optionScale={"max": 5}, options=[{"optionId": "a"}]),
            [
                {"ratings": {"a": 4}},
                {"ratings": {"a": 4}},
                {"ratings": {"a": None}},
                {"ratings": {"a": 9}},
                {"ratings": {"a": 9}},
            ],
            {"ratings": {"a": 4}},
        ),
        ("single_label_is_not_consensus", _question("binary"), [{"choice": True}], None),
        ("free_text_has_no_consensus", _question("freeform_long"), [{"response": "a"}, {"response": "a"}], None),
    ]
)
def test_majority_consensus(
    _name: str, question: Question, labels: list[dict[str, Any]], expected: dict[str, Any] | None
) -> None:
    consensus = cell_consensus(question, REC_1, labels)
    if expected is None:
        assert consensus is None
    else:
        assert consensus is not None
        assert {key: consensus.answer[key] for key in expected} == expected


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
        # Two current answers say no; two answers to the old wording say yes and must not outvote them.
        "labels": [answer(0, 2, False), answer(1, 2, False), answer(2, 1, True), answer(3, None, True)],
    }
    unanswered_now = {**recording, "recordingId": REC_2, "labels": [answer(0, 1, True), answer(1, 1, True)]}
    # Answered like rec-1, but its pseudonymous ids join to no production inputs.
    v1 = {**recording, "recordingId": REC_3, "teamRef": "0123456789abcdef0123456789abcdef", "idKind": "pseudonym"}

    snapshot = build_snapshot(questions, [recording, unanswered_now, v1])

    assert [(cell.recording_id, cell.answer["choice"], cell.label_count) for cell in snapshot.cells] == [
        (REC_1, False, 2)
    ]
    assert [(case.case_id, case.team_id, case.session_id) for case in snapshot.cases] == [(REC_1, 2, "s1")]


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
