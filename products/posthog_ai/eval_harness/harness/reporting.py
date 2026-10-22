from __future__ import annotations

import os
import time
import asyncio
import traceback
from collections import Counter, defaultdict
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from posthog.dataclasses import frozen

from ..engines.types import EvalSummary
from .progress import TrialPhase, TrialProgress
from .run_report import ExperimentReport, RunReport, ScoreReport
from .transcript import write_console
from .trial_stats import ScorerTrialStats

if TYPE_CHECKING:
    from ..engines.types import CaseResult
    from .cli import HarnessOptions
    from .dashboard import EvalDashboard
    from .discovery import EvalSuite

EVAL_RESULTS_JSONL = "eval_results.jsonl"
"""Machine-readable per-experiment summary export, opt-in via ``EXPORT_EVAL_RESULTS``."""

CaseStatus = Literal["ok", "timeout", "error"]


def _emit(text: str) -> None:
    write_console(text + "\n")


@dataclass
class SuiteRunResult:
    """Outcome of one suite function, assembled by the orchestrator."""

    suite_id: str
    status: Literal["passed", "crashed"]
    error: BaseException | None = None
    duration_seconds: float = 0.0


CasePhase = Literal["queued", "setup", "agent", "cleanup", "logs", "scoring"]


@frozen(frozen=False)
class _CaseProgress:
    experiment: str
    name: str
    trial_index: int
    started: float
    phase_started: float
    phase: CasePhase = "queued"
    status: CaseStatus = "ok"
    durations: dict[str, float] = field(default_factory=dict)

    def transition(self, phase: CasePhase) -> None:
        now = time.monotonic()
        self.durations[self.phase] = self.durations.get(self.phase, 0.0) + now - self.phase_started
        self.phase = phase
        self.phase_started = now

    def label(self) -> str:
        return f"{self.experiment} :: {self.name} [trial {self.trial_index + 1}]"


