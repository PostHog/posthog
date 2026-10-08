"""The push gate: decides whether an automatic follow-up review turn is worth its cost.

Every push to an opted-in author's PR starts an automatic turn, and a follow-up turn re-reviews the
whole PR. The gate looks at the PR's own commits since the last automatically reviewed head. It never
sees a first review or a human trigger: the workflow calls it only for automatic follow-ups.

The rules, in order. The first rule that matches gives the reason:

1. `no_new_commits`: the PR has no commit it did not have at the last reviewed head (a force-push back).
2. `merge_only`: the PR's full diff against its base is the same at both heads (a base merge or a
   rebase). A merge that changes the PR's own lines runs the review.
3. `docs_only`: the new own commits touch only docs, lockfiles, snapshots, images, and generated files.
4. `system_one_below_threshold`: System One rates the new own commits below a threshold.

Each rule has its own switch. A rule that is switched off still reports the turn it would skip
(`would_skip`), so production data can calibrate it before it skips anything. Every failure fails
open: the turn runs.

The rules, the non-code file list, the System One question, and the state follow the offline study
in `review-eval/production/push-gate`. The threshold is only valid for the state built the same way.
"""

import re
import logging
from typing import Any, Literal

import requests

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubRateLimitError
from posthog.llm.system_one import NoulAnswer, NoulQuestion, SystemOneNotConfigured, SystemOneRequestFailed
from posthog.llm.system_one_client import build_system_one_client

from products.review_hog.backend.reviewer.tools.github_client import GitHubAPIError, github_api_request
from products.review_hog.backend.reviewer.tools.github_meta import GITHUB_COMPARE_FILES_CAP, PRParser

logger = logging.getLogger(__name__)

# A rule that is off only records the skip it would make, so production data can calibrate it first.
SKIP_NO_NEW_COMMITS = True
SKIP_MERGE_ONLY = True
SKIP_DOCS_ONLY = False
SKIP_SYSTEM_ONE = False

# The JevK5 build PostHog hosts on the ai-gateway. The study calibrated the threshold on TypeSafe's
# `jev-latest`, so the shadow decisions must confirm it holds for this model before SKIP_SYSTEM_ONE goes on.
PUSH_GATE_MODEL = "posthog/hogference/jevk5-fp8-0.2"
SYSTEM_ONE_SKIP_BELOW = 0.30
# The study sent states up to 64k tokens, at about 3.5 characters per token of code.
MAX_STATE_CHARS = 224_000
SYSTEM_ONE_TIMEOUT_SECONDS = 15.0
# Each new own commit costs one GitHub call to read its patch.
MAX_OWN_COMMITS = 20
# GitHub's compare endpoint pages its commit list at this size.
_COMPARE_COMMITS_PER_PAGE = 100

_QUESTION_ID = "alters"
# The commits stay in the state, so text from the pull request can never become an instruction.
_ALTERS_QUESTION = NoulQuestion(
    instructions=(
        "Read the code change in the state. Could this change alter the behavior of the code "
        "or introduce a bug? Answer true if it could, false if it is only cosmetic, a rename, "
        "formatting, a comment, documentation or a test-only tweak that cannot affect behavior."
    ),
)

_NON_CODE_FILE = re.compile(
    "|".join(
        [
            r"(^|/)(pnpm-lock\.yaml|uv\.lock|package-lock\.json|yarn\.lock|Cargo\.lock|poetry\.lock|flox/manifest\.lock|\.flox/env/manifest\.lock)$",
            r"\.md$",
            r"\.mdx$",
            r"(^|/)docs/",
            r"(^|/)generated/",
            r"\.generated\.",
            r"(^|/)__snapshots__/",
            r"\.ambr$",
            r"\.snap$",
            r"\.(png|jpg|jpeg|gif|svg|webp)$",
            r"(^|/)(openapi|schema)\.json$",
            r"(^|/)api\.(schemas|zod)\.ts$",
            r"(^|/)frontend/src/queries/schema\.json$",
            r"(^|/)posthog/schema\.py$",
        ]
    )
)

