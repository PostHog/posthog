from __future__ import annotations

import sys
import json
import time
import signal
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, ValidationError

from ..log_sink import LOGS_ROOT
from .cli import HarnessOptions, ModelTarget
from .run_report import RunReport
from .transcript import write_console


class ModelRun(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    runtime: str
    model: str
    exit_code: int | None = None
    wall_time_seconds: float = 0
    report: RunReport | None = None
    issue: str | None = None


class ModelComparison:
    def __init__(self, options: HarnessOptions) -> None:
        self.options = options
        self.directory = (
            options.comparison_dir or LOGS_ROOT / "comparisons" / f"{datetime.now(UTC):%Y%m%d-%H%M%S}_{uuid4().hex[:8]}"
        ).resolve()
        self.runs = [ModelRun(runtime=target.runtime, model=target.model) for target in options.comparison_models]
        self.issues: list[str] = []

    def _command(self, target: ModelTarget, path: Path, *, check: bool) -> list[str]:
        options = self.options
        command = [
            sys.executable,
            "-m",
            "products.posthog_ai.eval_harness.harness",
            *options.selectors,
            "--agent-runtime",
            target.runtime,
            "--agent-model",
            target.model,
            "--provider",
            options.provider,
            "--skill-delivery",
            options.skill_delivery,
            "--trials",
            str(options.trials),
            "--max-sandboxes",
            str(options.max_sandboxes),
            "--case-timeout",
            str(options.per_case_timeout_seconds),
            "--infra-retries",
            str(options.infrastructure_retries),
            "--results-file",
            str(path),
            "--no-tui",
        ]
        for flag, value in (
            ("--eval", options.case_filter),
            ("--reasoning-effort", options.reasoning_effort),
            ("--fail-under", options.fail_under),
        ):
            if value is not None:
                command.extend([flag, str(value)])
        for flag, enabled in (
            ("--check", check),
            ("--verbose", options.verbose),
            ("--create-db", options.create_db),
            ("--keep-sandbox-containers", options.keep_sandbox_containers),
            ("--rebuild-sandbox-image", options.rebuild_sandbox_image),
        ):
            if enabled:
                command.append(flag)
        return command

    @staticmethod
    def _interrupt_on_sigterm(_signum: int, _frame: FrameType | None) -> None:
        raise KeyboardInterrupt

    @staticmethod
    def _execute(command: list[str]) -> int:
        # The child runs in its own session, so a SIGTERM sent to this process never reaches it.
        # Treat SIGTERM like Ctrl-C so the child gets SIGINT and finishes its own cleanup.
        previous_handler = signal.signal(signal.SIGTERM, ModelComparison._interrupt_on_sigterm)
        try:
            return ModelComparison._stream(command)
        finally:
            signal.signal(signal.SIGTERM, previous_handler)

    @staticmethod
    def _stream(command: list[str]) -> int:
        with subprocess.Popen(
            command,
            start_new_session=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        ) as child:
            assert child.stdout is not None
            try:
                for line in child.stdout:
                    write_console(line)
                return child.wait()
            except KeyboardInterrupt:
                child.send_signal(signal.SIGINT)
                for line in child.stdout:
                    write_console(line)
                child.wait()
                raise

    @staticmethod
    def _read_report(path: Path) -> RunReport | None:
        try:
            return RunReport.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError):
            return None

    def _validate_run(self, run: ModelRun) -> str | None:
        report = run.report
        if report is None:
            return "No valid run report; inspect the child transcript."
        if report.runtime != run.runtime or report.model != run.model or report.exit_code != run.exit_code:
            return "Run report does not match the requested model or exit status."
        if not report.experiments:
            return "No experiment results."
        if not any(
            score.mean is not None and score.scored_trials
            for experiment in report.experiments.values()
            for score in experiment.scores.values()
        ):
            return "No scored trials are available."
        for experiment in report.experiments.values():
            if not experiment.cases and not experiment.planned_trials and not experiment.completed_trials:
                continue
            if not experiment.cases or sum(experiment.cases.values()) * report.trials != experiment.planned_trials:
                return "Missing or inconsistent case selection."
            if experiment.completed_trials != experiment.planned_trials or experiment.errors or experiment.timeouts:
                return "Incomplete trial coverage, errors, or timeouts; compare scores with care."
        return None

    def _check_selection(self) -> None:
        reports = [run.report for run in self.runs if run.report and run.report.experiments]
        if len(reports) < 2:
            return
        selections = [
            (
                report.suite_ids,
                report.revision,
                report.worktree_dirty,
                {
                    name: (experiment.cases, sorted(experiment.scores))
                    for name, experiment in report.experiments.items()
                },
            )
            for report in reports
        ]
        if any(selection != selections[0] for selection in selections[1:]):
            self.issues.append("Checkout, case, or scorer selections differ. These scores are not directly comparable.")

    def _text(self) -> str:
        rows = [
            ["Metric", *(f"{run.runtime}/{run.model}" for run in self.runs)],
            ["Exit status", *(str(run.exit_code) if run.exit_code is not None else "not run" for run in self.runs)],
            [
                "Wall time",
                *(f"{run.wall_time_seconds:.1f}s" if run.exit_code is not None else "n/a" for run in self.runs),
            ],
        ]
        for metric in ("completed_trials", "errors", "timeouts"):
            values = []
            for run in self.runs:
                if run.report is None or not run.report.experiments:
                    values.append("n/a")
                    continue
                actual = sum(
                    {
                        "completed_trials": experiment.completed_trials,
                        "errors": experiment.errors,
                        "timeouts": experiment.timeouts,
                    }[metric]
                    for experiment in run.report.experiments.values()
                )
                planned = sum(experiment.planned_trials for experiment in run.report.experiments.values())
                values.append(f"{actual}/{planned}" if metric == "completed_trials" else str(actual))
            rows.append([metric.replace("_", " ").capitalize(), *values])
        rows.append(["Cost", *("unavailable" for _run in self.runs)])
        score_keys = sorted(
            {
                (name, scorer)
                for run in self.runs
                if run.report is not None
                for name, experiment in run.report.experiments.items()
                for scorer in experiment.scores
            }
        )
        for name, scorer in score_keys:
            values = []
            for run in self.runs:
                experiment = run.report.experiments.get(name) if run.report else None
                score = experiment.scores.get(scorer) if experiment else None
                values.append(
                    f"{score.mean:.1%} ({score.scored_trials}/{experiment.planned_trials} scored)"
                    if score is not None and score.mean is not None and experiment is not None
                    else "n/a"
                )
            rows.append([f"{name} / {scorer}", *values])
        widths = [max(len(row[index]) for row in rows) for index in range(len(self.runs) + 1)]
        lines = [
            "Model comparison (model + runtime)",
            *(" | ".join(value.ljust(widths[index]) for index, value in enumerate(row)).rstrip() for row in rows),
        ]
        lines.extend(f"NOTE: {issue}" for issue in self.issues)
        lines.extend(f"NOTE: {run.runtime}/{run.model}: {run.issue}" for run in self.runs if run.issue)
        return "\n".join(lines) + "\n"

    def _save(self) -> None:
        report = {
            "schema_version": 1,
            "settings": {
                "selectors": self.options.selectors,
                "case_filter": self.options.case_filter,
                "provider": self.options.provider,
                "trials": self.options.trials,
                "skill_delivery": self.options.skill_delivery,
                "reasoning_effort": self.options.reasoning_effort,
                "max_sandboxes": self.options.max_sandboxes,
                "case_timeout": self.options.per_case_timeout_seconds,
                "infrastructure_retries": self.options.infrastructure_retries,
                "fail_under": self.options.fail_under,
            },
            "issues": self.issues,
            "runs": [run.model_dump(mode="json") for run in self.runs],
        }
        temporary = self.directory / "comparison.tmp"
        temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.directory / "comparison.json")
        (self.directory / "comparison.txt").write_text(self._text(), encoding="utf-8")

    def run(self) -> int:
        self.directory.mkdir(parents=True, exist_ok=False)
        self._save()
        try:
            checked: list[RunReport] = []
            for index, target in enumerate(self.options.comparison_models):
                write_console(f"MODEL CHECK {index + 1}/{len(self.runs)}  {target.runtime}/{target.model}\n")
                path = self.directory / f"{index + 1}-check.json"
                code = self._execute(self._command(target, path, check=True))
                report = self._read_report(path)
                if code or report is None or report.suite_kinds != ["sandboxed"]:
                    self.issues.append(
                        f"{target.runtime}/{target.model}: configuration check failed or selected suites are not all sandboxed. "
                        "No model runs started. Inspect the child transcript above."
                    )
                    return 1
                checked.append(report)
            if any(report.suite_ids != checked[0].suite_ids for report in checked[1:]):
                self.issues.append("Suite selections differ. No model runs started.")
                return 1
            for index, target in enumerate(self.options.comparison_models):
                write_console(f"MODEL START {index + 1}/{len(self.runs)}  {target.runtime}/{target.model}\n")
                started = time.monotonic()
                path = self.directory / f"{index + 1}-results.json"
                try:
                    code = self._execute(self._command(target, path, check=False))
                except KeyboardInterrupt:
                    code = 130
                run = ModelRun(
                    runtime=target.runtime,
                    model=target.model,
                    exit_code=code,
                    wall_time_seconds=time.monotonic() - started,
                    report=self._read_report(path),
                )
                self.runs[index] = run.model_copy(update={"issue": self._validate_run(run)})
                self._save()
                if code == 130:
                    return 130
            self._check_selection()
            return int(bool(self.issues) or any(run.exit_code or run.issue for run in self.runs))
        except KeyboardInterrupt:
            self.issues.append("Comparison interrupted during configuration checks.")
            return 130
        except OSError as error:
            self.issues.append(f"Comparison could not run: {error}")
            return 1
        finally:
            self._save()
            write_console("\n" + self._text() + f"Comparison reports: {self.directory}\n")
