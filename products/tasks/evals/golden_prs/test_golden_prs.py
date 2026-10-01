import os
import json
import tempfile
import subprocess
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from unittest.mock import patch

from parameterized import parameterized

from products.tasks.evals.golden_prs.__main__ import load_results, rejudge, report, verdict_for
from products.tasks.evals.golden_prs.agents import (
    AgentOutcome,
    AgentRun,
    agent_command,
    agent_environment,
    agent_failure,
    agent_reply,
    agent_usage,
)
from products.tasks.evals.golden_prs.cases import GoldenPR, build_prompt, load_golden_prs, select_golden_prs
from products.tasks.evals.golden_prs.costs import TokenPrices, case_cost_usd
from products.tasks.evals.golden_prs.scoring import (
    Verdict,
    added_lines,
    changed_files,
    eval_score,
    judge,
    score_diffs,
    structured_answer,
)
from products.tasks.evals.golden_prs.workspace import candidate_diff, checkout_parent

GOLDEN_AUTHORS = {"pauldambra", "benjackwhite", "mariusandra", "Twixes"}


def diff_for(path: str, added: Sequence[str], removed: Sequence[str] = ()) -> str:
    body = "\n".join([f"-{line}" for line in removed] + [f"+{line}" for line in added])
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1,1 +1,1 @@\n{body}\n"


def golden_pr(**overrides: Any) -> GoldenPR:
    fields: dict[str, Any] = {
        "number": 1,
        "author": "pauldambra",
        "title": "fix: a thing",
        "body": "## Problem\n\nIt breaks.",
        "merged_at": "2023-06-01T00:00:00Z",
        "merge_commit_sha": "a" * 40,
    }
    return GoldenPR(**(fields | overrides))


def test_golden_set_holds_human_written_prs_from_the_four_authors():
    prs = load_golden_prs()
    assert len({pr.number for pr in prs}) == len(prs)
    for pr in prs:
        assert pr.author in GOLDEN_AUTHORS, pr.number
        assert pr.merged_at[:4] in ("2023", "2024"), pr.number
        assert len(pr.merge_commit_sha) == 40, pr.number
        assert pr.body.strip(), pr.number


def test_select_golden_prs_rejects_unknown_numbers():
    prs = [golden_pr(number=1), golden_pr(number=2)]
    assert [pr.number for pr in select_golden_prs(prs, [2])] == [2]
    try:
        select_golden_prs(prs, [3])
    except ValueError as error:
        assert "[3]" in str(error)
    else:
        raise AssertionError("unknown PR number was accepted")


@parameterized.expand(
    [
        ("html comments", "Do it.\n<!-- Briefly describe the steps you took. -->\n", "<!--"),
        (
            "template footer",
            "Do it.\n\n👉 *Stay up-to-date with [PostHog coding conventions](https://example.com) for a smoother review.*\n",
            "Stay up-to-date",
        ),
        ("carriage returns", "Do it.\r\nNow.\r\n", "\r"),
        ("blank runs", "Do it.\n\n\n\n\nNow.", "\n\n\n"),
    ]
)
def test_build_prompt_strips_pr_template_noise(_name: str, body: str, must_not_contain: str):
    prompt = build_prompt(golden_pr(body=body))
    assert must_not_contain not in prompt
    assert "Do it." in prompt
    assert "# fix: a thing" in prompt


def test_build_prompt_forbids_looking_up_the_merged_pr_on_github():
    prompt = build_prompt(golden_pr(body="Do it."))
    assert "You must not search GitHub" in prompt.split("# fix: a thing")[0]


@parameterized.expand(
    [
        ("modified file", "diff --git a/posthog/x.py b/posthog/x.py\n", {"posthog/x.py"}),
        ("rename keeps new path", "diff --git a/old/x.py b/new/x.py\n", {"new/x.py"}),
        ("snapshot ignored", "diff --git a/t/__snapshots__/a.ambr b/t/__snapshots__/a.ambr\n", set()),
        ("image ignored", "diff --git a/frontend/__snapshots__/a.png b/frontend/__snapshots__/a.png\n", set()),
    ]
)
def test_changed_files_reads_diff_headers(_name: str, diff: str, expected: set[str]):
    assert changed_files(diff) == expected


