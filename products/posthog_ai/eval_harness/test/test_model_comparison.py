from __future__ import annotations

import os
import sys
import json
import signal
import subprocess
from pathlib import Path

import pytest

from products.posthog_ai.eval_harness.engines.types import AggregateScore, CaseResult, EvalSummary
from products.posthog_ai.eval_harness.harness.cli import parse_args
from products.posthog_ai.eval_harness.harness.comparison import ModelComparison
from products.posthog_ai.eval_harness.harness.discovery import EvalSuite
from products.posthog_ai.eval_harness.harness.reporting import ProgressReporter
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.harness.run_report import ExperimentReport, RunReport, ScoreReport
from products.posthog_ai.eval_harness.harness.skill_snapshot import SkillSnapshot


@pytest.mark.parametrize(
    "scenario,expected_exit,expected_calls",
    [
        ("success", 0, 4),
        ("in_checkout_output", 0, 4),
        ("skipped", 1, 4),
        ("filtered_out_experiment", 0, 4),
        ("launch_error", 1, 1),
        ("error", 1, 4),
        ("timeout", 1, 4),
        ("different_cases", 1, 4),
        ("different_scorers", 1, 4),
        ("different_checkout", 1, 4),
        ("different_skills", 1, 4),
        ("missing_skills", 1, 4),
        ("missing_report", 1, 4),
        ("failed_check", 1, 1),
        ("one_shot", 1, 1),
        ("interrupted", 130, 3),
    ],
)
def test_model_comparison_preserves_settings_and_partial_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    scenario: str,
    expected_exit: int,
    expected_calls: int,
) -> None:
    directory = tmp_path / "comparison"
    if scenario == "in_checkout_output":
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    options = parse_args(
        [
            "example/suite",
            "--compare",
            "--comparison-dir",
            str(directory),
            "--eval",
            "selected",
            "--provider",
            "modal",
            "--skill-delivery",
            "exec",
            "--trials",
            "3",
            "--max-sandboxes",
            "2",
            "--case-timeout",
            "123",
            "--infra-retries",
            "1",
            "--reasoning-effort",
            "medium",
        ]
    )
    calls: list[bool] = []
    fingerprint: str | None = None

    def execute(command: list[str]) -> int:
        nonlocal fingerprint
        child = parse_args(command[3:])
        calls.append(child.check_only)
        assert child.selectors == options.selectors
        assert child.case_filter == options.case_filter
        assert child.provider == options.provider
        assert child.skill_delivery == options.skill_delivery
        assert child.trials == options.trials
        assert child.max_sandboxes == options.max_sandboxes
        assert child.per_case_timeout_seconds == options.per_case_timeout_seconds
        assert child.infrastructure_retries == options.infrastructure_retries
        assert child.reasoning_effort == options.reasoning_effort
        assert child.interactive is False
        assert not child.comparison_models
        assert child.results_file is not None
        if scenario == "in_checkout_output" and not child.check_only:
            assert child.skill_snapshot_output_dir == directory
            current = SkillSnapshot.source_fingerprint(
                tmp_path, "skills", excluded_paths=(child.skill_snapshot_output_dir,)
            )
            if fingerprint is None:
                fingerprint = current
            assert current == fingerprint
        if (
            not child.check_only
            and child.agent_runtime == "codex"
            and scenario not in {"missing_report", "missing_skills"}
        ):
            assert child.skill_snapshot_report == directory / "1-results.json"
        if child.check_only and scenario == "failed_check":
            return 2
        if scenario == "launch_error":
            raise OSError("Example child launch failure")
        if not child.check_only and scenario == "interrupted":
            raise KeyboardInterrupt
        if not child.check_only and child.agent_runtime == "claude" and scenario == "missing_report":
            return 1
        second = child.agent_runtime == "codex"
        error = scenario == "error" and not second and not child.check_only
        timeout = scenario == "timeout" and not second
        report = RunReport(
            runtime=child.agent_runtime,
            model=child.agent_model,
            reasoning_effort=child.reasoning_effort,
            provider=child.provider,
            trials=child.trials,
            suite_ids=["example/suite::eval_suite"],
            suite_kinds=["one-shot" if scenario == "one_shot" else "sandboxed"],
            exit_code=int(error),
            duration_seconds=2,
            revision="changed" if scenario == "different_checkout" and second else "example-revision",
            skills_sha256=None
            if scenario == "missing_skills"
            else "b" * 64
            if scenario == "different_skills" and second
            else "a" * 64,
            skills_source_sha256="b" * 64,
            skills_archive_path=str(tmp_path / "skills.zip"),
            experiments={}
            if child.check_only
            else {
                "example": ExperimentReport(
                    cases={"other" if scenario == "different_cases" and second else "selected": 1},
                    planned_trials=3,
                    completed_trials=3,
                    errors=int(error),
                    timeouts=int(timeout),
                    scores={
                        "other_score" if scenario == "different_scorers" and second else "score": ScoreReport(
                            mean=None if scenario == "skipped" else (1 if second else 0),
                            scored_trials=0 if scenario == "skipped" else (2 if error else 3),
                        )
                    },
                    log_dir=str(tmp_path),
                ),
                **(
                    {
                        "filtered_out": ExperimentReport(
                            cases={},
                            planned_trials=0,
                            completed_trials=0,
                            errors=0,
                            timeouts=0,
                            scores={},
                            log_dir=str(tmp_path),
                        )
                    }
                    if scenario == "filtered_out_experiment"
                    else {}
                ),
            },
        )
        child.results_file.write_text(report.model_dump_json())
        return report.exit_code

    monkeypatch.setattr(ModelComparison, "_execute", staticmethod(execute))
    assert ModelComparison(options).run() == expected_exit
    assert len(calls) == expected_calls
    assert calls[:2] == [True, True][: min(expected_calls, 2)]
    assert not any(calls[2:])
    saved = json.loads((directory / "comparison.json").read_text())
    text = (directory / "comparison.txt").read_text()
    text = "\n".join(" ".join(line.split()) for line in text.splitlines())
    assert "Cost | unavailable | unavailable" in text
    assert "model + runtime" in text
    assert str(directory) in capsys.readouterr().out
    assert len(saved["runs"]) == 2
    assert saved["settings"]["skill_delivery"] == "exec"
    if scenario == "success":
        assert "0.0% (3/3 scored) | 100.0% (3/3 scored)" in text
    if scenario == "skipped":
        assert "example / score | n/a | n/a" in text
    if scenario == "launch_error":
        assert "Example child launch failure" in text
    if scenario.startswith("different_"):
        assert "not directly comparable" in text
    if scenario in {"failed_check", "one_shot", "interrupted"}:
        assert saved["runs"][1]["exit_code"] is None
    if scenario == "missing_report":
        assert saved["runs"][0]["report"] is None
        assert saved["runs"][1]["report"] is not None


