import json
import tempfile
from collections.abc import Sequence
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import pytest
from unittest.mock import patch

from parameterized import parameterized

from products.tasks.evals.agents_md.__main__ import Job, evaluate, main, report
from products.tasks.evals.agents_md.claims import (
    AGENTS_MD_PATH,
    Arm,
    Claim,
    ablate,
    agents_md_for,
    build_prompt,
    load_claims,
    review_bullets,
)
from products.tasks.evals.agents_md.detectors import (
    DETECTORS,
    Candidate,
    RuleVerdict,
    TaskAssessment,
    TaskStatus,
    assess_task,
    detect,
    judge,
)
from products.tasks.evals.golden_prs.agents import AgentRun, Runtime, agent_command
from products.tasks.evals.golden_prs.scoring import Answer


def diff_for(path: str, added: Sequence[str] = (), removed: Sequence[str] = (), new: bool = False) -> str:
    body = "\n".join([f"-{line}" for line in removed] + [f"+{line}" for line in added])
    mode = "new file mode 100644\n" if new else ""
    return f"diff --git a/{path} b/{path}\n{mode}--- a/{path}\n+++ b/{path}\n@@ -1,1 +1,1 @@\n{body}\n"


def claim(**overrides: Any) -> Claim:
    fields: dict[str, Any] = {
        "id": "rule",
        "section": "Comments",
        "line": "- **Explain why.** `[review]`",
        "task": "Do a thing.",
        "detectors": (),
        "untestable": None,
    }
    return Claim(**(fields | overrides))


def candidate(diff: str, workdir: Path = Path("/nonexistent")) -> Candidate:
    return Candidate.from_diff(diff, workdir)


def test_every_review_rule_in_agents_md_has_a_claim_with_known_detectors():
    claims = load_claims()
    assert {c.line for c in claims} == {line for _, line in review_bullets(AGENTS_MD_PATH.read_text())}
    assert len({c.id for c in claims}) == len(claims)
    for c in claims:
        if c.testable:
            assert c.detectors, c.id
            assert all(spec["name"] in DETECTORS for spec in c.detectors), c.id
        else:
            assert c.untestable, c.id


def test_one_rule_can_have_several_trap_tasks():
    agents_md = "## Rules\n\n- **Do the thing.** `[review]` Always.\n"
    entries = [
        {
            "id": "thing-named",
            "starts_with": "**Do the thing.**",
            "task": "Do it here.",
            "detectors": [{"name": "judge"}],
        },
        {"id": "thing-open", "starts_with": "**Do the thing.**", "task": "Do it.", "detectors": [{"name": "judge"}]},
    ]
    with tempfile.NamedTemporaryFile("w", suffix=".json") as claims_file:
        json.dump(entries, claims_file)
        claims_file.flush()
        claims = load_claims(agents_md, Path(claims_file.name))
    assert [c.id for c in claims] == ["thing-named", "thing-open"]
    assert claims[0].line == claims[1].line


def test_ablate_removes_only_the_rule_under_test():
    text = AGENTS_MD_PATH.read_text()
    without = ablate(text, load_claims()[0])
    assert load_claims()[0].line not in without
    assert len(without.splitlines()) == len(text.splitlines()) - 1
    with pytest.raises(ValueError):
        ablate(without, load_claims()[0])


def test_build_prompt_carries_the_task_and_not_the_rule():
    prompt = build_prompt(claim(task="Add a thing.", line="- **Explain why.** `[review]`"))
    assert "Add a thing." in prompt
    assert "Explain why" not in prompt
    assert "Do not install dependencies" in prompt


@parameterized.expand([("with", "Short file"), ("without", "Current file")])
def test_whole_file_comparison_does_not_remove_an_individual_rule(arm: Arm, expected: str) -> None:
    assert agents_md_for("Current file", claim(), arm, "Short file") == expected