def test_added_lines_skips_artifacts_and_blank_lines():
    diff = diff_for("posthog/x.py", ["  x = 1", ""]) + diff_for("t/__snapshots__/a.ambr", ["ignored"])
    assert added_lines(diff) == Counter({"x = 1": 1})


GOLDEN = diff_for("posthog/a.py", ["a = 1", "b = 2"]) + diff_for("posthog/b.py", ["c = 3"])


@parameterized.expand(
    [
        ("identical", GOLDEN, (1.0, 1.0, 1.0, 1.0)),
        ("empty candidate", "", (0.0, 0.0, 0.0, 0.0)),
        ("wrong files", diff_for("posthog/z.py", ["a = 1", "b = 2", "c = 3"]), (0.0, 0.0, 0.0, 1.0)),
        ("half the files", diff_for("posthog/a.py", ["a = 1", "b = 2"]), (0.5, 1.0, 0.5, 0.8)),
        ("extra file", GOLDEN + diff_for("posthog/extra.py", ["d = 4"]), (1.0, 0.667, 0.667, 0.857)),
    ]
)
def test_score_diffs_measures_overlap_with_the_golden_diff(_name: str, candidate: str, expected: tuple[float, ...]):
    scores = score_diffs(candidate, GOLDEN)
    assert (scores.file_recall, scores.file_precision, scores.file_jaccard, scores.added_line_f1) == expected


def test_judge_scores_an_empty_diff_without_calling_the_model():
    verdict = judge("task", "   \n", GOLDEN, client=None)
    assert verdict.score == 0.0


@parameterized.expand(
    [
        ("verdict", 0, '{"structured_output": {"score": 0.7, "reasoning": "Core done."}}', 0.7, "Core done."),
        ("no verdict", 0, '{"structured_output": null, "result": "I cannot say."}', 0.0, "I cannot say."),
        ("not logged in", 1, '{"is_error": true, "result": "Not logged in"}', 0.0, "Not logged in"),
        ("no json", 1, "", 0.0, "exit code 1"),
    ]
)
def test_judge_uses_the_claude_cli_when_no_api_key_is_set(
    _name: str, exit_code: int, stdout: str, expected_score: float, expected_reasoning: str
):
    completed = subprocess.CompletedProcess(args=["claude"], returncode=exit_code, stdout=stdout, stderr="")
    with (
        patch.dict(os.environ, {}, clear=True),
        patch("products.tasks.evals.golden_prs.scoring.subprocess.run", return_value=completed) as run,
    ):
        verdict = judge("task", GOLDEN, GOLDEN)
    assert run.call_args.args[0][0] == "claude"
    assert verdict.score == expected_score
    assert expected_reasoning in verdict.reasoning


