"""The labeling benchmark suite: Replay Vision answers the labeling suite's questions, scored against every labeler.

Each case is one (recording, question) cell of a built benchmark version. The task asks the question through
the production scan pipeline (`run_scan`, with the same templates, response schemas and events tool) over the
case's rendered video and production inputs, then turns the output into a comparable answer. Edit the templates
under backend/temporal/scanners/prompts/ and re-run to compare, or set REPLAY_VISION_BENCHMARK_MODEL to
compare models.

Requires REPLAY_VISION_BENCHMARK_DIR (a copy written by `pull_replay_vision_benchmark`) and GEMINI_API_KEY.
The build checked AI data-processing consent for every case, and the local copy expires after 30 days.
"""

import os
import json
import time
import asyncio
import datetime as dt
from functools import partial
from pathlib import Path
from typing import Any

import structlog
from google.genai import (
    Client as RawGenAIClient,
    types as genai_types,
)

from products.posthog_ai.eval_harness.config import BaseEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.one_shot import OneShotPrivateEval
from products.replay_vision.backend.benchmark.local import LocalBenchmark
from products.replay_vision.backend.benchmark.questions import answer_from_outputs, scan_requests
from products.replay_vision.backend.models.replay_scanner import ScannerModel
from products.replay_vision.backend.temporal.activities.call_scanner_provider import run_scan
from products.replay_vision.backend.temporal.errors import ScannerFailureError
from products.replay_vision.backend.temporal.gemini import gemini_api_key
from products.replay_vision.backend.temporal.scanners import scanner_from_snapshot
from products.replay_vision.backend.temporal.video_clock import VideoClock, video_clock_from_export_context
from products.replay_vision.evals.scorers import Answered, LabelAgreement, LabelerAgreement

SUITE_KIND = SuiteKind.ONE_SHOT

logger = structlog.get_logger(__name__)

BENCHMARK_DIR_ENV_VAR = "REPLAY_VISION_BENCHMARK_DIR"
BENCHMARK_MODEL_ENV_VAR = "REPLAY_VISION_BENCHMARK_MODEL"
_MAX_PROCESSING_WAIT_SECONDS = 300


def _upload_video(client: RawGenAIClient, path: Path) -> genai_types.File:
    uploaded = client.files.upload(
        file=str(path),
        config=genai_types.UploadFileConfig(
            mime_type="video/mp4", display_name=f"replay-vision-benchmark-{path.parent.name}"
        ),
    )
    waited = 0.0
    while uploaded.state and uploaded.state.name == "PROCESSING":
        if waited >= _MAX_PROCESSING_WAIT_SECONDS:
            raise RuntimeError(f"Gemini file for {path} stuck in PROCESSING after {waited:.0f}s")
        time.sleep(0.5)
        waited += 0.5
        uploaded = client.files.get(name=uploaded.name or "")
    state = uploaded.state.name if uploaded.state else None
    if state != "ACTIVE" or not uploaded.uri:
        raise RuntimeError(f"Gemini upload for {path} ended in state {state!r}")
    return uploaded


def _delete_file_quiet(client: RawGenAIClient, name: str | None) -> None:
    if not name:
        return
    try:
        client.files.delete(name=name)
    except Exception:
        logger.warning("replay_vision.benchmark_eval.gemini_delete_failed", file=name)


class _Uploads:
    """One Gemini upload per recording, shared by every question asked about it and deleted after the run."""

    def __init__(self, client: RawGenAIClient, benchmark: LocalBenchmark) -> None:
        self._client = client
        self._benchmark = benchmark
        self._tasks: dict[str, asyncio.Task[genai_types.File]] = {}

    async def get(self, case_id: str) -> genai_types.File:
        if case_id not in self._tasks:
            path = self._benchmark.video_path(case_id)
            self._tasks[case_id] = asyncio.ensure_future(asyncio.to_thread(_upload_video, self._client, path))
        return await self._tasks[case_id]

    async def delete_all(self) -> None:
        for task in self._tasks.values():
            if task.done() and not task.cancelled() and task.exception() is None:
                await asyncio.to_thread(_delete_file_quiet, self._client, task.result().name)


