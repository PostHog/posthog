"""The push gate: decides whether an automatic follow-up review turn is worth its cost.

Every push to an opted-in author's PR starts an automatic turn, and a follow-up turn re-reviews the
whole PR. The gate looks at the PR's own commits since the last automatically reviewed head. It never
sees a first review or a human trigger: the workflow calls it only for automatic follow-ups.

The rules, in order. The first rule that matches gives the reason:

1. `no_new_commits`: the PR has no commit it did not have at the last reviewed head (a force-push back).
2. `reviewhog_commits_only`: the ReviewHog app authored every new commit, for example the fixes the
   resolution stage pushed. Reviewing them again would review ReviewHog's own answer to its review.
3. `merge_only`: the PR's full diff against its base is the same at both heads (a base merge or a
   rebase). A merge that changes the PR's own lines runs the review.
4. `draft`: the PR is a draft and no rule above skips the push. A draft cannot merge, and marking it
   ready starts a turn that reviews everything since the last reviewed head. A draft decision keeps the
   push size the rules above read.
5. `late_follow_up`: the push would start review number `LATE_FOLLOW_UP_RUN_INDEX` of the PR or a later one.
6. `small_pr`: the PR has fewer than `SMALL_PR_REVIEWABLE_LINES_BELOW` reviewable lines, the changed lines
   without generated and vendored files that the lens parts are sized by.
7. `quiet_small_push`: the last review kept no finding and the push changes at most
   `QUIET_PUSH_MAX_OWN_CODE_LINES` own code lines. Skipped pushes add up, so a later push that brings the
   own code lines over the limit runs the review.
   Rules 5 to 7 match the follow-ups that surfaced the least per review in production. A skipped push
   does not move the baseline, so the next review covers its changes. They never take over a gate
   failure, and they do not run on a retry of a turn that already finalized its head.
8. `zero_change`: the reviewed files of the PR are the same as at the last automatically reviewed head. It compares
   the stored PR snapshots of both heads. Rule 3 already skips a push whose whole PR diff is unchanged, so this rule
   catches pushes that change only files the review leaves out, such as generated files and snapshots. The snapshots
   leave lockfiles out too, so a PR with a lockfile at either head never matches, and neither does a PR with a file
   whose patch GitHub left out (`PRChange.comparable`). A push after skipped pushes compares against the same
   baseline. Only a PR in the treatment arm of `reviewhog-zero-change-skip` skips. An unknown comparison (no snapshot
   at either head) never matches.
9. `throttled`: the PR spent its review budget. Each PR has a token bucket (Turner 1986) that holds
   `PUSH_BUDGET.burst` reviews and gets one back every `3600 / PUSH_BUDGET.per_hour` seconds. A push
   that every rule above lets through takes a token, and a push that finds the bucket empty waits:
   the next turn that runs reviews everything since the last reviewed head. This caps bursts of
   pushes, and it never schedules a review on its own.

A turn that passes every rule can review only what changed (`plan_delta_review`): a follow-up from run
`DELTA_BAND_FIRST_RUN_INDEX` on, whose changed reviewable lines are at most `DELTA_BAND_MAX_CHANGE_SHARE` of the PR's
reviewable lines, with no dependency file changed and a comparison the snapshots show in full: no lockfile in the PR,
no file without a patch, and no file that left the PR. The first follow-up always reviews the whole PR. Only a PR in the treatment arm of `reviewhog-delta-band`
runs the delta review; the other arm records that the turn was eligible.

Each rule has its own switch. A rule that is switched off still reports the turn it would skip
(`would_skip`), so production data can calibrate it before it skips anything. Every failure fails
open: the turn runs.

Rules 1 to 3 and the non-code file list follow the offline study in `review-eval/production/push-gate`.
"""

import re
import logging
from dataclasses import replace
from typing import Any, Literal

import requests
from redis.exceptions import RedisError

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubRateLimitError
from posthog.redis import get_client
from posthog.token_bucket import BucketUnavailable, Budget, consume

from products.review_hog.backend.app_identity import posthog_app_login
from products.review_hog.backend.reviewer.artefact_content import PRSnapshotArtefact
from products.review_hog.backend.reviewer.tools.github_client import GitHubAPIError, github_api_request, matches_app_bot
from products.review_hog.backend.reviewer.tools.github_meta import GITHUB_COMPARE_FILES_CAP, PRParser
from products.review_hog.backend.reviewer.tools.single_agent_review import ChangedSinceReview

logger = logging.getLogger(__name__)

