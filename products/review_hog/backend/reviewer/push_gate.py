"""The push gate: decides whether an automatic follow-up review turn is worth its cost.

Every push to an opted-in author's PR starts an automatic turn, and a follow-up turn re-reviews the
whole PR. The gate looks at the interdiff from the last automatically reviewed head to the new head.
It never sees a first review or a human trigger: the workflow calls it only for automatic follow-ups.

The rules, in order. The first rule that matches gives the reason:

1. `no_new_commits`: the new head adds no commit to the last reviewed head (a force-push back).
2. `merge_only`: the PR's own diff against its base is the same at both heads, so the push only
   brought in base-branch changes (a merge or a rebase).
3. `docs_only`: the PR's own part of the interdiff touches only docs, lockfiles, and generated files.
4. `system_one_below_threshold`: System One rates the chance of a behavior change below a threshold.

Each rule has its own switch. A rule that is switched off still reports the turn it would skip
(`would_skip`), so production data can calibrate it before it skips anything. Every failure fails
open: the turn runs.
"""

import base64
import logging
from pathlib import PurePosixPath
from typing import Any, Literal

import requests

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubRateLimitError
from posthog.llm.system_one import NoulAnswer, NoulQuestion, SystemOneNotConfigured, SystemOneRequestFailed
from posthog.llm.system_one_client import build_system_one_client

from products.review_hog.backend.reviewer.tools.github_client import GitHubAPIError, github_api_request
from products.review_hog.backend.reviewer.tools.github_meta import GITHUB_COMPARE_FILES_CAP, PRFilter, PRParser

logger = logging.getLogger(__name__)

# Which rules skip a turn. A rule that is off only reports what it would skip. The offline study of
# later Flash turns lost no acted-on finding to the first two rules. It lost some to the docs rule,
# because a turn re-reads the whole PR and finds issues outside the interdiff. System One has no
# calibrated threshold yet.
SKIP_NO_NEW_COMMITS = True
SKIP_MERGE_ONLY = True
SKIP_DOCS_ONLY = False
SKIP_SYSTEM_ONE = False

# The JevK5 build PostHog hosts on the ai-gateway. A threshold is only valid for the model it was set
# against, so the gate pins a version instead of an alias.
PUSH_GATE_MODEL = "posthog/hogference/jevk5-fp8-0.2"
# System One would skip a turn below this probability of a behavior change. The value is deliberately
# low, so the gate would skip only pushes the model is confident are inert. A separate study calibrates
# it from the shadow decisions before `SKIP_SYSTEM_ONE` goes on.
SYSTEM_ONE_SKIP_BELOW = 0.1
# The ml_inference decision API caps a state at this size. A larger interdiff runs the turn instead of
# being cut, because the cut part can hold the change that matters.
MAX_INTERDIFF_CHARS = 65_536
# A push waits for this answer before its review starts, so a slow gateway must not hold the review long.
SYSTEM_ONE_TIMEOUT_SECONDS = 15.0

_QUESTION_ID = "behavior_change"
# The interdiff stays in the state, so text from the pull request can never become an instruction.
_BEHAVIOR_CHANGE_QUESTION = NoulQuestion(
    instructions=(
        "state.interdiff is the code diff pushed to a pull request since its last review. "
        "This change could alter runtime behavior or introduce a bug."
    ),
    criteria_true="The diff changes logic, control flow, data handling, queries, configuration, or dependencies.",
    criteria_false="The diff only renames, reformats, edits comments, or moves code without changing what it does.",
)

_DOC_SUFFIXES = frozenset({".md", ".mdx", ".rst", ".adoc"})
# Markdown in these directories is runtime input (agent skills, LLM prompts, rendered templates), so an
# edit there can change behavior.
_RUNTIME_MARKDOWN_DIRS = frozenset({"skills", "prompts", "templates"})

SkipReason = Literal["no_new_commits", "merge_only", "docs_only", "system_one_below_threshold"]
RunReason = Literal[
    "system_one_above_threshold",
    "system_one_unavailable",
    "interdiff_too_large",
    "compare_unavailable",
    "snapshot_unavailable",
]


@frozen
class PushGateDecision:
    # Whether the turn skips. Only a rule that is switched on skips.
    skip: bool
    # Whether a rule matched, switched on or not. A match with its rule off is a shadow decision.
    would_skip: bool
    reason: SkipReason | RunReason
    probability: float | None = None
    model: str | None = None
    # Files in the PR's own part of the interdiff, when the gate got that far.
    interdiff_files: int | None = None