@pytest.mark.parametrize("interrupt", [None, "keyboard", "sigterm"])
def test_comparison_streams_child_output_and_waits_for_interrupt_cleanup(
    interrupt: str | None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from products.posthog_ai.eval_harness.harness.transcript import write_console

    program = (
        "import signal, threading; ready = threading.Event(); "
        "signal.signal(signal.SIGINT, lambda *args: ready.set()); "
        "print('Child ready', flush=True); "
        + (
            "ready.wait(); print('Cleanup complete', flush=True); raise SystemExit(130)"
            if interrupt
            else "raise SystemExit(3)"
        )
    )

    def output(text: str) -> None:
        write_console(text)
        if interrupt == "keyboard" and "Child ready" in text:
            raise KeyboardInterrupt
        if interrupt == "sigterm" and "Child ready" in text:
            os.kill(os.getpid(), signal.SIGTERM)

    monkeypatch.setattr("products.posthog_ai.eval_harness.harness.comparison.write_console", output)
    if interrupt:
        with pytest.raises(KeyboardInterrupt):
            ModelComparison._execute([sys.executable, "-c", program])
        assert "Cleanup complete" in capsys.readouterr().out
    else:
        assert ModelComparison._execute([sys.executable, "-c", program]) == 3
        assert "Child ready" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_run_report_preserves_zero_skipped_scores_and_scorer_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EXPORT_EVAL_RESULTS", raising=False)
    options = parse_args(["example", "--trials", "3", "--results-file", str(tmp_path / "results.json")])
    reporter = ProgressReporter(1, revision="example-revision", worktree_dirty=True)
    reporter.set_skill_snapshot(
        SkillSnapshot(
            directory=tmp_path / "skills",
            manifest_path=tmp_path / "manifest.json",
            sha256="a" * 64,
            source_sha256="b" * 64,
            archive_path=tmp_path / "skills.zip",
        )
    )
    await reporter.experiment_started("example", 3, tmp_path, case_names=["selected"])
    for status in ("ok", "ok", "timeout"):
        await reporter.case_done("example", "selected", duration_seconds=1, status=status)
    await reporter.record_summary(
        "example",
        EvalSummary(
            engine_name="example",
            experiment_name="example",
            scores={
                "score": AggregateScore("score", 0),
            },
        ),
        error_count=1,
        case_results=[
            CaseResult(input={"name": "selected"}, output=None, scores={"score": 0, "skipped": None}),
            CaseResult(
                input={"name": "selected"},
                output=None,
                scores={"score": 0},
                error="Example scorer failure",
                error_kind="scorer",
            ),
            CaseResult(input={"name": "selected"}, output=None, scores={"score": 1}, error="Example task failure"),
        ],
    )

    async def suite(_ctx: object) -> None:
        pass

    suites = [
        EvalSuite(domain="example", module_name="example", fn_name="eval_suite", fn=suite, kind=SuiteKind.SANDBOXED)
    ]
    reporter.write_run_report(options, suites, exit_code=1, duration_seconds=3)
    assert options.results_file is not None
    report = RunReport.model_validate_json(options.results_file.read_text())
    experiment = report.experiments["example"]
    assert experiment.cases == {"selected": 1}
    assert experiment.errors == 1
    assert experiment.timeouts == 1
    assert experiment.scores["score"].mean == 0
    assert experiment.scores["score"].scored_trials == 2
    assert experiment.scores["skipped"].mean is None
    assert experiment.scores["skipped"].scored_trials == 0
    assert report.revision == "example-revision"
    assert report.worktree_dirty is True
    assert report.skills_sha256 == "a" * 64
    assert report.skills_manifest_path == str(tmp_path / "manifest.json")
    assert report.skills_source_sha256 == "b" * 64
    assert report.skills_archive_path == str(tmp_path / "skills.zip")
    assert not list(tmp_path.glob("*.tmp"))
