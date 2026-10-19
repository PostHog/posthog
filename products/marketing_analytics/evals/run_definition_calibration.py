"""Calibrate the definition judge against fixed synthetic answers.

The default dry run writes a pending report without calling a provider. Live runs
require --live, OPENAI_API_KEY, and an explicit OPENAI_BASE_URL for that key.
Labels stay local. This measures judge agreement, not generation quality.
"""

from __future__ import annotations

import os
import sys
import json
import socket
import asyncio
import hashlib
import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from unittest.mock import patch

from openai import AsyncOpenAI

from posthog.dataclasses import frozen

from products.marketing_analytics.evals.report_writer import write_report_checkpoint

if TYPE_CHECKING:
    from products.posthog_ai.eval_harness.config import BaseEvalCase
    from products.posthog_ai.eval_harness.scorers.contract import Score

MIN_ACCURACY = 0.9
MAX_FALSE_POSITIVE_RATE = 0.05
MAX_FALSE_NEGATIVE_RATE = 0.1


class CalibrationJudge(Protocol):
    async def eval_async(self, output: dict[str, object], expected: dict[str, object]) -> Score: ...


@frozen
class CalibrationJudgment:
    case_name: str
    error_class: str
    gold_pass: bool
    actual_pass: bool | None
    metadata: dict[str, object]
    error: str | None = None


@frozen
class _JudgeInputs:
    output: dict[str, object]
    expected: dict[str, object]


def source_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parents[3]
    paths = [
        Path(__file__).resolve(),
        Path(__file__).with_name("definition_calibration_cases.py"),
        Path(__file__).with_name("definition_evidence.py"),
        Path(__file__).with_name("definition_judge_transport.py"),
        Path(__file__).with_name("report_writer.py"),
        root / "products/posthog_ai/eval_harness/scorers/judged.py",
        root / "products/posthog_ai/eval_harness/scorers/tracing.py",
    ]
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def confusion_matrix(judgments: Sequence[CalibrationJudgment]) -> dict[str, int | float | None]:
    tp = sum(item.gold_pass and item.actual_pass is True for item in judgments)
    tn = sum(not item.gold_pass and item.actual_pass is False for item in judgments)
    fp = sum(not item.gold_pass and item.actual_pass is True for item in judgments)
    fn = sum(item.gold_pass and item.actual_pass is False for item in judgments)
    measured = tp + tn + fp + fn
    return {
        "true_positive": tp,
        "true_negative": tn,
        "false_positive": fp,
        "false_negative": fn,
        "measured": measured,
        "errors": sum(item.actual_pass is None for item in judgments),
        "accuracy": (tp + tn) / measured if measured else None,
        "false_positive_rate": fp / (fp + tn) if fp + tn else None,
        "false_negative_rate": fn / (fn + tp) if fn + tp else None,
    }


def calibration_summary(
    judgments: Sequence[CalibrationJudgment], *, planned: int, sources_unchanged: bool
) -> dict[str, object]:
    matrix = confusion_matrix(judgments)
    accuracy = matrix["accuracy"]
    false_positive_rate = matrix["false_positive_rate"]
    false_negative_rate = matrix["false_negative_rate"]
    complete = len(judgments) == planned and matrix["measured"] == planned
    passed = (
        complete
        and sources_unchanged
        and isinstance(accuracy, float)
        and accuracy > MIN_ACCURACY
        and isinstance(false_positive_rate, float)
        and false_positive_rate <= MAX_FALSE_POSITIVE_RATE
        and isinstance(false_negative_rate, float)
        and false_negative_rate <= MAX_FALSE_NEGATIVE_RATE
    )
    return {
        "complete": complete,
        "sources_unchanged": sources_unchanged,
        "calibration_passed": passed,
        "confusion_matrix": matrix,
        "by_error_class": {
            error_class: confusion_matrix([item for item in judgments if item.error_class == error_class])
            for error_class in sorted({item.error_class for item in judgments})
        },
    }