SkipReason = Literal["no_new_commits", "merge_only", "docs_only", "system_one_below_threshold"]
RunReason = Literal[
    "commits_removed",
    "system_one_above_threshold",
    "system_one_unavailable",
    "interdiff_too_large",
    "compare_unavailable",
    "snapshot_unavailable",
]


@frozen
class PushGateDecision:
    skip: bool
    # Whether a rule matched, switched on or not. A match with its rule off is a shadow decision.
    would_skip: bool
    reason: SkipReason | RunReason
    probability: float | None = None
    model: str | None = None
    own_commits: int | None = None


@frozen
class _ChangedFile:
    filename: str
    changes: int
    patch: str | None


@frozen
class _ChangedLine:
    type: str
    code: str


@frozen
class _PRDiff:
    """The PR as `base...head`: its commits, the merge commits among them, and its full diff."""

    commit_shas: list[str]
    merge_shas: set[str]
    files: list[_ChangedFile]


def _rule_enabled(reason: SkipReason) -> bool:
    if reason == "no_new_commits":
        return SKIP_NO_NEW_COMMITS
    if reason == "merge_only":
        return SKIP_MERGE_ONLY
    if reason == "docs_only":
        return SKIP_DOCS_ONLY
    return SKIP_SYSTEM_ONE


def _matched(
    reason: SkipReason, *, own_commits: int | None = None, probability: float | None = None, model: str | None = None
) -> PushGateDecision:
    return PushGateDecision(
        skip=_rule_enabled(reason),
        would_skip=True,
        reason=reason,
        probability=probability,
        model=model,
        own_commits=own_commits,
    )


def _runs(
    reason: RunReason, *, own_commits: int | None = None, probability: float | None = None, model: str | None = None
) -> PushGateDecision:
    return PushGateDecision(
        skip=False,
        would_skip=False,
        reason=reason,
        probability=probability,
        model=model,
        own_commits=own_commits,
    )


def _changed_files(payload: dict[str, Any]) -> list[_ChangedFile]:
    return [
        _ChangedFile(filename=file["filename"], changes=file.get("changes", 0), patch=file.get("patch"))
        for file in payload.get("files") or []
    ]


def _own_lines(files: list[_ChangedFile]) -> dict[str, list[_ChangedLine]] | None:
    """The PR's added and removed lines per file, without line numbers, which shift when the base moves."""
    lines: dict[str, list[_ChangedLine]] = {}
    for file in files:
        if file.patch is None and file.changes:
            # GitHub left the patch out, so the lines of this file cannot be compared.
            return None
        changes = PRParser.parse_patch(file.patch or "")
        lines[file.filename] = [
            _ChangedLine(type=change.type, code=change.code) for change in changes if change.type != "context"
        ]
    return lines


def _same_full_diff(previous: _PRDiff, current: _PRDiff) -> bool:
    previous_lines = _own_lines(previous.files)
    return previous_lines is not None and previous_lines == _own_lines(current.files)