def test_matrix_dry_run_includes_sonnet_without_starting_agents(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("products.tasks.evals.agents_md.__main__.evaluate") as evaluate:
        assert main(["run", "--matrix", "--dry-run", "--claim", load_claims()[0].id]) == 0
    output = capsys.readouterr().out
    for model in ("claude-opus-5-5", "claude-fable-5-1", "claude-sonnet-5-5", "gpt-6-astra", "gpt-6-sol"):
        assert model in output
    evaluate.assert_not_called()


@parameterized.expand(
    [
        ("posthog/tasks/read.py", 1.0),
        ("posthog/tasks/test/test_read.py", 0.0),
        ("posthog/tasks/tests/test_read.py", 0.0),
        ("posthog/tasks/test_read.py", 0.0),
    ]
)
def test_scoping_check_excludes_test_fixtures(path: str, expected: float) -> None:
    spec = next(c for c in load_claims() if c.id == "for-team-outside-request").detectors[1]
    params = {key: value for key, value in spec.items() if key != "name"}
    observed = DETECTORS[spec["name"]](
        candidate(diff_for(path, ["Widget.objects.unscoped().create(team_id=2)"])), claim(), **params
    )
    assert observed.violations == expected
    spec = next(c for c in load_claims() if c.id == "for-team-outside-request").detectors[0]
    params = {key: value for key, value in spec.items() if key != "name"}
    observed = DETECTORS[spec["name"]](
        candidate(diff_for(path, ["Widget.objects.for_team(2).count()"])), claim(), **params
    )
    assert observed.violations == 1.0 - expected


@parameterized.expand([("claude", True), ("codex", False)])
def test_eval_hook_setting_is_scoped_to_claude(runtime: Runtime, has_settings: bool) -> None:
    command = agent_command(runtime, "model", disable_hooks=True)
    assert ("--settings" in command) == has_settings
    if has_settings:
        assert json.loads(command[command.index("--settings") + 1])["disableAllHooks"] is True
    assert "--settings" not in agent_command(runtime, "model")


@parameterized.expand(
    [
        ("issues_found", False),
        ("no_issues_found", False),
        ("unmeasured", True),
    ]
)
def test_task_assessment_preserves_uncertainty(status: TaskStatus, fails: bool) -> None:
    answer = (
        Answer(value=None, failure="judge unavailable")
        if fails
        else Answer(value=TaskAssessment(status=status, reasoning="Checked the task."))
    )
    with patch("products.tasks.evals.agents_md.detectors.structured_answer", return_value=answer):
        observed = assess_task(candidate(diff_for("example.txt", ["Proposed change"])), claim(), model="judge")
    assert observed.status == status
    assert observed.reasoning


@parameterized.expand([("a.py", 1), (".flox/env/manifest.lock", 0)])
def test_failed_or_setup_changed_trials_are_not_scored(path: str, exit_code: int) -> None:
    run = AgentRun(
        runtime="claude",
        model="model",
        agent_version="version",
        exit_code=exit_code,
        timed_out=False,
        duration_seconds=1,
        stdout="",
        stderr="",
    )
    diff = diff_for(path, ["changed"])
    with (
        patch(
            "products.tasks.evals.agents_md.__main__.checkout_with_agents_md",
            return_value=nullcontext(Path("/nonexistent")),
        ),
        patch("products.tasks.evals.agents_md.__main__.run_agent", return_value=run),
        patch("products.tasks.evals.agents_md.__main__.candidate_diff", return_value=diff),
        patch("products.tasks.evals.agents_md.__main__.detect") as score,
        patch("products.tasks.evals.agents_md.__main__.assess_task") as assess,
    ):
        result, saved_diff, _ = evaluate(
            Job(claim=claim(), arm="with", repeat=1),
            "instructions",
            "claude",
            "model",
            "judge",
            30,
            Path("/nonexistent"),
            "ref",
        )
    assert result.failure
    assert result.violations is None
    assert result.task_assessment == "unmeasured"
    assert saved_diff == diff
    score.assert_not_called()
    assess.assert_not_called()


LONG_PROSE = "This sentence goes on for a while so that it is long enough to look like a wrapped paragraph and"


@parameterized.expand(
    [
        (
            "count matching",
            "count_added_matching",
            {"pattern": "os\\.path\\."},
            diff_for("a.py", ["p = os.path.join(a)"]),
            1,
        ),
        (
            "count in other files only",
            "count_added_matching",
            {"pattern": ".", "files": "*.md"},
            diff_for("a.py", ["x"]),
            0,
        ),
        (
            "missing, rule applies",
            "missing_added_matching",
            {"pattern": "loading=", "when": "<LemonButton"},
            diff_for("a.tsx", ["<LemonButton />"]),
            1,
        ),
        (
            "missing, rule does not apply",
            "missing_added_matching",
            {"pattern": "loading=", "when": "<LemonButton"},
            diff_for("a.tsx", ["<div />"]),
            0,
        ),
        (
            "present",
            "missing_added_matching",
            {"pattern": "loading="},
            diff_for("a.tsx", ["<LemonButton loading={x} />"]),
            0,
        ),
        (
            "new file outside prefix",
            "files_added_outside",
            {"prefix": "products/surveys/"},
            diff_for("tools/x.py", ["x"], new=True),
            1,
        ),
        (
            "changed file under prefix",
            "changed_files_under",
            {"prefix": "services/llm-gateway/"},
            diff_for("services/llm-gateway/a.py", ["x"]),
            1,
        ),
        (
            "several changed files under prefix is one breach",
            "changed_files_under",
            {"prefix": "services/llm-gateway/"},
            diff_for("services/llm-gateway/a.py", ["x"]) + diff_for("services/llm-gateway/b.py", ["y"]),
            1,
        ),
        ("indented import", "indented_imports", {}, diff_for("a.py", ["def f():", "    import json", "import os"]), 1),
        (
            "comment lines skip pragmas",
            "comment_lines",
            {},
            diff_for("a.py", ["# why", "# noqa: E501", "x = 1  # type: ignore"]),
            1,
        ),
        (
            "removed comment not re-added",
            "removed_comment_lines",
            {},
            diff_for("a.py", ["# kept"], ["# kept", "# lost"]),
            1,
        ),
        (
            "edited comment is kept",
            "removed_comment_lines",
            {},
            diff_for(
                "a.py",
                ["# Map the unit onto the token that posthog.helpers.relative_dates.parse understands."],
                ["# Map the unit onto the token that posthog.utils.parse understands."],
            ),
            0,
        ),
        (
            "stdlib dataclass",
            "stdlib_dataclass_decorators",
            {},
            diff_for("a.py", ["@dataclass(frozen=True)", "@frozen"]),
            1,
        ),
        (
            "ts functions without return types",
            "ts_functions_without_return_type",
            {},
            diff_for(
                "a.ts",
                [
                    "export function f(a: number) {",
                    "function g(): void {",
                    "const h = (a) => a",
                    "const i = (a): number => a",
                ],
            ),
            2,
        ),
        (
            "hard wrapped prose",
            "hard_wrapped_markdown",
            {},
            diff_for("a.md", [LONG_PROSE, f"- {LONG_PROSE}", "short and"]),
            1,
        ),
        (
            "command lines in a code fence are not prose",
            "hard_wrapped_markdown",
            {},
            diff_for("a.md", ["```bash", LONG_PROSE, "```", LONG_PROSE]),
            1,
        ),
        (
            "standalone tests in a new file",
            "unparameterized_tests",
            {},
            diff_for("test_a.py", ["def test_a():", "def test_b():"], new=True),
            3,
        ),
        (
            "parameterized tests in an existing file",
            "unparameterized_tests",
            {},
            diff_for("test_a.py", ["@parameterized.expand([1])", "def test_a(x):"]),
            0,
        ),
    ]
)
def test_diff_detectors_count_violations(_name: str, detector: str, params: dict[str, Any], diff: str, expected: float):
    assert DETECTORS[detector](candidate(diff), claim(), **params).violations == expected


HANDLE = "class Command:\n    def handle(self, *args, **options):\n        a = 1\n        b = 2\n        return a + b\n"
DEFS = "def f(a):\n    pass\n\n\ndef g(a: int) -> int:\n    return a\n"
CALL_FIRST = "def a():\n    return b()\n\n\ndef b():\n    return 1\n"
ATOMIC_WITH_EMAIL = "def view():\n    with transaction.atomic():\n        Thing.objects.create()\n        send_mail()\n"
ATOMIC_CLEAN = "def view():\n    with transaction.atomic():\n        Thing.objects.create()\n    send_mail()\n"
ATOMIC_CLEAN_ABOVE_OLD = ATOMIC_CLEAN + "\n\ndef old():\n    with transaction.atomic():\n        send_mail()\n"
TWO_DESCRIBES = "describe('a', () => {})\ndescribe('b', () => {})\n"


@parameterized.expand(
    [
        (
            "handle statements",
            "handle_statement_count",
            {},
            "posthog/management/commands/x.py",
            HANDLE,
            ["def handle(self, *args, **options):"],
            3,
        ),
        ("no handle added", "handle_statement_count", {}, "posthog/management/commands/x.py", HANDLE, ["x = 1"], None),
        ("unannotated def", "unannotated_defs", {}, "a.py", DEFS, ["def f(a):", "def g(a: int) -> int:"], 1),
        ("call before definition", "calls_before_definition", {}, "a.py", CALL_FIRST, ["def a():"], 1),
        (
            "email inside atomic",
            "side_effects_inside_atomic",
            {},
            "a.py",
            ATOMIC_WITH_EMAIL,
            ATOMIC_WITH_EMAIL.splitlines(),
            1,
        ),
        ("email after atomic", "side_effects_inside_atomic", {}, "a.py", ATOMIC_CLEAN, ATOMIC_CLEAN.splitlines(), 0),
        *[
            (
                name,
                "side_effects_inside_atomic",
                {},
                "a.py",
                source,
                source.splitlines(),
                expected,
            )
            for name, expression, expected in [
                ("deferred lambda", "transaction.on_commit(lambda: send_mail())", 0),
                ("callback evaluated before registration", "transaction.on_commit(send_mail())", 1),
                (
                    "lambda default evaluated before registration",
                    "transaction.on_commit(lambda value=send_mail(): value)",
                    1,
                ),
                ("lambda called immediately", "(lambda: send_mail())()", 1),
                (
                    "named callback",
                    "def callback():\n            send_mail()\n        transaction.on_commit(callback)",
                    0,
                ),
                (
                    "function default evaluated immediately",
                    "def callback(value=send_mail()):\n            return value",
                    1,
                ),
            ]
            for source in [
                f"def view():\n    with transaction.atomic():\n        Record.objects.create()\n        {expression}\n"
            ]
        ],
        (
            "old email inside an atomic block the agent did not touch",
            "side_effects_inside_atomic",
            {},
            "a.py",
            ATOMIC_CLEAN_ABOVE_OLD,
            ATOMIC_CLEAN.splitlines(),
            0,
        ),
        ("no atomic", "side_effects_inside_atomic", {}, "a.py", "def view():\n    send_mail()\n", ["send_mail()"], 1),
        ("two describes", "extra_top_level_describes", {}, "a.test.ts", TWO_DESCRIBES, ["describe('b', () => {})"], 1),
        (
            "pattern missing in file",
            "missing_in_file",
            {"path": "admin.py", "pattern": "raw_id_fields"},
            "admin.py",
            "x = 1\n",
            ["x = 1"],
            1,
        ),
    ]
)
def test_file_detectors_read_the_changed_file(
    _name: str, detector: str, params: dict[str, Any], path: str, content: str, added: list[str], expected: float | None
):
    with tempfile.TemporaryDirectory() as workdir:
        target = Path(workdir, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        observation = DETECTORS[detector](candidate(diff_for(path, added, new=True), Path(workdir)), claim(), **params)
    assert observation.violations == expected


def test_detect_sums_detectors_and_reports_no_number_when_one_cannot_tell():
    two = claim(detectors=({"name": "indented_imports"}, {"name": "count_added_matching", "pattern": "x"}))
    assert detect(candidate(diff_for("a.py", ["    import x", "x = 1"])), two).violations == 3
    assert detect(candidate(""), two).violations is None
    assert detect(candidate(""), claim(detectors=two.detectors, no_change_is_compliant=True)).violations == 0.0
    judged = claim(detectors=({"name": "judge"},))
    with patch(
        "products.tasks.evals.agents_md.detectors.structured_answer", return_value=Answer(value=None, failure="down")
    ):
        detection = detect(candidate(diff_for("a.py", ["x"])), judged)
    assert detection.violations is None
    assert "down" in detection.details[0]


@parameterized.expand(
    [
        ("two of three saw it", [True, False, True], 2 / 3, "2 of 3"),
        ("one of three saw it", [False, False, True], 1 / 3, "1 of 3"),
        ("a failed sample does not vote", [True, None, False], 0.5, "1 of 2"),
    ]
)
def test_judge_asks_several_times_and_reports_the_vote(
    _name: str, votes: list[bool | None], expected: float, tally: str
):
    answers = [
        Answer(value=None, failure="down")
        if vote is None
        else Answer(value=RuleVerdict(violated=vote, reasoning=f"v{i}"))
        for i, vote in enumerate(votes)
    ]
    with patch("products.tasks.evals.agents_md.detectors.structured_answer", side_effect=answers):
        observation = judge(candidate(diff_for("a.py", ["x"])), claim(), model="m")
    assert observation.violations == pytest.approx(expected)
    assert tally in observation.detail


def test_run_reports_a_crashed_job_and_finishes_the_others(capsys: pytest.CaptureFixture[str]):
    first = load_claims()[0].id
    with (
        patch("products.tasks.evals.agents_md.__main__.resolve_ref", return_value="abc"),
        patch("products.tasks.evals.agents_md.__main__.agents_md_at", return_value=AGENTS_MD_PATH.read_text()),
        patch("products.tasks.evals.agents_md.__main__.evaluate", side_effect=RuntimeError("boom")) as evaluate,
        tempfile.TemporaryDirectory() as results_dir,
    ):
        assert main(["run", "--claim", first, "--claim", first, "--results-dir", results_dir, "--workers", "1"]) == 1
    out = capsys.readouterr().out
    assert evaluate.call_count == 2
    assert out.count("crashed") == 2
    assert "RuntimeError: boom" in out


def result(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "claim": "rule",
        "section": "Comments",
        "runtime": "claude",
        "model": "m",
        "arm": "with",
        "repeat": 1,
        "violations": 0.0,
    }
    return fields | overrides


def test_report_shows_the_difference_the_rule_makes():
    rendered = report(
        [
            result(arm="with", violations=1.0),
            result(arm="with", repeat=2, violations=0.0),
            result(arm="without", violations=2.0),
            result(arm="without", repeat=2, violations=None),
            result(claim="quiet", arm="with", violations=0.0),
            result(claim="quiet", arm="without", violations=0.0),
            result(claim="quiet", model="other", arm="with", violations=0.0),
            result(claim="quiet", model="other", arm="without", violations=0.0),
            result(claim="backfire", arm="with", violations=2.0),
            result(claim="backfire", arm="without", violations=0.0),
            result(claim="missing", violations=None),
            result(claim="quiet", violations=10.0, failure="agent failed"),
            result(claim="review", task_assessment="issues_found"),
        ]
    )
    assert "### claude m" in rendered
    assert (
        "| rule | Comments | 0.50 (n=2) | 2.00 (n=1) | +1.50 | 1 of 1 |\n"
        "| quiet | Comments | 0.00 (n=1) | 0.00 (n=1) | no evidence | 0 of 1 |\n"
        "| backfire | Comments | 2.00 (n=1) | 0.00 (n=1) | -2.00 | 0 of 1 |\n"
    ) in rendered
    assert "No violations were detected in the available results for these claims: quiet" in rendered
    assert "claims: missing" not in rendered
    assert "Excluded 1 failed run" in rendered
    assert "issues_found: 1" in rendered
    assert "no_issues_found does not establish correctness" in rendered
    assert report([]) == "No results found.\n"
    compared = report([result(comparison="file"), result(comparison="file", arm="without", violations=1)])
    assert "Candidate file | Current file | Current minus candidate" in compared
    assert "With rule" not in compared
    with pytest.raises(ValueError, match="separately"):
        report([result(), result(comparison="file")])