# A rule that is off only records the skip it would make, so production data can calibrate it first.
SKIP_NO_NEW_COMMITS = True
SKIP_REVIEWHOG_COMMITS_ONLY = True
SKIP_MERGE_ONLY = True
SKIP_DRAFT = True
SKIP_LATE_FOLLOW_UP = True
SKIP_SMALL_PR = True
SKIP_QUIET_SMALL_PUSH = True
SKIP_THROTTLED = True

# Picked by a replay of production follow-ups in `review-eval/experiments/2026-10-16-follow-up-value`.
LATE_FOLLOW_UP_RUN_INDEX = 9
SMALL_PR_REVIEWABLE_LINES_BELOW = 150
QUIET_PUSH_MAX_OWN_CODE_LINES = 30
# Picked by the replay in `review-eval/experiments/2026-10-14-review-throttle`.
PUSH_BUDGET = Budget(burst=2, per_hour=2)
# Picked by the backtest in `review-eval/experiments/2026-10-26-economics-report` (calibrate67) and fixed for the experiment.
DELTA_BAND_FIRST_RUN_INDEX = 3
DELTA_BAND_MAX_CHANGE_SHARE = 0.03
# A change to one of these files changes what the code runs with, so it never counts as small or as no change. The
# lockfile endings match every lockfile the review snapshots leave out (`PRFilter`), so none of them changes unseen.
_DEPENDENCY_FILE = re.compile(
    r"(^|/)(package\.json|pyproject\.toml|requirements[^/]*\.txt|go\.mod|go\.sum|Cargo\.toml|Gemfile|composer\.json|"
    r"npm-shrinkwrap\.json)$|(\.lock|\.lockb|lock\.json|lock\.ya?ml)$"
)
# Longer than a turn and its retry take, so a retried turn finds that its head paid already.
_PAID_HEAD_TTL_SECONDS = 6 * 3600

# GitHub leaves out the patch of a very large file. A push with more patch text than this runs the review too.
MAX_OWN_PATCH_CHARS = 224_000
# Each new own commit costs one GitHub call to read its patch.
MAX_OWN_COMMITS = 20
# GitHub's compare endpoint pages its commit list at this size.
_COMPARE_COMMITS_PER_PAGE = 100

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

SkipReason = Literal[
    "no_new_commits",
    "reviewhog_commits_only",
    "merge_only",
    "draft",
    "late_follow_up",
    "small_pr",
    "quiet_small_push",
    "throttled",
    "zero_change",
]
RunReason = Literal[
    "no_rule_matched",
    "commits_removed",
    "interdiff_too_large",
    "compare_unavailable",
    "snapshot_unavailable",
]
# Reasons of removed rules. The gate activity returns this decision, and a workflow that replays a history recorded
# before the removal decodes the old reason again, so the type keeps them until no such history is open.
RetiredReason = Literal[
    "docs_only",
    "small_change",
    "system_one_below_threshold",
    "next_push_likely",
    "system_one_above_threshold",
    "system_one_unavailable",
    "small_change_not_stored",
]


@frozen
class PushGateDecision:
    skip: bool
    # Whether a rule matched, switched on or not. A match with its rule off is a shadow decision.
    would_skip: bool
    reason: SkipReason | RunReason | RetiredReason
    own_commits: int | None = None
    # Lines the new own commits change in code files, summed per commit. Set only when the gate read every file.
    own_code_lines: int | None = None
    # Inputs of rules 5 to 7. None when the gate could not read them.
    reviewable_lines: int | None = None
    previous_findings: int | None = None
    # Lines of the PR's own diff that changed since the last automatically reviewed head, in every file. None when unknown.
    pr_changed_lines: int | None = None
    delta_eligible: bool = False
    delta_review: bool = False


def is_dependency_file(path: str) -> bool:
    return _DEPENDENCY_FILE.search(path) is not None


@frozen
class PRChange:
    """How the PR's diff changed since the last automatically reviewed head, as far as the stored snapshots show it."""

    # Diff lines added or removed since that head, in every file of the snapshots.
    changed_lines: int
    changed_reviewable_lines: int
    dependency_changed: bool
    # False when a change can hide from the snapshots, so neither split may act on the comparison.
    comparable: bool

    @classmethod
    def between(cls, earlier: PRSnapshotArtefact, current: PRSnapshotArtefact) -> "PRChange":
        change = ChangedSinceReview.between(earlier.pr_files, current.pr_files)
        changed = {filename for filename, count in change.changed_line_counts.items() if count}
        current_files = {pr_file.filename for pr_file in current.pr_files}
        return cls(
            changed_lines=sum(change.changed_line_counts.values()),
            changed_reviewable_lines=change.reviewable_line_count(),
            dependency_changed=any(is_dependency_file(filename) for filename in changed),
            # The snapshots leave lockfiles out, a file without a patch shows only its line counts, and a delta prompt
            # shows only the files still in the PR.
            comparable=not change.files_without_patch
            and changed <= current_files
            and not any(is_dependency_file(path) for path in [*earlier.skipped_paths, *current.skipped_paths]),
        )