@parameterized.expand(
    [
        ("verdict", 0, '{"score": 0.7, "reasoning": "Core done."}', 0.7, "Core done."),
        ("prose", 0, "I cannot say.", 0.0, "I cannot say."),
        ("no reply", 1, None, 0.0, "exit code 1"),
    ]
)
def test_a_gpt_judge_answers_through_the_codex_cli(
    _name: str, exit_code: int, reply: str | None, expected_score: float, expected_reasoning: str
) -> None:
    def codex(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess:
        if reply is not None:
            Path(command[command.index("--output-last-message") + 1]).write_text(reply)
        return subprocess.CompletedProcess(args=command, returncode=exit_code, stdout="", stderr="")

    with patch("products.tasks.evals.golden_prs.scoring.subprocess.run", side_effect=codex) as run:
        verdict = judge("task", GOLDEN, GOLDEN, model="gpt-6-sol")
    command = run.call_args.args[0]
    assert command[:2] == ["codex", "exec"] and "--ignore-user-config" in command
    assert verdict.score == expected_score
    assert expected_reasoning in verdict.reasoning


def test_rejudge_saves_a_second_verdict_beside_each_result_and_the_report_counts_each_case_once(
    tmp_path: Path,
) -> None:
    (tmp_path / "7.json").write_text(json.dumps({"pr": 7, "judge_score": 0.5}))
    (tmp_path / "7.diff").write_text(GOLDEN)
    with (
        patch("products.tasks.evals.golden_prs.__main__.ensure_golden_commits"),
        patch("products.tasks.evals.golden_prs.__main__.golden_diff", return_value=GOLDEN),
        patch(
            "products.tasks.evals.golden_prs.__main__.judge", return_value=Verdict(score=0.9, reasoning="Same.")
        ) as second_judge,
    ):
        rejudge(tmp_path, [golden_pr(number=7)], "gpt-6-sol", tmp_path)

    assert second_judge.call_args.kwargs["model"] == "gpt-6-sol"
    assert json.loads((tmp_path / "7.judge-gpt-6-sol.json").read_text()) == {
        "judge_model": "gpt-6-sol",
        "judge_score": 0.9,
        "judge_reasoning": "Same.",
    }
    assert load_results(tmp_path) == [{"pr": 7, "judge_score": 0.5, "second_judges": {"gpt-6-sol": 0.9}}]


@parameterized.expand([("diff only", None, ""), ("with the checkout", Path("/work/tree"), "Read,Grep,Glob")])
def test_cli_judge_reads_the_checkout_only_when_given_one(_name: str, read_dir: Path | None, tools: str) -> None:
    completed = subprocess.CompletedProcess(
        args=["claude"], returncode=0, stdout='{"structured_output": {"score": 1, "reasoning": "ok"}}', stderr=""
    )
    with (
        patch.dict(os.environ, {}, clear=True),
        patch("products.tasks.evals.golden_prs.scoring.subprocess.run", return_value=completed) as run,
    ):
        structured_answer("m", "system", "request", Verdict, read_dir=read_dir)
    command = run.call_args.args[0]
    assert command[command.index("--tools") + 1] == tools
    assert ("--add-dir" in command) == (read_dir is not None)
    assert command[command.index("--setting-sources") + 1] == "project,local"


def agent_run(**overrides: Any) -> AgentRun:
    fields: dict[str, Any] = {
        "runtime": "claude",
        "model": "m",
        "agent_version": "1",
        "exit_code": 0,
        "timed_out": False,
        "duration_seconds": 1.0,
        "stdout": "",
        "stderr": "",
    }
    return AgentRun(**(fields | overrides))


@parameterized.expand(
    [
        ("clean exit", agent_run(), None),
        (
            "claude error report",
            agent_run(exit_code=1, stdout='{"is_error": true, "result": "Not logged in"}'),
            "Not logged in",
        ),
        (
            "codex stderr",
            agent_run(runtime="codex", exit_code=1, stderr="warn\nERROR invalid peer certificate\n"),
            "ERROR invalid peer certificate",
        ),
        ("timeout", agent_run(exit_code=-1, timed_out=True), "The agent hit the case timeout."),
        ("silent failure", agent_run(exit_code=2), "The agent exited with code 2."),
    ]
)
def test_agent_failure_explains_a_non_zero_exit(_name: str, run: AgentRun, expected: str | None):
    assert agent_failure(run) == expected


CODEX_STREAM = (
    '{"type":"item.completed","item":{"type":"agent_message","text":"done"}}\n'
    '{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":40,"output_tokens":10}}\n'
    '{"type":"turn.completed","usage":{"input_tokens":50,"cached_input_tokens":0,"output_tokens":5}}\n'
)


@parameterized.expand(
    [
        (
            "claude cost and turns",
            agent_run(
                stdout='{"total_cost_usd": 1.5, "num_turns": 3, "usage": {"input_tokens": 7, "output_tokens": 2}}'
            ),
            {"total_cost_usd": 1.5, "num_turns": 3, "input_tokens": 7, "output_tokens": 2},
        ),
        (
            "codex tokens summed over turns",
            agent_run(runtime="codex", stdout=CODEX_STREAM),
            {"num_turns": 2, "input_tokens": 150, "cached_input_tokens": 40, "output_tokens": 15},
        ),
        ("nothing parseable", agent_run(stdout="not json"), {}),
    ]
)
def test_agent_usage_reads_each_runtime(_name: str, run: AgentRun, expected: dict[str, float | int]):
    assert agent_usage(run) == expected


@parameterized.expand(
    [
        ("claude result", agent_run(stdout='{"result": "done"}'), "done"),
        ("codex last message", agent_run(runtime="codex", stdout=CODEX_STREAM), "done"),
        ("nothing parseable", agent_run(stdout="not json"), ""),
    ]
)
def test_agent_reply_reads_each_runtime(_name: str, run: AgentRun, expected: str) -> None:
    assert agent_reply(run) == expected


def test_claude_agents_skip_user_level_instructions() -> None:
    command = agent_command("claude", "m")
    assert command[command.index("--setting-sources") + 1] == "project,local"


def test_verdict_for_a_failed_agent_names_the_failure_instead_of_judging():
    outcome = AgentOutcome.from_run(agent_run(exit_code=1, stderr="boom"))
    verdict = verdict_for(outcome, "task", "", GOLDEN, "judge-model")
    assert verdict.score == 0.0
    assert "boom" in verdict.reasoning


@parameterized.expand([("mnemonic prefixes", "diff.mnemonicPrefix"), ("no prefixes", "diff.noprefix")])
def test_candidate_diff_keeps_the_prefixes_the_scorer_reads(_name: str, host_git_setting: str):
    host_config = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": host_git_setting, "GIT_CONFIG_VALUE_0": "true"}
    with tempfile.TemporaryDirectory() as workdir, patch.dict(os.environ, host_config):
        subprocess.run(["git", "init", "-q"], cwd=workdir, check=True)
        Path(workdir, "x.py").write_text("x = 1\n")
        diff = candidate_diff(Path(workdir))
    assert changed_files(diff) == {"x.py"}
    assert added_lines(diff) == Counter({"x = 1": 1})


def test_checkout_parent_keeps_the_export_ignored_gitignore_so_build_output_stays_out_of_the_diff():
    with tempfile.TemporaryDirectory() as repo_dir:
        repo = Path(repo_dir)
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]
        subprocess.run([*git, "init", "-q"], cwd=repo, check=True)
        (repo / ".gitattributes").write_text(".gitignore export-ignore\n")
        (repo / ".gitignore").write_text("build/\n")
        (repo / "a.py").write_text("a = 1\n")
        for message in ("parent", "merge"):
            (repo / "a.py").write_text(f"# {message}\n")
            subprocess.run([*git, "add", "-A"], cwd=repo, check=True)
            subprocess.run([*git, "commit", "-q", "--no-verify", "-m", message], cwd=repo, check=True)
        merge_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout
        with checkout_parent(repo, golden_pr(merge_commit_sha=merge_sha.strip())) as workdir:
            (workdir / "build").mkdir()
            (workdir / "build" / "out.txt").write_text("built\n")
            (workdir / "a.py").write_text("a = 2\n")
            assert changed_files(candidate_diff(workdir)) == {"a.py"}
            read_only_cache = workdir / ".flox" / "cache"
            read_only_cache.mkdir(parents=True)
            (read_only_cache / "mod.go").write_text("")
            (read_only_cache / "mod.go").chmod(0o444)
            read_only_cache.chmod(0o555)
        assert not workdir.exists()