def _case_inputs(case: BaseEvalCase) -> _JudgeInputs:
    answer = case.metadata.get("answer")
    gold_pass = case.metadata.get("gold_pass")
    error_class = case.metadata.get("error_class")
    criterion = case.expected.get("conversion_definition_evidence", {}).get("criterion")
    if not all(isinstance(value, str) and value.strip() for value in (case.prompt, answer, criterion, error_class)):
        raise ValueError("Calibration fixtures require nonempty audit, answer, criterion, and error class")
    if not isinstance(gold_pass, bool):
        raise ValueError("Calibration fixtures require a boolean gold label")
    return _JudgeInputs(
        output={"prompt": case.prompt, "last_message": answer, "exit_code": 0, "stop_reason": "end_turn"},
        expected={"conversion_definition_evidence": {"criterion": criterion}},
    )


def _write_report(path: Path, report: dict[str, object]) -> None:
    write_report_checkpoint(path, json.dumps(report, indent=2, ensure_ascii=False) + "\n")


async def run_calibration(
    cases: Sequence[BaseEvalCase],
    *,
    judge: CalibrationJudge | None,
    report_path: Path,
    judge_model: str,
    judge_version: str,
    trials: int = 1,
) -> dict[str, object]:
    if not cases or len({case.name for case in cases}) != len(cases):
        raise ValueError("Calibration requires nonempty cases with unique names")
    if not 1 <= trials <= 5:
        raise ValueError("Calibration requires between one and five trials")
    for case in cases:
        _case_inputs(case)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("x"):
        pass
    frozen_sources = source_hashes()
    report: dict[str, object] = {
        "status": "pending_real_calibration" if judge is None else "running",
        "mode": "dry_run" if judge is None else "live",
        "judge_model": judge_model,
        "judge_version": judge_version,
        "planned_trials": len(cases) * trials,
        "repetitions": trials,
        "completed_trials": 0,
        "calibration_passed": None,
        "confusion_matrix": None,
        "by_error_class": {},
        "source_sha256": frozen_sources,
        "fixtures_sha256": hashlib.sha256(
            json.dumps([case.model_dump(mode="json") for case in cases], sort_keys=True).encode()
        ).hexdigest(),
        "gate": {
            "all_planned_trials": True,
            "no_judge_errors": True,
            "sources_unchanged": True,
            "accuracy_strictly_above": MIN_ACCURACY,
            "false_positive_rate_at_most": MAX_FALSE_POSITIVE_RATE,
            "false_negative_rate_at_most": MAX_FALSE_NEGATIVE_RATE,
        },
        "limitations": [
            "Agent-authored labels are reference judgments, not a calibrated human benchmark.",
            "These fixtures measure evaluator agreement, not generator or production workflow quality.",
            "Error-class pairs are diagnostic examples, not a representative production sample.",
        ],
        "trials": [],
    }
    _write_report(report_path, report)
    if judge is None:
        return report
    judgments: list[CalibrationJudgment] = []
    records: list[dict[str, object]] = []
    report["trials"] = records
    for trial_index, case in ((index, case) for index in range(trials) for case in cases):
        metadata: dict[str, object] = {}
        actual_pass: bool | None = None
        error: str | None = None
        try:
            if source_hashes() != frozen_sources:
                raise RuntimeError("Calibration sources changed after the report was frozen")
            inputs = _case_inputs(case)
            score = await judge.eval_async(inputs.output, inputs.expected)
            metadata = dict(score.metadata or {})
            if "reason" in metadata or score.score not in (0.0, 1.0):
                raise RuntimeError(str(metadata.get("reason", "Judge did not return a binary verdict")))
            actual_pass = score.score == 1.0
        except Exception as exc:
            error = str(exc)
        judgment = CalibrationJudgment(
            case_name=case.name,
            error_class=case.metadata["error_class"],
            gold_pass=case.metadata["gold_pass"],
            actual_pass=actual_pass,
            metadata=metadata,
            error=error,
        )
        judgments.append(judgment)
        records.append(
            {
                "case": judgment.case_name,
                "trial_index": trial_index,
                "trial_id": f"{case.name}:trial-{trial_index + 1}",
                "error_class": judgment.error_class,
                "gold_pass": judgment.gold_pass,
                "gold_failed_checks": case.metadata["gold_failed_checks"],
                "actual_pass": judgment.actual_pass,
                "metadata": judgment.metadata,
                "error": judgment.error,
            }
        )
        report["completed_trials"] = len(judgments)
        report.update(
            calibration_summary(
                judgments, planned=len(cases) * trials, sources_unchanged=source_hashes() == frozen_sources
            )
        )
        report["status"] = "judge_error" if error is not None else "running"
        _write_report(report_path, report)
        if error is not None:
            return report
    report["status"] = "passed" if report["calibration_passed"] else "failed"
    _write_report(report_path, report)
    return report