@frozen
class _ChangedFile:
    filename: str
    changes: int
    patch: str | None


@frozen
class _CommitFiles:
    files: list[_ChangedFile]
    # GitHub lists at most one page of files per commit, so a full page may hide more files.
    complete: bool


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
    reviewhog_shas: set[str]


def _rule_enabled(reason: SkipReason) -> bool:
    if reason == "no_new_commits":
        return SKIP_NO_NEW_COMMITS
    if reason == "reviewhog_commits_only":
        return SKIP_REVIEWHOG_COMMITS_ONLY
    if reason == "merge_only":
        return SKIP_MERGE_ONLY
    if reason == "draft":
        return SKIP_DRAFT
    if reason == "late_follow_up":
        return SKIP_LATE_FOLLOW_UP
    if reason == "small_pr":
        return SKIP_SMALL_PR
    if reason == "quiet_small_push":
        return SKIP_QUIET_SMALL_PUSH
    if reason == "throttled":
        return SKIP_THROTTLED
    return False


def _matched(
    reason: SkipReason, *, own_commits: int | None = None, own_code_lines: int | None = None
) -> PushGateDecision:
    return PushGateDecision(
        skip=_rule_enabled(reason),
        would_skip=True,
        reason=reason,
        own_commits=own_commits,
        own_code_lines=own_code_lines,
    )