def test_agent_environment_drops_github_credentials_and_the_other_provider_key():
    host = {"GH_TOKEN": "x", "GITHUB_TOKEN": "y", "ANTHROPIC_API_KEY": "z", "OPENAI_API_KEY": "w", "PATH": "/bin"}
    assert agent_environment(host, "claude") == {"ANTHROPIC_API_KEY": "z", "PATH": "/bin"}
    assert agent_environment(host, "codex") == {"OPENAI_API_KEY": "w", "PATH": "/bin"}


@parameterized.expand(
    [
        ("fast case keeps the mean judge score", [0.8, 0.6], 10, 0.7),
        ("case at the slow mark loses half", [1.0], 30 * 60, 0.5),
        ("case past the slow mark loses no more than half", [1.0], 60 * 60, 0.5),
        ("halfway on the log scale loses a quarter", [1.0], (30 * 30 * 60) ** 0.5, 0.75),
    ]
)
def test_eval_score_combines_the_judges_with_speed(
    _name: str, judge_scores: list[float], seconds: float, expected: float
) -> None:
    assert eval_score(judge_scores, seconds) == pytest.approx(expected)


SOL_PRICES = {"openai/gpt-6-sol": TokenPrices(input=2e-6, cached_input=2e-7, output=1e-5)}