def build_cases(benchmark: LocalBenchmark, model: str) -> list[BaseEvalCase]:
    domains = {case.case_id: case.domain for case in benchmark.cases}
    cases = []
    for cell in benchmark.cells:
        question = benchmark.questions.get(cell.question_id)
        if question is None or question.version != cell.question_version or not scan_requests(question, model):
            continue
        cases.append(
            BaseEvalCase(
                name=f"{cell.recording_id}-{cell.question_id}",
                prompt=str(question.definition.get("prompt", "")),
                expected={"cell": {"question": question.model_dump(mode="json"), "labels": cell.answers}},
                metadata={
                    "case_id": cell.recording_id,
                    "question_id": cell.question_id,
                    "answer_kind": question.kind,
                    "domain": domains.get(cell.recording_id),
                    "model": model,
                },
            )
        )
    return cases


async def _answer_task(
    benchmark: LocalBenchmark, uploads: _Uploads, model: str, case: BaseEvalCase, ctx: EvalContext
) -> dict[str, Any]:
    case_id = case.metadata["case_id"]
    question = benchmark.questions[case.metadata["question_id"]]
    llm_inputs = await asyncio.to_thread(benchmark.inputs, case_id)
    render = await asyncio.to_thread(benchmark.render, case_id)
    uploaded = await uploads.get(case_id)
    periods = [period.model_dump(mode="json") for period in render.inactivity_periods]
    video_clock = video_clock_from_export_context({"inactivity_periods": periods}) or VideoClock(spans=())

    async def scan(request: Any) -> tuple[str, dict[str, Any] | str]:
        try:
            result = await run_scan(
                snapshot=request.snapshot,
                scanner=scanner_from_snapshot(request.snapshot),
                llm_inputs=llm_inputs,
                team_name=case.metadata["domain"] or "this product",
                file_uri=uploaded.uri or "",
                mime_type=uploaded.mime_type or "video/mp4",
                team_id=llm_inputs.team_id,
                video_clock=video_clock,
            )
        except ScannerFailureError as exc:
            # A scan the model cannot complete is a quality signal, so it scores as no answer, not an infra error.
            return request.key, str(exc)
        return request.key, result.model_output.model_dump(mode="json")

    results = await asyncio.gather(*(scan(request) for request in scan_requests(question, model)))
    outputs = {key: value for key, value in results if isinstance(value, dict)}
    errors = [value for _, value in results if isinstance(value, str)]
    answer = answer_from_outputs(question, outputs)
    return {
        "answer": answer,
        "outputs": outputs,
        "error": "; ".join(errors) or None,
        "last_message": json.dumps(answer),
    }


async def eval_benchmark(ctx: EvalContext) -> None:
    root = os.environ.get(BENCHMARK_DIR_ENV_VAR)
    if not root:
        # Skip rather than fail: the copy is local-only, so a full `hogli evals` run without one still passes.
        logger.warning("replay_vision.benchmark_eval.skipped_no_copy", env_var=BENCHMARK_DIR_ENV_VAR)
        return
    if not gemini_api_key():
        raise RuntimeError("Set GEMINI_API_KEY (or REPLAY_VISION_GEMINI_API_KEY) to run replay-vision scans")

    benchmark = LocalBenchmark.load(Path(root).expanduser(), dt.datetime.now(dt.UTC))
    model = os.environ.get(BENCHMARK_MODEL_ENV_VAR) or ScannerModel.GEMINI_3_FLASH_PREVIEW
    uploads = _Uploads(RawGenAIClient(api_key=gemini_api_key()), benchmark)
    try:
        await OneShotPrivateEval(
            # One history per version and tier, so runs with different prompts or models compare in place.
            experiment_name=f"replay-vision-benchmark-{benchmark.record.version}-{benchmark.record.tier}",
            cases=build_cases(benchmark, str(model)),
            scorers=[Answered(), LabelAgreement(), LabelerAgreement()],
            task=partial(_answer_task, benchmark, uploads, str(model)),
            ctx=ctx,
        )
    finally:
        await uploads.delete_all()
