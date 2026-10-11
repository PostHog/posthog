import os
import re
import json
import tempfile
import subprocess
from collections import Counter
from dataclasses import dataclass

import anthropic
from pydantic import BaseModel, Field

DEFAULT_JUDGE_MODEL = "claude-opus-5"

# Generated or binary files: an agent cannot regenerate them without running the test suite,
# so they must not count against it.
ARTIFACT_SUFFIXES = (".ambr", ".snap", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico")
ARTIFACT_DIRS = ("__snapshots__/",)

DIFF_HEADER = re.compile(r"^diff --git a/(.*?) b/(.*)$", re.MULTILINE)

# Keeps the judge request inside the context window when an agent rewrites half the repository.
MAX_DIFF_CHARS_FOR_JUDGE = 120_000

JUDGE_SYSTEM_PROMPT = """You grade a coding agent's attempt at a task against the change a human engineer merged for the same task.

Score how completely the candidate diff implements the same behavior as the golden diff, from 0 to 1:
- 1.0: behaviorally equivalent. Naming, formatting, file layout and test style may differ.
- 0.7: the core behavior is implemented, but a secondary part of the golden change is missing or different.
- 0.4: a partial or partly wrong implementation of the core behavior.
- 0.0: nothing relevant, or the change breaks the behavior the task asks for.

Ignore snapshot files, generated files and lockfiles. Judge behavior, not similarity of text.
Explain the score in a few plain sentences that name what matches and what is missing."""


class Verdict(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    reasoning: str


@dataclass(frozen=True, kw_only=True, slots=True)
class DiffScores:
    file_recall: float
    file_precision: float
    file_jaccard: float
    added_line_f1: float


def is_artifact(path: str) -> bool:
    return path.endswith(ARTIFACT_SUFFIXES) or any(marker in path for marker in ARTIFACT_DIRS)


def changed_files(diff: str) -> set[str]:
    return {new_path for _, new_path in DIFF_HEADER.findall(diff) if not is_artifact(new_path)}


def added_lines(diff: str) -> Counter[str]:
    lines: Counter[str] = Counter()
    counting = False
    for line in diff.splitlines():
        header = DIFF_HEADER.match(line)
        if header:
            counting = not is_artifact(header.group(2))
        elif counting and line.startswith("+") and not line.startswith("+++"):
            content = line[1:].strip()
            if content:
                lines[content] += 1
    return lines


def _f1(candidate: Counter[str], golden: Counter[str]) -> float:
    overlap = sum((candidate & golden).values())
    if overlap == 0:
        return 0.0
    precision = overlap / sum(candidate.values())
    recall = overlap / sum(golden.values())
    return round(2 * precision * recall / (precision + recall), 3)


def score_diffs(candidate: str, golden: str) -> DiffScores:
    candidate_files, golden_files = changed_files(candidate), changed_files(golden)
    shared = candidate_files & golden_files
    union = candidate_files | golden_files
    return DiffScores(
        file_recall=round(len(shared) / len(golden_files), 3) if golden_files else 0.0,
        file_precision=round(len(shared) / len(candidate_files), 3) if candidate_files else 0.0,
        file_jaccard=round(len(shared) / len(union), 3) if union else 0.0,
        added_line_f1=_f1(added_lines(candidate), added_lines(golden)),
    )


def _bounded(diff: str) -> str:
    if len(diff) <= MAX_DIFF_CHARS_FOR_JUDGE:
        return diff
    return diff[:MAX_DIFF_CHARS_FOR_JUDGE] + "\n[diff truncated for the judge]\n"


def judge(
    task: str,
    candidate: str,
    golden: str,
    model: str = DEFAULT_JUDGE_MODEL,
    client: anthropic.Anthropic | None = None,
) -> Verdict:
    if not candidate.strip():
        return Verdict(score=0.0, reasoning="The agent changed no files.")
    request = (
        f"<task>\n{task}\n</task>\n\n"
        f"<golden_diff>\n{_bounded(golden)}\n</golden_diff>\n\n"
        f"<candidate_diff>\n{_bounded(candidate)}\n</candidate_diff>"
    )
    if client is None and not os.environ.get("ANTHROPIC_API_KEY"):
        return _judge_with_claude_cli(model, request)
    client = client or anthropic.Anthropic()
    response = client.messages.parse(
        model=model,
        max_tokens=4096,
        system=JUDGE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": request}],
        output_format=Verdict,
    )
    # A missing verdict is a broken judge, which must score 0 rather than vanish from the mean.
    return response.parsed_output or Verdict(score=0.0, reasoning="The judge returned no verdict.")


JUDGE_CLI_TIMEOUT_SECONDS = 10 * 60


def _judge_with_claude_cli(model: str, request: str) -> Verdict:
    """The CLI signs in with its own credentials, so a devbox with `claude` logged in needs no API key."""
    command = [
        "claude",
        "-p",
        "--no-session-persistence",
        "--model",
        model,
        "--tools",
        "",
        "--output-format",
        "json",
        "--system-prompt",
        JUDGE_SYSTEM_PROMPT,
        "--json-schema",
        json.dumps(Verdict.model_json_schema()),
    ]
    # A neutral working directory, so the CLI does not load this repository's CLAUDE.md and hooks into the judge.
    try:
        completed = subprocess.run(
            command,
            cwd=tempfile.gettempdir(),
            input=request,
            capture_output=True,
            text=True,
            check=False,
            timeout=JUDGE_CLI_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return Verdict(score=0.0, reasoning="The judge returned no verdict: the CLI timed out.")
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError:
        report = {}
    if report.get("structured_output"):
        return Verdict.model_validate(report["structured_output"])
    failure = report.get("result") or completed.stderr.strip() or f"exit code {completed.returncode}"
    return Verdict(score=0.0, reasoning=f"The judge returned no verdict: {failure}")
