"""Braintrust entrypoint for the self-driving eval (project: signals-self-driving).

One experiment per run, one row per (task, trial). The pipeline orchestration is
the runner's job: callers inject `run_fn`, an async callable returning the
`TaskRunResult.to_json()` dict for one (task_id, trial). This module only builds
the eval cases, grades each result via harness.grade, and converts grades into
Braintrust scores - it never touches Django itself, so it stays importable from
a bare Python process.
"""

from __future__ import annotations

import json
import asyncio
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

from braintrust import EvalAsync, EvalCase, Score
from braintrust.framework import EvalHooks, EvalResultWithSummary

from products.signals.eval.self_driving.harness.grade import TASKS_DIR, grade_result, load_task_spec

PROJECT_NAME = "signals-self-driving"

RunFn = Callable[[str, int], Awaitable[dict[str, Any]]]
"""(task_id, trial) -> TaskRunResult.to_json() dict; drives the real pipeline inside Django."""

SCORER_NAMES: tuple[str, ...] = (
    # Stage R - research
    "root_cause_identified",
    "evidence_grounding",
    "distractor_avoidance",
    "actionability_calibration",
    "priority_calibration",
    "pipeline_progression",
    # Stage I - implementation
    "behavioral_correctness",
    "no_regressions",
    "mergeability",
    "pr_narrative",
    "task_completion",
    # End-to-end
    "e2e_resolution",
)


def _signal_excerpt(task_id: str, limit: int = 500) -> str:
    signals_path = TASKS_DIR / task_id / "signals.json"
    if not signals_path.is_file():
        return ""
    try:
        records = json.loads(signals_path.read_text())
    except json.JSONDecodeError:
        return ""
    if not isinstance(records, list) or not records:
        return ""
    first = records[0] if isinstance(records[0], dict) else {}
    parts = [str(first.get(key)) for key in ("subject", "title", "description", "body") if first.get(key)]
    return " - ".join(parts)[:limit]


def build_cases(task_ids: Sequence[str], trials: int) -> list[EvalCase[dict[str, Any], dict[str, Any]]]:
    cases: list[EvalCase[dict[str, Any], dict[str, Any]]] = []
    for task_id in task_ids:
        spec = load_task_spec(task_id)
        for trial in range(trials):
            cases.append(
                EvalCase(
                    input={
                        "task_id": task_id,
                        "trial": trial,
                        "title": spec.get("title"),
                        "difficulty": spec.get("difficulty"),
                        "family": spec.get("family"),
                        "signal_excerpt": _signal_excerpt(task_id),
                    },
                    expected=spec.get("ground_truth", {}),
                    metadata={
                        "task_id": task_id,
                        "trial": trial,
                        "difficulty": spec.get("difficulty"),
                        "family": spec.get("family"),
                        "repo_full_name": spec.get("repo_full_name"),
                    },
                )
            )
    return cases


def _make_scorer(name: str) -> Callable[..., Score]:
    def scorer(input: dict[str, Any], output: dict[str, Any] | None, expected: Any) -> Score:
        grades = (output or {}).get("grades") or {}
        entry = grades.get(name)
        if not isinstance(entry, dict):
            return Score(name=name, score=None, metadata={"reason": "not graded"})
        return Score(name=name, score=entry.get("score"), metadata={"reasoning": entry.get("reasoning")})

    scorer.__name__ = name
    return scorer


async def run_eval(
    task_ids: Sequence[str],
    trials: int,
    workspace: Path,
    experiment_name: str,
    run_fn: RunFn,
    max_concurrency: int = 2,
    timeout_s: float = 4 * 60 * 60,
) -> EvalResultWithSummary[dict[str, Any], dict[str, Any]]:
    """Run the eval: one row per (task, trial), scores from grade_result.

    `workspace` is the runner's workspace root - patched working copies are
    expected under workspace/repos/<task_id> (the mounted repos the agents
    committed into).
    """
    repos_workspace = workspace / "repos"

    async def eval_task(input: dict[str, Any], hooks: EvalHooks[dict[str, Any]]) -> dict[str, Any]:
        task_id = input["task_id"]
        result = await run_fn(task_id, input["trial"])
        spec = load_task_spec(task_id)
        # Grading is blocking (subprocesses + judge HTTP calls) - keep it off the loop.
        grades = await asyncio.to_thread(grade_result, spec, result, repos_workspace)
        report = result.get("report") or {}
        hooks.meta(
            team_id=result.get("team_id"),
            timings=result.get("timings"),
            patch_size=len(result.get("patch") or ""),
            commit_count=len(result.get("commit_messages") or []),
            report_status=report.get("status"),
            failure=result.get("failure"),
            verify=grades.get("meta"),
        )
        return {"result": result, "grades": grades}

    return await EvalAsync(
        PROJECT_NAME,
        experiment_name=experiment_name,
        data=build_cases(task_ids, trials),
        task=eval_task,
        scores=[_make_scorer(name) for name in SCORER_NAMES],
        metadata={"task_ids": list(task_ids), "trials": trials, "workspace": str(workspace)},
        max_concurrency=max_concurrency,
        timeout=timeout_s,
    )


if __name__ == "__main__":
    raise SystemExit(
        "eval_selfdriving.py is a library entrypoint, not a script: running the pipeline needs Django, "
        "Temporal, and the sandbox stack.\n"
        "Drive it from a Django shell instead, e.g.:\n"
        "  DEBUG=1 python manage.py shell\n"
        "  >>> from products.signals.eval.self_driving.eval_selfdriving import run_eval\n"
        "  >>> from products.signals.eval.self_driving.harness.runner import run_one_task\n"
        "  >>> async def run_fn(task_id, trial):\n"
        "  ...     return (await run_one_task(task_id, workspace, trial=trial)).to_json()\n"
        "  >>> await run_eval(['checkout-coupon-case'], trials=1, workspace=workspace, "
        "experiment_name='dev', run_fn=run_fn)\n"
        "(with the Temporal worker running separately under SANDBOX_REPO_MOUNT_MAP - see harness/runner.py)."
    )