async def _run_live(cases: Sequence[BaseEvalCase], report_path: Path, *, trials: int) -> dict[str, object]:
    from products.marketing_analytics.evals.definition_evidence import (  # noqa: PLC0415 — Django must initialize before scorer imports
        DEFINITION_JUDGE_VERSION,
        ConversionDefinitionEvidence,
    )
    from products.posthog_ai.eval_harness.scorers import (
        JUDGE_MODEL,  # noqa: PLC0415 — Django must initialize before scorer imports
    )

    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL")
    if not api_key or not base_url:
        raise ValueError("Live calibration requires OPENAI_API_KEY and explicit OPENAI_BASE_URL for that key")
    async with AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=0, timeout=60.0) as client:
        return await run_calibration(
            cases,
            judge=ConversionDefinitionEvidence(client=client),
            report_path=report_path,
            judge_model=JUDGE_MODEL,
            judge_version=DEFINITION_JUDGE_VERSION,
            trials=trials,
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Call the configured judge provider; incurs charges")
    parser.add_argument("--trials", type=int, choices=range(1, 6), default=1, help="Repetitions per fixed answer")
    parser.add_argument("--output", type=Path, required=True, help="New local report.json file; refuses to overwrite")
    args = parser.parse_args(argv)
    os.environ["OPT_OUT_CAPTURE"] = "true"
    from django.db.backends.base.base import BaseDatabaseWrapper  # noqa: PLC0415 — CLI-only database guard

    from products.posthog_ai.eval_harness.harness.django_env import (
        setup_django,  # noqa: PLC0415 — defer framework startup to CLI
    )

    with patch.object(
        BaseDatabaseWrapper, "ensure_connection", side_effect=RuntimeError("Database access is forbidden")
    ):
        with patch.object(socket.socket, "connect", side_effect=RuntimeError("Network is forbidden during startup")):
            setup_django()
            from products.marketing_analytics.evals.definition_calibration_cases import (  # noqa: PLC0415 — BaseEvalCase requires initialized Django
                definition_calibration_cases,
            )
            from products.marketing_analytics.evals.definition_evidence import (  # noqa: PLC0415 — scorer imports require initialized Django
                DEFINITION_JUDGE_VERSION,
            )
            from products.posthog_ai.eval_harness.scorers import (
                JUDGE_MODEL,  # noqa: PLC0415 — scorer imports require initialized Django
            )

            cases = definition_calibration_cases()
        if args.live:
            report = asyncio.run(_run_live(cases, args.output, trials=args.trials))
        else:
            with patch.object(socket.socket, "connect", side_effect=RuntimeError("Network is forbidden in dry runs")):
                report = asyncio.run(
                    run_calibration(
                        cases,
                        judge=None,
                        report_path=args.output,
                        judge_model=JUDGE_MODEL,
                        judge_version=DEFINITION_JUDGE_VERSION,
                        trials=args.trials,
                    )
                )
    sys.stdout.write(f"{report['status']}: {args.output}\n")
    return 0 if not args.live or report["calibration_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