@parameterized.expand(
    [
        ("claude reports its own cost", "claude", "claude-opus-5-5", {"total_cost_usd": 1.5, "input_tokens": 9}, 1.5),
        (
            "codex tokens priced with cached input at the cache rate",
            "codex",
            "gpt-6-sol",
            {"input_tokens": 1_000_000, "cached_input_tokens": 800_000, "output_tokens": 10_000},
            0.4 + 0.16 + 0.1,
        ),
        ("codex model with no price", "codex", "gpt-unknown", {"input_tokens": 10, "output_tokens": 1}, None),
        ("no usage at all", "codex", "gpt-6-sol", {}, None),
    ]
)
def test_case_cost_prices_codex_tokens_at_api_rates(
    _name: str, runtime: str, model: str, usage: dict[str, float], expected: float | None
) -> None:
    cost = case_cost_usd({"runtime": runtime, "model": model, "usage": usage}, SOL_PRICES)
    assert cost == (None if expected is None else pytest.approx(expected))


def test_report_leads_with_the_eval_score_then_each_judge_then_speed_and_cost():
    results = [
        {
            "pr": 1,
            "title": "fix: a",
            "author": "pauldambra",
            "runtime": "codex",
            "model": "gpt-6-sol",
            "scores": {"file_recall": 1.0, "added_line_f1": 0.5},
            "judge_model": "claude-opus-5",
            "judge_score": 0.8,
            "second_judges": {"gpt-6-sol": 0.6},
            "duration_seconds": 10,
            "timed_out": False,
            "usage": {"input_tokens": 1_000_000, "cached_input_tokens": 800_000, "output_tokens": 10_000},
            "judge_reasoning": "Good.",
        },
        {
            "pr": 2,
            "title": "fix: b",
            "author": "Twixes",
            "runtime": "codex",
            "model": "gpt-6-sol",
            "scores": {"file_recall": 0.0, "added_line_f1": 0.0},
            "judge_model": "claude-opus-5",
            "judge_score": 0.0,
            "second_judges": {"gpt-6-sol": 0.0},
            "duration_seconds": 1800,
            "timed_out": True,
            "usage": {},
            "judge_reasoning": "Nothing.",
        },
    ]
    rendered = report(results, SOL_PRICES)
    assert "| Eval score | Judge claude-opus-5 | Judge gpt-6-sol | Minutes | Cost $ | Files hit | Line F1 |" in rendered
    assert "| #1 | fix: a | pauldambra | codex gpt-6-sol | 0.70 | 0.80 | 0.60 | 0.2 | 0.66 | 1.00 | 0.50 |" in rendered
    assert "| 0.00 | 0.00 | 0.00 | 30.0 (timed out) | n/a |" in rendered
    assert "| **Mean** | | | | 0.35 | 0.40 | 0.30 | 15.1 | 0.66 | 0.50 | 0.25 |" in rendered
    assert report([], SOL_PRICES) == "No results found.\n"
