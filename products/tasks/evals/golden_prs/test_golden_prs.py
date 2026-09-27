from collections import Counter
from collections.abc import Sequence
from typing import Any

from parameterized import parameterized

from products.tasks.evals.golden_prs.__main__ import report
from products.tasks.evals.golden_prs.agents import agent_environment
from products.tasks.evals.golden_prs.cases import GoldenPR, build_prompt, load_golden_prs, select_golden_prs
from products.tasks.evals.golden_prs.scoring import added_lines, changed_files, judge, score_diffs

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


def test_agent_environment_drops_github_credentials():
    env = agent_environment({"GH_TOKEN": "x", "GITHUB_TOKEN": "y", "ANTHROPIC_API_KEY": "z", "PATH": "/bin"})
    assert env == {"ANTHROPIC_API_KEY": "z", "PATH": "/bin"}


def test_report_lists_each_case_and_the_mean():
    results = [
        {
            "pr": 1,
            "title": "fix: a",
            "author": "pauldambra",
            "runtime": "claude",
            "model": "m",
            "scores": {"file_recall": 1.0, "added_line_f1": 0.5},
            "judge_score": 0.8,
            "duration_seconds": 120,
            "timed_out": False,
            "usage": {"total_cost_usd": 1.5},
            "judge_reasoning": "Good.",
        },
        {
            "pr": 2,
            "title": "fix: b",
            "author": "Twixes",
            "runtime": "claude",
            "model": "m",
            "scores": {"file_recall": 0.0, "added_line_f1": 0.0},
            "judge_score": 0.0,
            "duration_seconds": 1800,
            "timed_out": True,
            "usage": {},
            "judge_reasoning": "Nothing.",
        },
    ]
    rendered = report(results)
    assert "| #1 | fix: a | pauldambra | claude m | 1.00 | 0.50 | 0.80 | 2.0 | 1.50 |" in rendered
    assert "| 30.0 (timed out) | 0.00 |" in rendered
    assert "| **Mean** | | | | 0.50 | 0.25 | 0.40 | | |" in rendered
    assert report([]) == "No results found.\n"