@frozen
class _CompareFile:
    filename: str
    status: str
    changes: int
    # GitHub leaves the patch out for a binary or very large file.
    patch: str | None


@frozen
class _Comparison:
    # Commits the head has that the base does not.
    ahead_by: int
    files: list[_CompareFile]


def _rule_enabled(reason: SkipReason) -> bool:
    if reason == "no_new_commits":
        return SKIP_NO_NEW_COMMITS
    if reason == "merge_only":
        return SKIP_MERGE_ONLY
    if reason == "docs_only":
        return SKIP_DOCS_ONLY
    return SKIP_SYSTEM_ONE


def _matched(
    reason: SkipReason,
    *,
    interdiff_files: int | None = None,
    probability: float | None = None,
    model: str | None = None,
) -> PushGateDecision:
    return PushGateDecision(
        skip=_rule_enabled(reason),
        would_skip=True,
        reason=reason,
        probability=probability,
        model=model,
        interdiff_files=interdiff_files,
    )


def _runs(
    reason: RunReason,
    *,
    interdiff_files: int | None = None,
    probability: float | None = None,
    model: str | None = None,
) -> PushGateDecision:
    return PushGateDecision(
        skip=False,
        would_skip=False,
        reason=reason,
        probability=probability,
        model=model,
        interdiff_files=interdiff_files,
    )


def _is_doc(filename: str) -> bool:
    path = PurePosixPath(filename)
    return path.suffix.lower() in _DOC_SUFFIXES and not _RUNTIME_MARKDOWN_DIRS.intersection(path.parts[:-1])


def _own_lines(files: list[_CompareFile]) -> dict[str, list[tuple[str, str]]] | None:
    """The PR's added and removed lines per file, without line numbers, which shift when the base moves."""
    lines: dict[str, list[tuple[str, str]]] = {}
    for file in files:
        if file.patch is None and file.changes:
            # GitHub left the patch out, so the lines of this file cannot be compared.
            return None
        changes = PRParser.parse_patch(file.patch or "")
        lines[file.filename] = [(change.type, change.code) for change in changes if change.type != "context"]
    return lines


class GeneratedPaths:
    """The paths a repository's `.gitattributes` marks as `linguist-generated`."""

    def __init__(self, patterns: list[str]) -> None:
        self.patterns = patterns

    @classmethod
    def parse(cls, text: str) -> "GeneratedPaths":
        patterns: list[str] = []
        for line in text.splitlines():
            parts = line.split()
            if not parts or parts[0].startswith("#"):
                continue
            if any(attribute in ("linguist-generated", "linguist-generated=true") for attribute in parts[1:]):
                patterns.append(parts[0])
        return cls(patterns)

    def matches(self, filename: str) -> bool:
        path = PurePosixPath(filename)
        for pattern in self.patterns:
            if pattern.startswith("/"):
                matched = path.full_match(pattern.lstrip("/"))
            elif "/" in pattern:
                matched = path.full_match(pattern)
            else:
                # Git matches a pattern without a slash against the file name at any depth.
                matched = PurePosixPath(path.name).full_match(pattern)
            if matched:
                return True
        return False


