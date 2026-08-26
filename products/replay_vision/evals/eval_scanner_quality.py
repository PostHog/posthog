"""Golden-dataset quality suite for Replay Vision scanner prompts.

Each case re-runs the production scan pipeline (same Jinja templates, response schemas, events
tool, and citation handling, via run_scan) against a collected session video plus its event
snapshot, then scores the fresh output against the recorded output and its human thumbs label.
Edit the templates under backend/temporal/scanners/prompts/ and re-run to compare experiments
in the local logs (this suite is private; nothing is sent to Braintrust).

Requires REPLAY_VISION_EVAL_DATASET (a directory written by collect.py) and GEMINI_API_KEY.
"""

import time
import asyncio
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
from products.replay_vision.backend.prompt_evaluation import primary_outcome
from products.replay_vision.backend.temporal.activities.call_scanner_provider import apply_known_freeform_tags, run_scan
from products.replay_vision.backend.temporal.errors import ScannerFailureError
from products.replay_vision.backend.temporal.gemini import gemini_api_key
from products.replay_vision.backend.temporal.scanners import scanner_from_snapshot
from products.replay_vision.evals.dataset import (
    DATASET_ENV_VAR,
    GoldenCase,
    dataset_root,
    ensure_dataset_fresh,
    load_dataset,
)
from products.replay_vision.evals.scorers import (
    SUMMARY_FIELDS,
    LabeledOutcome,
    OutputStability,
    ScanCompleted,
    ScoreAlignment,
    SummaryAlignment,
)

SUITE_KIND = SuiteKind.ONE_SHOT

logger = structlog.get_logger(__name__)

_MAX_PROCESSING_WAIT_SECONDS = 300


def build_case(golden: GoldenCase) -> BaseEvalCase:
    """Map a golden case onto the scorer contract: which scorer applies, and what its reference is."""
    expected: dict[str, Any] = {}
    recorded_primary = primary_outcome(golden.recorded_output)
    if golden.scanner_type in ("monitor", "classifier"):
        if golden.label_is_correct is not None:
            expected["labeled_outcome"] = {
                "is_correct": golden.label_is_correct,
                "recorded_primary": recorded_primary,
            }
        else:
            expected["output_stability"] = {"recorded_primary": recorded_primary}
    elif golden.scanner_type == "scorer":
        recorded_score = golden.recorded_output.get("score")
        scale = golden.snapshot.scanner_config.get("scale") or {}
        scale_min, scale_max = scale.get("min"), scale.get("max")
        # Default the bounds as a pair: defaulting them independently can fabricate a zero-width
        # scale (e.g. min set to 1.0 with max defaulting to 1.0) that no scanner actually has.
        if scale_min is None and scale_max is None:
            scale_min, scale_max = 0.0, 1.0
        # A thumbs-downed recorded score is a known-bad reference, so those cases only get scan_completed.
        if (
            golden.label_is_correct is not False
            and isinstance(recorded_score, int | float)
            and scale_min is not None
            and scale_max is not None
        ):
            expected["score_alignment"] = {
                "recorded_score": recorded_score,
                "scale_min": scale_min,
                "scale_max": scale_max,
            }
    elif golden.scanner_type == "summarizer":
        if golden.label_is_correct is not False:
            expected["summary_alignment"] = {
                "reference": {field: golden.recorded_output.get(field) for field in SUMMARY_FIELDS}
            }
    return BaseEvalCase(
        # The full case id: UUIDv7 ids collected in the same minute share their first characters,
        # so any truncation makes same-type cases collide.
        name=f"{golden.scanner_type}-{golden.case_id}",
        prompt=str(golden.snapshot.scanner_config.get("prompt", "")),
        expected=expected,
        metadata={
            "case_id": golden.case_id,
            "scanner_name": golden.scanner_name,
            "scanner_type": golden.scanner_type,
            "session_id": golden.session_id,
            "label_is_correct": golden.label_is_correct,
        },
    )


def _upload_video(client: RawGenAIClient, path: Path) -> genai_types.File:
    uploaded = client.files.upload(
        file=str(path),
        config=genai_types.UploadFileConfig(
            mime_type="video/mp4", display_name=f"replay-vision-eval-{path.parent.name}"
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
        logger.warning("replay_vision.eval.gemini_delete_failed", file=name)


async def _scan_task(
    root: Path, golden_by_case_id: dict[str, GoldenCase], case: BaseEvalCase, ctx: EvalContext
) -> dict[str, Any]:
    golden = golden_by_case_id[case.metadata["case_id"]]
    llm_inputs = await asyncio.to_thread(golden.load_inputs, root)
    # Rebuild the scanner the way production does, tag vocabulary included, so a freeform classifier
    # is scored on its prompt rather than on missing context.
    scanner = apply_known_freeform_tags(scanner_from_snapshot(golden.snapshot), golden.known_freeform_tags)
    client = RawGenAIClient(api_key=gemini_api_key())
    uploaded = await asyncio.to_thread(_upload_video, client, golden.video_path(root))
    try:
        try:
            result = await run_scan(
                snapshot=golden.snapshot,
                scanner=scanner,
                llm_inputs=llm_inputs,
                team_name=golden.team_name,
                file_uri=uploaded.uri or "",
                mime_type=uploaded.mime_type or "video/mp4",
                team_id=golden.team_id,
            )
        except ScannerFailureError as exc:
            # A scan the model cannot complete is a prompt-quality signal (broken schema compliance),
            # not an infra error, so it must score 0 rather than be excluded from the aggregate.
            return {
                "exit_code": 1,
                "model_output": None,
                "error": str(exc),
                "scanner_type": golden.scanner_type,
                "last_message": f"scan failed: {exc}",
            }
    finally:
        await asyncio.to_thread(_delete_file_quiet, client, uploaded.name)

    model_output = result.model_output.model_dump(mode="json")
    primary = primary_outcome(model_output)
    return {
        "exit_code": 0,
        "model_output": model_output,
        "error": None,
        "scanner_type": golden.scanner_type,
        "signals_count": len(result.signals),
        "primary": primary,
        "last_message": primary or "",
    }


async def eval_scanner_quality(ctx: EvalContext) -> None:
    root = dataset_root()
    if root is None:
        # Skip rather than fail: the dataset is local-only and most environments (CI included) won't have one.
        logger.warning("replay_vision.eval.skipped_no_dataset", env_var=DATASET_ENV_VAR)
        return
    if not gemini_api_key():
        raise RuntimeError("Set GEMINI_API_KEY (or REPLAY_VISION_GEMINI_API_KEY) to run replay-vision scans")

    dataset = load_dataset(root)
    ensure_dataset_fresh(dataset, root)
    golden_cases = dataset.cases
    missing = [g.case_id for g in golden_cases if not (g.video_path(root).exists() and g.inputs_path(root).exists())]
    if missing:
        raise RuntimeError(f"Dataset at {root} is missing files for cases {missing[:5]}; re-run collect.py")

    cases = [build_case(golden) for golden in golden_cases]
    golden_by_case_id = {case.metadata["case_id"]: golden for case, golden in zip(cases, golden_cases)}
    # A collision here would silently score one observation against another session's video.
    if len(golden_by_case_id) != len(golden_cases):
        raise RuntimeError(f"Dataset at {root} contains duplicate case ids; re-collect into a clean directory")
    await OneShotPrivateEval(
        experiment_name="replay-vision-scanner-quality",
        cases=cases,
        scorers=[ScanCompleted(), LabeledOutcome(), OutputStability(), ScoreAlignment(), SummaryAlignment()],
        task=partial(_scan_task, root, golden_by_case_id),
        ctx=ctx,
    )
