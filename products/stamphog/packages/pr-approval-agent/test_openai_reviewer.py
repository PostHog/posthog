"""Tests for the OpenAI reviewer harness."""

import sys
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from unittest.mock import MagicMock

# reviewer.py's claude_agent_sdk dep is installed by `uv run`, not the test venv.
sys.modules.setdefault("claude_agent_sdk", MagicMock())
sys.modules.setdefault("claude_agent_sdk.types", MagicMock())

import review_pr  # noqa: E402
import openai_reviewer  # noqa: E402
from github import PRData  # noqa: E402
from openai_reviewer import OpenAIReviewer, RepoTools  # noqa: E402

SECRET = "outside-the-checkout"


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("def handler():\n    return 1\n")
    (tmp_path / "secret.txt").write_text(SECRET)
    (root / "src" / "link.txt").symlink_to(tmp_path / "secret.txt")
    (root / "src" / "linkdir").symlink_to(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    return root


@pytest.mark.parametrize(
    "tool, arguments",
    [
        pytest.param("read_file", {"path": "../secret.txt", "offset": None, "limit": None}, id="read-dotdot"),
        pytest.param("read_file", {"path": "{outside}/secret.txt", "offset": None, "limit": None}, id="read-absolute"),
        pytest.param("read_file", {"path": "src/link.txt", "offset": None, "limit": None}, id="read-symlink"),
        pytest.param("grep", {"pattern": "outside", "path": "..", "glob": None}, id="grep-dotdot"),
        pytest.param("grep", {"pattern": "outside", "path": "src/linkdir", "glob": None}, id="grep-symlink-dir"),
        pytest.param("grep", {"pattern": "outside", "path": None, "glob": None}, id="grep-walk-skips-links"),
        pytest.param("glob", {"pattern": "../*"}, id="glob-dotdot"),
        pytest.param("glob", {"pattern": "src/*"}, id="glob-symlink-file"),
        pytest.param("glob", {"pattern": "src/linkdir/*"}, id="glob-symlink-dir"),
    ],
)
def test_tools_never_reveal_content_outside_the_checkout(checkout: Path, tool: str, arguments: dict) -> None:
    arguments = {k: v.format(outside=checkout.parent) if isinstance(v, str) else v for k, v in arguments.items()}

    output = RepoTools(checkout).call(tool, json.dumps(arguments))

    assert SECRET not in output
    if tool == "glob":
        listed = [line for line in output.splitlines() if not line.startswith(("(", "error"))]
        assert all((checkout / line).resolve().is_relative_to(checkout.resolve()) for line in listed)


@pytest.mark.parametrize(
    "arguments, expected",
    [
        pytest.param({"pattern": "def handler", "path": None, "glob": None}, "src/app.py:1:def handler():", id="root"),
        pytest.param({"pattern": "handler", "path": "src", "glob": "*.py"}, "src/app.py:1:def handler():", id="glob"),
        pytest.param({"pattern": "no such text", "path": None, "glob": None}, "(no matches)", id="no-match"),
        pytest.param({"pattern": "(unclosed", "path": None, "glob": None}, "error:", id="bad-pattern"),
    ],
)
def test_grep_finds_untracked_files_and_reports_bad_patterns(checkout: Path, arguments: dict, expected: str) -> None:
    output = RepoTools(checkout).call("grep", json.dumps(arguments))

    assert output.startswith(expected)


def test_grep_returns_clipped_output_when_a_broad_pattern_matches_too_much(checkout: Path) -> None:
    (checkout / "src" / "big.txt").write_text("match this line\n" * 20_000)

    output = RepoTools(checkout).call("grep", json.dumps({"pattern": "match", "path": None, "glob": None}))

    assert not output.startswith("error")
    assert output.endswith(f"(output truncated at {openai_reviewer.TOOL_OUTPUT_MAX_CHARS} characters)")


def _pr() -> PRData:
    return PRData(
        number=7,
        repo="PostHog/posthog",
        title="fix: handler",
        state="OPEN",
        draft=False,
        mergeable_state="clean",
        author="alice",
        labels=[],
        base_ref="master",
        base_sha="a",
        head_sha="h",
        files=[{"filename": "src/app.py", "additions": 1, "deletions": 0}],
        reviews=[],
        review_comments=[],
        check_runs=[],
    )


def _usage(input_tokens: int, cached: int, output_tokens: int, reasoning: int) -> SimpleNamespace:
    return SimpleNamespace(
        input_tokens=input_tokens,
        input_tokens_details=SimpleNamespace(cached_tokens=cached),
        output_tokens=output_tokens,
        output_tokens_details=SimpleNamespace(reasoning_tokens=reasoning),
    )


class _FakeResponses:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self.responses = responses
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> SimpleNamespace:
        # The harness appends to its conversation list after the call, so keep a snapshot.
        self.requests.append({**kwargs, "input": list(kwargs["input"])})
        return self.responses[len(self.requests) - 1]


def _tool_call(name: str, arguments: dict) -> SimpleNamespace:
    call = SimpleNamespace(type="function_call", call_id=f"call-{name}", name=name, arguments=json.dumps(arguments))
    return SimpleNamespace(status="completed", output=[call], output_text="", usage=_usage(1000, 0, 50, 40))


def _answer(facts: dict) -> SimpleNamespace:
    message = SimpleNamespace(type="message")
    return SimpleNamespace(
        status="completed", output=[message], output_text=json.dumps(facts), usage=_usage(1200, 900, 300, 200)
    )


_FACTS = {
    "risky_areas": ["migrations: src/app.py adds a column"],
    "reviews_on_current_head": [],
    "owning_team_author": False,
    "strong_familiarity": False,
    "unresolved_substantive_concerns": [],
    "other_refusal_grounds": [],
    "reasoning": "Touches a migration without a reviewer.",
    "change_summary": "x" * 700,
}


def test_tool_loop_reads_the_diff_and_derives_the_verdict_from_the_final_facts(checkout: Path) -> None:
    diff_path = checkout / ".pr-review-diff-test.patch"
    diff_path.write_text("+    return 1\n")
    fake = _FakeResponses(
        [_tool_call("read_file", {"path": str(diff_path), "offset": None, "limit": None}), _answer(_FACTS)]
    )
    reviewer = OpenAIReviewer(checkout, client=SimpleNamespace(responses=fake))
    gate_context = {"gate_verdict": "PENDING", "gates": []}
    classification = {"tier": "T1-agent", "t1_subclass": "T1b-small", "breadth": "narrow", "ownership": {}}

    result = reviewer.review(_pr(), classification, gate_context, diff_path=diff_path)

    assert result["verdict"] == "ESCALATE"
    assert result["risk"] == "high"
    assert len(result["change_summary"]) == openai_reviewer.CHANGE_SUMMARY_MAX_CHARS
    assert result["usage"] == {
        "model": "gpt-6.1-sol",
        "turns": 2,
        "input_tokens": 2200,
        "cached_input_tokens": 900,
        "output_tokens": 350,
        "reasoning_tokens": 240,
    }
    first, second = fake.requests
    assert str(diff_path) in first["input"][0]["content"]
    assert "read_file, grep, and glob" in first["instructions"]
    assert first["text"]["format"]["strict"] is True
    assert first["store"] is False
    tool_output = second["input"][-1]
    assert tool_output["type"] == "function_call_output"
    assert "return 1" in tool_output["output"]
    assert diff_path.exists()


@pytest.mark.parametrize(
    "budget_spent, expected_error",
    [
        (False, "Reached maximum number of turns"),
        (True, "time budget exhausted"),
    ],
)
def test_tool_loop_stops_with_an_error_the_pipeline_does_not_retry(
    checkout: Path, budget_spent: bool, expected_error: str
) -> None:
    calls = [_tool_call("glob", {"pattern": "src/*"}) for _ in range(5)]
    reviewer = OpenAIReviewer(checkout, client=SimpleNamespace(responses=_FakeResponses(calls)))
    if budget_spent:
        reviewer.deadline = 0.0
    gate_context = {"gate_verdict": "DENIED", "gates": []}
    diff_path = checkout / ".pr-review-diff-test.patch"
    diff_path.write_text("")

    with pytest.raises(RuntimeError, match=expected_error) as raised:
        reviewer.review(_pr(), {"tier": "T2-never", "breadth": "narrow", "ownership": {}}, gate_context, diff_path)
    assert not review_pr._is_retryable_error(str(raised.value))


@pytest.mark.parametrize(
    "summary, expected",
    [
        pytest.param("Short summary.", "Short summary.", id="under-cap"),
        pytest.param("First clause. " + "y" * 700, "First clause.", id="cut-at-sentence-end"),
        pytest.param("x" * 700, "x" * 600, id="no-sentence-end"),
    ],
)
def test_clip_summary_keeps_whole_sentences(summary: str, expected: str) -> None:
    assert openai_reviewer._clip_summary(summary) == expected