class PushGate:
    def __init__(self, *, team_id: int, repository: str, token: str, installation_id: str | None) -> None:
        self.team_id = team_id
        self.repository = repository
        self._token = token
        self._installation_id = installation_id

    def _compare(self, base: str, head: str) -> _Comparison | None:
        """`base...head` from GitHub, or None when the compare is unavailable or truncated."""
        try:
            comparison: dict[str, Any] = github_api_request(
                "GET",
                f"/repos/{self.repository}/compare/{base}...{head}",
                token=self._token,
                installation_id=self._installation_id,
                endpoint="/repos/{owner}/{repo}/compare/{basehead}",
                # The file list comes with the first page in full, so one commit per page keeps the body small.
                params={"per_page": 1},
            ).json()
        except (GitHubAPIError, GitHubRateLimitError, requests.RequestException) as error:
            logger.warning("Push gate could not compare %s: %s", self.repository, type(error).__name__)
            return None
        files: list[dict[str, Any]] = comparison.get("files") or []
        if len(files) >= GITHUB_COMPARE_FILES_CAP:
            return None
        return _Comparison(
            ahead_by=comparison["ahead_by"],
            files=[
                _CompareFile(
                    filename=file["filename"],
                    status=file["status"],
                    changes=file.get("changes", 0),
                    patch=file.get("patch"),
                )
                for file in files
            ],
        )

    def _generated_paths(self, head_sha: str) -> GeneratedPaths:
        try:
            content = github_api_request(
                "GET",
                f"/repos/{self.repository}/contents/.gitattributes",
                token=self._token,
                installation_id=self._installation_id,
                endpoint="/repos/{owner}/{repo}/contents/{path}",
                params={"ref": head_sha},
            ).json()
            return GeneratedPaths.parse(base64.b64decode(content["content"]).decode())
        except (GitHubAPIError, GitHubRateLimitError, requests.RequestException, KeyError, ValueError):
            # No readable list means no file counts as generated, so the gate errs toward a review.
            return GeneratedPaths([])

    def _code_files(self, files: list[_CompareFile], head_sha: str) -> list[_CompareFile]:
        remaining = [
            file for file in files if not _is_doc(file.filename) and not PRFilter.is_filtered_file(file.filename)
        ]
        if not remaining:
            return []
        generated = self._generated_paths(head_sha)
        return [file for file in remaining if not generated.matches(file.filename)]

    def _ask_system_one(self, code_files: list[_CompareFile], interdiff_files: int) -> PushGateDecision:
        if any(file.patch is None for file in code_files):
            # System One cannot judge a change it cannot see.
            return _runs("interdiff_too_large", interdiff_files=interdiff_files)
        interdiff = "\n\n".join(f"=== {file.filename} [{file.status}] ===\n{file.patch}" for file in code_files)
        if len(interdiff) > MAX_INTERDIFF_CHARS:
            return _runs("interdiff_too_large", interdiff_files=interdiff_files)
        try:
            client = build_system_one_client(
                model=PUSH_GATE_MODEL,
                ai_product="review_hog",
                team_id=self.team_id,
                timeout=SYSTEM_ONE_TIMEOUT_SECONDS,
            )
            result = client.decide(state={"interdiff": interdiff}, questions={_QUESTION_ID: _BEHAVIOR_CHANGE_QUESTION})
        except (SystemOneNotConfigured, SystemOneRequestFailed) as error:
            logger.warning("Push gate could not reach System One: %s", type(error).__name__)
            return _runs("system_one_unavailable", interdiff_files=interdiff_files)
        answer = result.answers[_QUESTION_ID]
        if not isinstance(answer, NoulAnswer):
            return _runs("system_one_unavailable", interdiff_files=interdiff_files)
        if answer.probability < SYSTEM_ONE_SKIP_BELOW:
            return _matched(
                "system_one_below_threshold",
                interdiff_files=interdiff_files,
                probability=answer.probability,
                model=result.model,
            )
        return _runs(
            "system_one_above_threshold",
            interdiff_files=interdiff_files,
            probability=answer.probability,
            model=result.model,
        )

    def decide(self, *, previous_head_sha: str, head_sha: str, base_branch: str) -> PushGateDecision:
        """Judge the push from `previous_head_sha`, the last automatically reviewed head, to `head_sha`."""
        interdiff = self._compare(previous_head_sha, head_sha)
        if interdiff is None:
            return _runs("compare_unavailable")
        if interdiff.ahead_by == 0:
            return _matched("no_new_commits")
        # The PR's full diff at each head, before ReviewHog drops lockfiles and tests from what it reviews.
        previous_diff = self._compare(base_branch, previous_head_sha)
        current_diff = self._compare(base_branch, head_sha)
        if previous_diff is None or current_diff is None:
            return _runs("compare_unavailable")
        # An interdiff file outside the PR's diff at both heads matches the base branch, so its change
        # came in with the base.
        pr_filenames = {file.filename for file in previous_diff.files + current_diff.files}
        own_files = [file for file in interdiff.files if file.filename in pr_filenames]
        previous_lines = _own_lines(previous_diff.files)
        if not own_files or (previous_lines is not None and previous_lines == _own_lines(current_diff.files)):
            return _matched("merge_only", interdiff_files=len(own_files))
        code_files = self._code_files(own_files, head_sha)
        if not code_files:
            return _matched("docs_only", interdiff_files=len(own_files))
        return self._ask_system_one(code_files, interdiff_files=len(own_files))