class ProgressReporter:
    """Serializes harness output and renders the stable final summary."""

    def __init__(
        self,
        total_suites: int,
        *,
        verbose: bool = False,
        dashboard: EvalDashboard | None = None,
        revision: str | None = None,
        worktree_dirty: bool | None = None,
    ) -> None:
        self._revision = revision
        self._worktree_dirty = worktree_dirty
        self._total_suites = total_suites
        self._verbose = verbose
        self._lock = asyncio.Lock()
        self._finished_suites = 0
        self._summaries: dict[str, EvalSummary] = {}
        self._case_counts: dict[str, int] = defaultdict(int)
        self._setup_retry_count = 0
        self._case_durations: dict[str, float] = defaultdict(float)
        self._case_statuses: dict[str, Counter[str]] = defaultdict(Counter)
        self._summary_error_counts: dict[str, int] = defaultdict(int)
        self._trial_stats: dict[str, Sequence[ScorerTrialStats]] = {}
        self._experiment_totals: dict[str, int] = {}
        self._case_selections: dict[str, dict[str, int]] = {}
        self._scored_trial_counts: dict[str, Counter[str]] = {}
        self._scorer_names: dict[str, frozenset[str]] = {}
        self._posthog_urls: dict[str, str] = {}
        self._posthog_offline_statuses: dict[str, str] = {}
        self._log_dirs: dict[str, Path] = {}
        self._active_cases: dict[str, _CaseProgress] = {}
        self._started = time.monotonic()
        self._dashboard = dashboard

    def _publish_trial(
        self, trial_id: str, case: _CaseProgress, *, phase: TrialPhase | None = None, detail: str = ""
    ) -> None:
        if self._dashboard is not None:
            self._dashboard.update_trial(
                TrialProgress(
                    trial_id=trial_id,
                    experiment=case.experiment,
                    name=case.name,
                    trial_index=case.trial_index,
                    phase=phase or case.phase,
                    started=case.started,
                    ended=time.monotonic() if phase in {"done", "error", "timeout", "canceled"} else None,
                    log_dir=self._log_dirs.get(case.experiment),
                    detail=detail,
                )
            )

    @asynccontextmanager
    async def live_updates(self) -> AsyncIterator[None]:
        async def update() -> None:
            while True:
                await asyncio.sleep(30)
                await self.report_progress()

        task = asyncio.create_task(update())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def report_progress(self) -> None:
        async with self._lock:
            counts: Counter[str] = Counter(case.phase for case in self._active_cases.values())
            total = sum(self._experiment_totals.values())
            finished = sum(self._case_counts.values())
            states = ", ".join(
                f"{phase}={counts[phase]}" for phase in ("queued", "setup", "agent", "cleanup", "logs", "scoring")
            )
            lines = [
                f"PROGRESS  executions {finished}/{total}; elapsed {_format_duration(time.monotonic() - self._started)}",
                f"  {states}",
            ]
            if self._active_cases:
                oldest = min(self._active_cases.values(), key=lambda case: case.started)
                lines.append(
                    f"  oldest: {oldest.label()} ({oldest.phase}, {_format_duration(time.monotonic() - oldest.phase_started)})"
                )
            await asyncio.to_thread(_emit, "\n".join(lines))

    async def case_started(self, experiment: str, name: str, trial_id: str, trial_index: int) -> dict[str, float]:
        async with self._lock:
            now = time.monotonic()
            case = _CaseProgress(
                experiment=experiment, name=name, trial_index=trial_index, started=now, phase_started=now
            )
            self._active_cases[trial_id] = case
            self._publish_trial(trial_id, case)
            await asyncio.to_thread(_emit, f"CASE START  {case.label()}  queued; id={trial_id}")
            return case.durations

    async def case_phase(self, trial_id: str, phase: CasePhase) -> None:
        async with self._lock:
            case = self._active_cases.get(trial_id)
            if case is None or case.phase == phase:
                return
            case.transition(phase)
            self._publish_trial(trial_id, case)
            await asyncio.to_thread(_emit, f"CASE PHASE  {case.label()}  {phase}")

    async def case_scored(self, trial_id: str, *, error: str | None = None) -> None:
        async with self._lock:
            case = self._active_cases.pop(trial_id, None)
            if case is None:
                return
            case.transition(case.phase)
            if error is not None:
                self._case_statuses[case.experiment][case.status] -= 1
                self._case_statuses[case.experiment]["error"] += 1
            marker = (
                "ERROR" if error is not None else {"ok": "DONE", "timeout": "TIMEOUT", "error": "ERROR"}[case.status]
            )
            phase: TrialPhase = "done"
            if error is not None or case.status == "error":
                phase = "error"
            elif case.status == "timeout":
                phase = "timeout"
            self._publish_trial(trial_id, case, phase=phase, detail=error or "")
            await asyncio.to_thread(_emit, f"CASE {marker:<7} {case.label()}  results ready")

    async def finish_cases(self, trial_ids: Sequence[str]) -> None:
        async with self._lock:
            for trial_id in trial_ids:
                case = self._active_cases.pop(trial_id, None)
                if case is not None:
                    case.transition(case.phase)
                    self._publish_trial(trial_id, case, phase="canceled")

    async def finish_experiment(self, experiment: str) -> None:
        await self.finish_cases(
            [trial_id for trial_id, case in self._active_cases.items() if case.experiment == experiment]
        )

    def setup_started(self, phase: str) -> None:
        if self._dashboard:
            self._dashboard.setup_started(phase)
        _emit(f"SETUP START  {phase}")

    def print_run_header(
        self,
        *,
        provider: str,
        agent_runtime: str,
        agent_model: str,
        max_sandboxes: int,
        trials: int,
        case_timeout_seconds: int,
    ) -> None:
        if self._dashboard:
            self._dashboard.configure(
                f"{provider} | {agent_runtime} / {agent_model} | {max_sandboxes} sandboxes | {trials} trials per case"
            )
        lines = [
            "Sandboxed eval run",
            f"Suites: {self._total_suites}",
            f"Provider: {provider}",
            f"Agent: {agent_runtime} / {agent_model}",
            f"Sandbox concurrency: {max_sandboxes}",
            f"Trials per case: {trials}",
            f"Case timeout: {case_timeout_seconds}s",
            "Execution completion does not include scoring. The experiment ends when results are ready.",
            "Use --verbose for detailed console logs. The transcript always keeps detailed logs.",
            "",
        ]
        _emit("\n".join(lines))

    async def suite_started(self, suite_id: str) -> None:
        async with self._lock:
            await asyncio.to_thread(_emit, f"SUITE START  {suite_id}")

    async def experiment_started(
        self, experiment_name: str, planned_cases: int, log_dir: Path, *, case_names: Sequence[str] = ()
    ) -> None:
        async with self._lock:
            self._experiment_totals[experiment_name] = planned_cases
            self._case_selections[experiment_name] = dict(Counter(case_names))
            self._log_dirs[experiment_name] = log_dir
            if self._dashboard:
                self._dashboard.experiment_started(experiment_name, planned_cases)
            await asyncio.to_thread(_emit, f"EXPERIMENT START  {experiment_name}  [{planned_cases} cases]")

    async def case_done(
        self,
        experiment_name: str,
        case_name: str,
        *,
        duration_seconds: float,
        status: CaseStatus = "ok",
        trial_id: str | None = None,
        error_type: str | None = None,
        error_detail: str | None = None,
    ) -> None:
        async with self._lock:
            self._case_counts[experiment_name] += 1
            self._case_durations[experiment_name] += duration_seconds
            self._case_statuses[experiment_name][status] += 1
            marker = {"ok": "DONE", "timeout": "TIMEOUT", "error": "ERROR"}[status]
            detail = ""
            case = self._active_cases.get(trial_id) if trial_id else None
            if case is not None and trial_id is not None:
                case_name = f"{case_name} [trial {case.trial_index + 1}]"
                case.status = status
                if status == "error":
                    detail = f"; {error_type or 'infrastructure error'}; last phase={case.phase}; id={trial_id}. Inspect the full run transcript and {self._log_dirs.get(experiment_name, 'agent logs')}."
                    case.transition(case.phase)
                    self._active_cases.pop(trial_id, None)
                else:
                    marker = "READY" if status == "ok" else "TIMEOUT"
                    detail = "; execution complete; scoring pending"
                    case.transition("scoring")
                self._publish_trial(
                    trial_id,
                    case,
                    phase="error" if status == "error" else None,
                    detail=error_detail or detail.removeprefix("; "),
                )
            total = self._experiment_totals.get(experiment_name)
            progress = f"[{self._case_counts[experiment_name]}/{total}]" if total is not None else ""
            await asyncio.to_thread(
                _emit,
                f"CASE {marker:<7} {experiment_name} :: {case_name}  {progress}  {_format_duration(duration_seconds)}{detail}",
            )

    async def case_setup_retry(
        self,
        experiment_name: str,
        case_name: str,
        *,
        next_attempt: int,
        total_attempts: int,
        delay_seconds: float,
        error_type: str,
        trial_id: str | None = None,
    ) -> None:
        async with self._lock:
            self._setup_retry_count += 1
            if self._dashboard and trial_id:
                self._dashboard.trial_retry(
                    trial_id,
                    f"Setup attempt {next_attempt}/{total_attempts} in {delay_seconds:.1f}s ({error_type}). No action required.",
                )
            await asyncio.to_thread(
                _emit,
                f"CASE RETRY   {experiment_name} :: {case_name}  setup attempt {next_attempt}/{total_attempts} "
                f"in {delay_seconds:.1f}s ({error_type}). No action required.",
            )

    async def suite_finished(self, result: SuiteRunResult) -> None:
        async with self._lock:
            self._finished_suites += 1
            marker = "DONE" if result.status == "passed" else "CRASH"
            await asyncio.to_thread(
                _emit,
                f"SUITE {marker:<5} {result.suite_id}  "
                f"[{self._finished_suites}/{self._total_suites} suites]  "
                f"{_format_duration(result.duration_seconds)}",
            )

    @staticmethod
    def _append_summary(summary: EvalSummary) -> None:
        with open(EVAL_RESULTS_JSONL, "a", encoding="utf-8") as f:
            f.write(summary.as_json() + "\n")

    async def record_summary(
        self,
        experiment_name: str,
        summary: EvalSummary,
        *,
        error_count: int = 0,
        trial_stats: Sequence[ScorerTrialStats] = (),
        case_results: Sequence[CaseResult] = (),
    ) -> None:
        async with self._lock:
            self._summaries[experiment_name] = summary
            self._trial_stats[experiment_name] = trial_stats
            self._summary_error_counts[experiment_name] = error_count
            # The offline summary drops a scorer that skipped every trial, so keep the names the trials reported.
            self._scorer_names[experiment_name] = frozenset(summary.scores).union(
                *(result.scores for result in case_results)
            )
            self._scored_trial_counts[experiment_name] = Counter(
                name
                for result in case_results
                if result.error is None or result.error_kind == "scorer"
                for name, score in result.scores.items()
                if score is not None
            )
            if os.getenv("EXPORT_EVAL_RESULTS"):
                await asyncio.to_thread(self._append_summary, summary)
            total = self._experiment_totals.get(experiment_name)
            progress = f"[{self._case_counts[experiment_name]}/{total} cases]" if total is not None else ""
            await asyncio.to_thread(_emit, f"EXPERIMENT DONE  {experiment_name}  {progress}")

    def write_run_report(
        self, options: HarnessOptions, suites: Sequence[EvalSuite], *, exit_code: int, duration_seconds: float
    ) -> None:
        if options.results_file is None:
            return
        experiments: dict[str, ExperimentReport] = {}
        for name, planned in self._experiment_totals.items():
            summary = self._summaries.get(name)
            experiments[name] = ExperimentReport(
                cases=self._case_selections[name],
                planned_trials=planned,
                completed_trials=self._case_counts[name],
                errors=max(self._case_statuses[name]["error"], self._summary_error_counts[name]),
                timeouts=self._case_statuses[name]["timeout"],
                scores={
                    key: ScoreReport(
                        mean=summary.scores[key].score if key in summary.scores else None,
                        scored_trials=self._scored_trial_counts[name][key],
                    )
                    for key in sorted(self._scorer_names[name])
                }
                if summary is not None
                else {},
                log_dir=str(self._log_dirs[name].resolve()),
            )
        report = RunReport(
            runtime=options.agent_runtime,
            model=options.agent_model,
            reasoning_effort=options.reasoning_effort,
            provider=options.provider,
            trials=options.trials,
            suite_ids=[suite.id for suite in suites],
            suite_kinds=sorted({suite.kind.value for suite in suites}),
            exit_code=exit_code,
            duration_seconds=duration_seconds,
            experiments=experiments,
            revision=self._revision,
            worktree_dirty=self._worktree_dirty,
        )
        options.results_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = options.results_file.with_suffix(".tmp")
        temporary.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
        temporary.replace(options.results_file)

    async def record_posthog_offline_result(self, experiment_name: str, status: str, *, url: str | None = None) -> None:
        async with self._lock:
            self._posthog_offline_statuses[experiment_name] = status
            if url is not None:
                self._posthog_urls[experiment_name] = url
            await asyncio.to_thread(_emit, f"POSTHOG OFFLINE  {experiment_name}  {url or status}")

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
            f"Case setup retries: {self._setup_retry_count}",
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

    def has_case_errors(self) -> bool:
        return self._combined_case_statuses()["error"] > 0

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
        stats_by_scorer = {stats.name: stats for stats in self._trial_stats.get(experiment_name, ())}
        scores = [(score.name, score.score) for score in summary.scores.values() if score.score is not None]
        if scores:
            lines.append("  Scores:")
            for name, score in scores:
                lines.extend(_score_lines(name, score, stats_by_scorer.get(name)))
        else:
            lines.append("  Scores: none")

        posthog_url = self._posthog_urls.get(experiment_name)
        if posthog_url:
            lines.append(f"  PostHog: {posthog_url}")
        if (offline_status := self._posthog_offline_statuses.get(experiment_name)) and offline_status != "uploaded":
            lines.append(f"  PostHog offline: {offline_status}")
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
                if self._verbose:
                    lines.append("".join(traceback.format_exception(result.error)).rstrip())
                else:
                    lines.append(
                        f"{type(result.error).__name__}: {str(result.error).splitlines()[0] if str(result.error) else '(no message)'}"
                    )
                    lines.append("Inspect the full run transcript for the traceback.")
            else:
                lines.append("(no traceback captured)")
        return lines


def _score_lines(name: str, score: float, stats: ScorerTrialStats | None) -> list[str]:
    if stats is None:
        return [f"    {name}: {score * 100:.1f}%"]
    interval = ""
    if stats.ci_low is not None and stats.ci_high is not None:
        interval = f" (95% CI {stats.ci_low * 100:.1f}-{stats.ci_high * 100:.1f}%)"
    lines = [f"    {name}: {score * 100:.1f}%{interval}"]
    if stats.trials > 1:
        k = stats.trials
        shortfall = f" | {stats.short_cases} cases short of {k} trials" if stats.short_cases else ""
        lines.append(
            f"      pass^{k} {_percent(stats.pass_all)} | pass@{k} {_percent(stats.pass_any)} "
            f"| {stats.flaky_cases}/{stats.complete_cases} cases flaky{shortfall}"
        )
    return lines


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, remaining = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)}m {remaining:.1f}s"
    hours, minutes = divmod(int(minutes), 60)
    return f"{hours}h {minutes}m {remaining:.1f}s"