class PushGate:
    def __init__(self, *, team_id: int, repository: str, token: str, installation_id: str | None) -> None:
        self.team_id = team_id
        self.repository = repository
        self._token = token
        self._installation_id = installation_id

    def _get(self, path: str, *, endpoint: str, params: dict[str, str | int] | None = None) -> dict[str, Any] | None:
        try:
            return github_api_request(
                "GET",
                f"/repos/{self.repository}{path}",
                token=self._token,
                installation_id=self._installation_id,
                endpoint=f"/repos/{{owner}}/{{repo}}{endpoint}",
                params=params,
            ).json()
        except (GitHubAPIError, GitHubRateLimitError, requests.RequestException) as error:
            logger.warning("Push gate could not read %s from GitHub: %s", endpoint, type(error).__name__)
            return None

    def _pr_diff(self, base_branch: str, head_sha: str) -> _PRDiff | None:
        """The PR at `head_sha`, or None when GitHub cannot return all of it in one page."""
        comparison = self._get(
            f"/compare/{base_branch}...{head_sha}",
            endpoint="/compare/{basehead}",
            params={"per_page": _COMPARE_COMMITS_PER_PAGE},
        )
        if comparison is None:
            return None
        commits: list[dict[str, Any]] = comparison.get("commits") or []
        files = _changed_files(comparison)
        if comparison.get("total_commits", 0) > len(commits) or len(files) >= GITHUB_COMPARE_FILES_CAP:
            return None
        return _PRDiff(
            commit_shas=[commit["sha"] for commit in commits],
            merge_shas={commit["sha"] for commit in commits if len(commit.get("parents") or []) > 1},
            files=files,
        )

    def _commit_files(self, shas: list[str]) -> list[_ChangedFile] | None:
        files: list[_ChangedFile] = []
        for sha in shas:
            commit = self._get(f"/commits/{sha}", endpoint="/commits/{ref}")
            if commit is None:
                return None
            files.extend(_changed_files(commit))
        return files

    def _ask_system_one(self, code_files: list[_ChangedFile], own_commits: int) -> PushGateDecision:
        if any(file.patch is None for file in code_files):
            return _runs("interdiff_too_large", own_commits=own_commits)
        state = "\n\n".join(f"--- {file.filename}\n{file.patch}" for file in code_files)
        if len(state) > MAX_STATE_CHARS:
            return _runs("interdiff_too_large", own_commits=own_commits)
        try:
            client = build_system_one_client(
                model=PUSH_GATE_MODEL,
                ai_product="review_hog",
                team_id=self.team_id,
                timeout=SYSTEM_ONE_TIMEOUT_SECONDS,
            )
            result = client.decide(state=state, questions={_QUESTION_ID: _ALTERS_QUESTION})
        except (SystemOneNotConfigured, SystemOneRequestFailed) as error:
            logger.warning("Push gate could not reach System One: %s", type(error).__name__)
            return _runs("system_one_unavailable", own_commits=own_commits)
        answer = result.answers[_QUESTION_ID]
        if not isinstance(answer, NoulAnswer):
            return _runs("system_one_unavailable", own_commits=own_commits)
        if answer.probability < SYSTEM_ONE_SKIP_BELOW:
            return _matched(
                "system_one_below_threshold",
                own_commits=own_commits,
                probability=answer.probability,
                model=result.model,
            )
        return _runs(
            "system_one_above_threshold", own_commits=own_commits, probability=answer.probability, model=result.model
        )

    def decide(self, *, previous_head_sha: str, head_sha: str, base_branch: str) -> PushGateDecision:
        """Judge the push from `previous_head_sha`, the last automatically reviewed head, to `head_sha`."""
        previous = self._pr_diff(base_branch, previous_head_sha)
        current = self._pr_diff(base_branch, head_sha)
        if previous is None or current is None:
            return _runs("compare_unavailable")
        # Commits that came in with a merge from the base branch are on the base, so `base...head`
        # leaves them out and only the merge commit itself is new.
        previous_shas = set(previous.commit_shas)
        new_shas = [sha for sha in current.commit_shas if sha not in previous_shas]
        if not new_shas:
            if _same_full_diff(previous, current):
                return _matched("no_new_commits")
            # A force-push back to an earlier commit adds no commit but removes changes the last review saw.
            return _runs("commits_removed")
        own_shas = [sha for sha in new_shas if sha not in current.merge_shas]
        if _same_full_diff(previous, current):
            return _matched("merge_only", own_commits=len(own_shas))
        if not own_shas:
            # A merge that changed the PR's own lines (conflict resolution) carries code nobody reviewed.
            return _runs("interdiff_too_large", own_commits=0)
        if len(own_shas) > MAX_OWN_COMMITS:
            return _runs("interdiff_too_large", own_commits=len(own_shas))
        own_files = self._commit_files(own_shas)
        if own_files is None:
            return _runs("compare_unavailable", own_commits=len(own_shas))
        code_files = [file for file in own_files if not _NON_CODE_FILE.search(file.filename)]
        if not code_files:
            return _matched("docs_only", own_commits=len(own_shas))
        return self._ask_system_one(code_files, own_commits=len(own_shas))
