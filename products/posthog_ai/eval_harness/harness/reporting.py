from __future__ import annotations

import os
import asyncio
import traceback
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..engines.types import EvalSummary

EVAL_RESULTS_JSONL = "eval_results.jsonl"
"""Machine-readable per-experiment summary export, opt-in via ``EXPORT_EVAL_RESULTS``."""

POSTHOG_EVALUATIONS_URL = (
    "https://us.posthog.com/project/2/ai-evals/evaluations/offline/experiments/{experiment_id}?offline_date_from=-1d"
)

CaseStatus = Literal["ok", "timeout", "error"]


def _emit(text: str) -> None:
    print(text)  # noqa: T201 — this module is the single owner of harness terminal output


@dataclass
class SuiteRunResult:
    """Outcome of one suite function, assembled by the orchestrator."""

    suite_id: str
    status: Literal["passed", "crashed"]
    error: BaseException | None = None
    duration_seconds: float = 0.0


class ProgressReporter:
    """Serializes harness output and renders the stable final summary."""

    def __init__(self, total_suites: int) -> None:
        self._total_suites = total_suites
        self._lock = asyncio.Lock()
        self._finished_suites = 0
        self._summaries: dict[str, EvalSummary] = {}
        self._case_counts: dict[str, int] = defaultdict(int)
        self._case_durations: dict[str, float] = defaultdict(float)
        self._case_statuses: dict[str, Counter[str]] = defaultdict(Counter)
        self._summary_error_counts: dict[str, int] = defaultdict(int)
        self._experiment_totals: dict[str, int] = {}
        self._posthog_urls: dict[str, str] = {}
        self._log_dirs: dict[str, Path] = {}

    def print_run_header(
        self,
        *,
        provider: str,
        agent_runtime: str,
        agent_model: str,
        max_sandboxes: int,
        trials: int,
    ) -> None:
        lines = [
            "Sandboxed eval run",
            f"Suites: {self._total_suites}",
            f"Provider: {provider}",
            f"Agent: {agent_runtime} / {agent_model}",
            f"Sandbox concurrency: {max_sandboxes}",
            f"Trials per case: {trials}",
            "",
        ]
        _emit("\n".join(lines))

    async def suite_started(self, suite_id: str) -> None:
        async with self._lock:
            _emit(f"SUITE START  {suite_id}")

    async def experiment_started(self, experiment_name: str, planned_cases: int, log_dir: Path) -> None:
        async with self._lock:
            self._experiment_totals[experiment_name] = planned_cases
            self._log_dirs[experiment_name] = log_dir
            _emit(f"EXPERIMENT START  {experiment_name}  [{planned_cases} cases]")

    async def case_done(
        self,
        experiment_name: str,
        case_name: str,
        *,
        duration_seconds: float,
        status: CaseStatus = "ok",
    ) -> None:
        async with self._lock:
            self._case_counts[experiment_name] += 1
            self._case_durations[experiment_name] += duration_seconds
            self._case_statuses[experiment_name][status] += 1
            marker = {"ok": "DONE", "timeout": "TIMEOUT", "error": "ERROR"}[status]
            total = self._experiment_totals.get(experiment_name)
            progress = f"[{self._case_counts[experiment_name]}/{total}]" if total is not None else ""
            _emit(
                f"CASE {marker:<7} {experiment_name} :: {case_name}  {progress}  {_format_duration(duration_seconds)}"
            )

    async def suite_finished(self, result: SuiteRunResult) -> None:
        async with self._lock:
            self._finished_suites += 1
            marker = "DONE" if result.status == "passed" else "CRASH"
            _emit(
                f"SUITE {marker:<5} {result.suite_id}  "
                f"[{self._finished_suites}/{self._total_suites} suites]  "
                f"{_format_duration(result.duration_seconds)}"
            )

    async def record_summary(self, experiment_name: str, summary: EvalSummary, *, error_count: int = 0) -> None:
        async with self._lock:
            self._summaries[experiment_name] = summary
            self._summary_error_counts[experiment_name] = error_count
            if os.getenv("EXPORT_EVAL_RESULTS"):
                with open(EVAL_RESULTS_JSONL, "a", encoding="utf-8") as f:
                    f.write(summary.as_json() + "\n")
            total = self._experiment_totals.get(experiment_name)
            progress = f"[{self._case_counts[experiment_name]}/{total} cases]" if total is not None else ""
            _emit(f"EXPERIMENT DONE  {experiment_name}  {progress}")

    async def record_posthog_evaluations_url(self, experiment_name: str, experiment_id: str) -> None:
        async with self._lock:
            self._posthog_urls[experiment_name] = POSTHOG_EVALUATIONS_URL.format(experiment_id=experiment_id)

    def print_final_summary(
        self,
        results: Sequence[SuiteRunResult],
        *,
        exit_code: int,
        fail_under: float | None,
        duration_seconds: float,
    ) -> None:
        crashed = sorted(
            (result for result in results if result.status == "crashed"), key=lambda result: result.suite_id
        )
        case_statuses = self._combined_case_statuses()
        lines = [
            "",
            "Sandboxed eval summary",
            "----------------------",
            f"Status: {'PASS' if exit_code == 0 else 'FAIL'}",
            f"Suites: {len(results) - len(crashed)} done, {len(crashed)} crashed",
            (
                f"Cases: {case_statuses['ok']} done, {case_statuses['timeout']} timed out, "
                f"{case_statuses['error']} errors"
            ),
            f"Mean score: {self._mean_score_text()}",
            f"Score gate: {self._score_gate_text(fail_under)}",
            f"Duration: {_format_duration(duration_seconds)}",
        ]

        for experiment_name in sorted(self._summaries):
            lines.extend(self._experiment_block(experiment_name, self._summaries[experiment_name]))

        if not self._summaries and not crashed:
            lines.extend(["", "No experiments ran."])

        lines.extend(self._crash_block(crashed))
        _emit("\n".join(lines))

    def print_incomplete_summary(self, *, status: str, duration_seconds: float) -> None:
        _emit(
            "\n".join(
                [
                    "",
                    "Sandboxed eval summary",
                    "----------------------",
                    f"Status: {status}",
                    f"Duration: {_format_duration(duration_seconds)}",
                ]
            )
        )

    def mean_score(self) -> float | None:
        scores = [
            score.score
            for summary in self._summaries.values()
            for score in summary.scores.values()
            if score.score is not None
        ]
        if not scores:
            return None
        return sum(scores) / len(scores)

    def _combined_case_statuses(self) -> Counter[str]:
        combined: Counter[str] = Counter()
        experiment_names = self._case_statuses.keys() | self._summary_error_counts.keys()
        for experiment_name in experiment_names:
            statuses = self._case_statuses[experiment_name]
            combined["ok"] += statuses["ok"]
            combined["timeout"] += statuses["timeout"]
            combined["error"] += max(statuses["error"], self._summary_error_counts[experiment_name])
        return combined

    def _experiment_block(self, experiment_name: str, summary: EvalSummary) -> list[str]:
        statuses = self._case_statuses[experiment_name]
        error_count = max(statuses["error"], self._summary_error_counts[experiment_name])
        lines = [
            "",
            f"Experiment: {experiment_name}",
            (f"  Cases: {statuses['ok']} done, {statuses['timeout']} timed out, {error_count} errors"),
            f"  Case time: {_format_duration(self._case_durations[experiment_name])}",
        ]
        scores = [(score.name, score.score) for score in summary.scores.values() if score.score is not None]
        if scores:
            lines.append("  Scores:")
            lines.extend(f"    {name}: {score * 100:.1f}%" for name, score in scores)
        else:
            lines.append("  Scores: none")

        posthog_url = self._posthog_urls.get(experiment_name)
        if posthog_url:
            lines.append(f"  PostHog: {posthog_url}")
        lines.append(f"  {summary.engine_name.title()}: {summary.experiment_url or '(local run, not uploaded)'}")
        log_dir = self._log_dirs.get(experiment_name)
        if log_dir:
            lines.append(f"  Agent logs: {log_dir}")
        return lines

    def _mean_score_text(self) -> str:
        mean = self.mean_score()
        return f"{mean * 100:.1f}%" if mean is not None else "n/a"

    def _score_gate_text(self, fail_under: float | None) -> str:
        if fail_under is None:
            return "not configured"
        mean = self.mean_score()
        target = fail_under * 100
        if mean is None:
            return f"not met (no scores; required {target:.1f}%)"
        comparison = ">=" if mean >= fail_under else "<"
        status = "met" if mean >= fail_under else "not met"
        return f"{status} ({mean * 100:.1f}% {comparison} {target:.1f}%)"

    def _crash_block(self, crashed: Sequence[SuiteRunResult]) -> list[str]:
        if not crashed:
            return []
        lines = ["", "Crashed suites", "---------------"]
        for result in crashed:
            lines.append(f"Suite: {result.suite_id}")
            lines.append(f"Duration: {_format_duration(result.duration_seconds)}")
            if result.error is not None:
                lines.append("".join(traceback.format_exception(result.error)).rstrip())
            else:
                lines.append("(no traceback captured)")
        return lines


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, remaining = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)}m {remaining:.1f}s"
    hours, minutes = divmod(int(minutes), 60)
    return f"{hours}h {minutes}m {remaining:.1f}s"