def _runs(reason: RunReason, *, own_commits: int | None = None, own_code_lines: int | None = None) -> PushGateDecision:
    return PushGateDecision(
        skip=False, would_skip=False, reason=reason, own_commits=own_commits, own_code_lines=own_code_lines
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


def _is_own_commit(commit: dict[str, Any], app_login: str | None) -> bool:
    # Anyone can put the app's noreply email on a commit, so only a GitHub-verified commit with the
    # app as both author and committer counts. Those are the commits the app creates through the API.
    verified = bool(((commit.get("commit") or {}).get("verification") or {}).get("verified"))
    return (
        verified
        and matches_app_bot(commit.get("author"), app_login)
        and matches_app_bot(commit.get("committer"), app_login)
    )


class PushGate:
    def __init__(self, *, repository: str, token: str, installation_id: str | None) -> None:
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
        app_login = posthog_app_login()
        files = _changed_files(comparison)
        if comparison.get("total_commits", 0) > len(commits) or len(files) >= GITHUB_COMPARE_FILES_CAP:
            return None
        return _PRDiff(
            commit_shas=[commit["sha"] for commit in commits],
            merge_shas={commit["sha"] for commit in commits if len(commit.get("parents") or []) > 1},
            files=files,
            reviewhog_shas={commit["sha"] for commit in commits if _is_own_commit(commit, app_login)},
        )

    def _commit_files(self, shas: list[str]) -> _CommitFiles | None:
        files: list[_ChangedFile] = []
        complete = True
        for sha in shas:
            commit = self._get(f"/commits/{sha}", endpoint="/commits/{ref}")
            if commit is None:
                return None
            commit_files = _changed_files(commit)
            complete = complete and len(commit_files) < GITHUB_COMPARE_FILES_CAP
            files.extend(commit_files)
        return _CommitFiles(files=files, complete=complete)

    def decide(self, *, previous_head_sha: str, head_sha: str, base_branch: str) -> PushGateDecision:
        """Judge the push from `previous_head_sha`, the last automatically reviewed head, to `head_sha`.

        Rules 1 to 3 only: `apply_draft_rule` and the functions below add the later rules on top of the result.
        """
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
        if all(sha in current.reviewhog_shas for sha in new_shas):
            return _matched("reviewhog_commits_only", own_commits=len(own_shas))
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
        code_files = [file for file in own_files.files if not _NON_CODE_FILE.search(file.filename)]
        own_code_lines = sum(file.changes for file in code_files) if own_files.complete else None
        patch_chars = sum(len(file.patch or "") for file in code_files)
        if any(file.patch is None for file in code_files) or patch_chars > MAX_OWN_PATCH_CHARS:
            return _runs("interdiff_too_large", own_commits=len(own_shas), own_code_lines=own_code_lines)
        return _runs("no_rule_matched", own_commits=len(own_shas), own_code_lines=own_code_lines)


def apply_draft_rule(decision: PushGateDecision, *, draft: bool) -> PushGateDecision:
    """Rule 4, on top of `PushGate.decide`. A caller that finds the PR ready after all uses the decision it got."""
    if not draft or decision.skip:
        return decision
    return _matched("draft", own_commits=decision.own_commits, own_code_lines=decision.own_code_lines)


# A decision that runs the review because the gate could not judge the push. Rules 5 to 7 keep it.
_FAIL_OPEN_REASONS: frozenset[RunReason] = frozenset(
    {"commits_removed", "interdiff_too_large", "compare_unavailable", "snapshot_unavailable"}
)


def _low_value_reason(
    decision: PushGateDecision, *, run_index: int, reviewable_lines: int | None, previous_findings: int | None
) -> SkipReason | None:
    if run_index >= LATE_FOLLOW_UP_RUN_INDEX:
        return "late_follow_up"
    if reviewable_lines is not None and reviewable_lines < SMALL_PR_REVIEWABLE_LINES_BELOW:
        return "small_pr"
    own_code_lines = decision.own_code_lines
    if previous_findings == 0 and own_code_lines is not None and own_code_lines <= QUIET_PUSH_MAX_OWN_CODE_LINES:
        return "quiet_small_push"
    return None


def apply_follow_up_value_rules(
    decision: PushGateDecision, *, run_index: int, reviewable_lines: int | None, previous_findings: int | None
) -> PushGateDecision:
    """Rules 5 to 7, on top of the draft rule. An input that is None matches no rule, so the push runs.

    `run_index` is the turn this push would start. `previous_findings` is the number of findings the last
    turn kept.
    """
    decision = replace(decision, reviewable_lines=reviewable_lines, previous_findings=previous_findings)
    if decision.skip or decision.reason in _FAIL_OPEN_REASONS:
        return decision
    reason = _low_value_reason(
        decision, run_index=run_index, reviewable_lines=reviewable_lines, previous_findings=previous_findings
    )
    if reason is None:
        return decision
    return replace(decision, skip=_rule_enabled(reason), would_skip=True, reason=reason)


def apply_throttle(decision: PushGateDecision, *, report_id: str, head_sha: str) -> PushGateDecision:
    """Rule 9, last: a push that the rules before it skip takes no token. Without Redis the push runs.

    A head pays once. A failed turn runs again as a new activity or a new child workflow, and a
    retry that charged again could find the bucket empty and drop a review that passed the budget.
    """
    if decision.skip:
        return decision
    paid_key = f"reviewhog_push_budget_paid:{report_id}:{head_sha}"
    client = get_client()
    try:
        first_charge = client.set(paid_key, 1, nx=True, ex=_PAID_HEAD_TTL_SECONDS)
    except RedisError:
        return decision
    if not first_charge:
        return decision
    bucket = consume(f"reviewhog_push_budget:{report_id}", PUSH_BUDGET)
    if isinstance(bucket, BucketUnavailable) or bucket.allowed:
        return decision
    client.delete(paid_key)
    return replace(decision, skip=_rule_enabled("throttled"), would_skip=True, reason="throttled")


def apply_zero_change_rule(decision: PushGateDecision, *, change: PRChange | None, enabled: bool) -> PushGateDecision:
    """Rule 8, after rules 5 to 7. A missing or incomplete comparison runs the push."""
    decision = replace(decision, pr_changed_lines=change.changed_lines if change is not None else None)
    if decision.skip or decision.reason in _FAIL_OPEN_REASONS or change is None or not change.comparable:
        return decision
    if change.changed_lines != 0:
        return decision
    return replace(decision, skip=enabled, would_skip=True, reason="zero_change")


def plan_delta_review(
    decision: PushGateDecision,
    *,
    run_index: int,
    change: PRChange | None,
    reviewable_lines: int | None,
    enabled: bool,
) -> PushGateDecision:
    """Whether a turn that runs reviews only what changed since the last automatically reviewed head.

    Anything unknown (no comparison, a change the snapshots cannot show, a gate that could not judge the push) keeps the
    full review.
    """
    eligible = (
        not decision.skip
        and decision.reason not in _FAIL_OPEN_REASONS
        and change is not None
        and change.comparable
        and not change.dependency_changed
        and run_index >= DELTA_BAND_FIRST_RUN_INDEX
        and reviewable_lines is not None
        and 0 < change.changed_reviewable_lines <= DELTA_BAND_MAX_CHANGE_SHARE * reviewable_lines
    )
    return replace(decision, delta_eligible=eligible, delta_review=eligible and enabled)
