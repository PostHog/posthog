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
4. `docs_only`: the new own commits touch only docs, lockfiles, snapshots, images, and generated files.
5. `small_change`: the push changes at most `SMALL_CHANGE_MAX_NET_CODE_LINES` code lines net, read from
   the compare of the last reviewed head and the push head. The rule matches only when the push head
   descends from the last reviewed head: after a rebase or a force-push the compare does not show the
   push's own change. After `SMALL_CHANGE_MAX_DEFERRALS` deferrals in a row the next small push runs the
   review, so small pushes cannot pile up without a review. A push that every rule lets through to a review
   sets the count back to 0. A push that a rule skips keeps the count, because nothing was reviewed. The
   count is stored only after the last rule has decided, so a draft or throttle skip also keeps it. When
   the count cannot be stored, because another turn of the PR stored one after this turn read it or Redis
   refuses the write, a small push runs the review.
6. `system_one_below_threshold`: System One rates the new own commits below a threshold.
7. `draft`: the PR is a draft and no rule above skips the push. A draft cannot merge, and marking it
   ready starts a turn that reviews everything since the last reviewed head. The rules above still run,
   so a draft decision keeps the System One answer and the push size for calibration.
8. `late_follow_up`: the push would start review number `LATE_FOLLOW_UP_RUN_INDEX` of the PR or a later one.
9. `small_pr`: the PR has fewer than `SMALL_PR_REVIEWABLE_LINES_BELOW` reviewable lines, the changed lines
   without generated and vendored files that the lens parts are sized by.
10. `quiet_small_push`: the last review kept no finding and the push changes at most
   `QUIET_PUSH_MAX_OWN_CODE_LINES` own code lines. Skipped pushes add up, so a later push that brings the
   own code lines over the limit runs the review.
   Rules 8 to 10 match the follow-ups that surfaced the least per review in production. A skipped push
   does not move the baseline, so the next review covers its changes. These rules take over a shadow
   match of the rules above, so a push that only a shadow rule matched can still skip. They never take
   over a gate failure, and they do not run on a retry of a turn that already finalized its head.
11. `next_push_likely`: on a PR that is not a draft, when no rule above matched, another automatic
   follow-up is likely to come. Skipped changes add up and the next review covers them. The chance
   comes from a table fitted offline on the follow-up number and the PR size. Every decision on a
   PR that is not a draft records the chance, also when another rule decided.
12. `throttled`: the PR spent its review budget. Each PR has a token bucket (Turner 1986) that holds
   `PUSH_BUDGET.burst` reviews and gets one back every `3600 / PUSH_BUDGET.per_hour` seconds. A push
   that every rule above lets through takes a token, and a push that finds the bucket empty waits:
   the next turn that runs reviews everything since the last reviewed head. This caps bursts of
   pushes, and it never schedules a review on its own.

Each rule has its own switch. A rule that is switched off still reports the turn it would skip
(`would_skip`), so production data can calibrate it before it skips anything. Every failure fails
open: the turn runs.

The rules, the non-code file list, the System One question, and the state follow the offline study
in `review-eval/production/push-gate`. The threshold is only valid for the state built the same way.
"""

import re
import logging
from dataclasses import replace
from typing import Any, Literal

import requests
from redis.exceptions import RedisError

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubRateLimitError
from posthog.llm.system_one import NoulAnswer, NoulQuestion, SystemOneNotConfigured, SystemOneRequestFailed
from posthog.llm.system_one_client import build_system_one_client
from posthog.redis import get_client
from posthog.token_bucket import BucketUnavailable, Budget, consume

from products.review_hog.backend.app_identity import posthog_app_login
from products.review_hog.backend.reviewer.tools.github_client import GitHubAPIError, github_api_request, matches_app_bot
from products.review_hog.backend.reviewer.tools.github_meta import GITHUB_COMPARE_FILES_CAP, PRParser

logger = logging.getLogger(__name__)

# A rule that is off only records the skip it would make, so production data can calibrate it first.
SKIP_NO_NEW_COMMITS = True
SKIP_REVIEWHOG_COMMITS_ONLY = True
SKIP_MERGE_ONLY = True
SKIP_DOCS_ONLY = False
SKIP_SMALL_CHANGE = False
SKIP_SYSTEM_ONE = False
SKIP_DRAFT = True
SKIP_LATE_FOLLOW_UP = True
SKIP_SMALL_PR = True
SKIP_QUIET_SMALL_PUSH = True
# Before this goes on, `next_push_likely` must defer only once per reviewed head. A skip does not
# advance run_index, so the same chance would match every later push and no review would run.
SKIP_NEXT_PUSH = False
SKIP_THROTTLED = True

NEXT_PUSH_SKIP_AT = 0.85
# Picked by the replay in `review-eval/experiments/2026-10-15-gate-surfacing`.
SMALL_CHANGE_MAX_NET_CODE_LINES = 10
SMALL_CHANGE_MAX_DEFERRALS = 2
# Long enough to span a PR's quiet days, short enough that an abandoned PR's counter goes away.
_SMALL_CHANGE_DEFERRALS_TTL_SECONDS = 3 * 24 * 3600
# Compare-and-set: two turns of one PR can overlap, and each counts from the value it read.
_STORE_STREAK_IF_UNCHANGED = """
if (redis.call('GET', KEYS[1]) or '') ~= ARGV[1] then
    return 0
end
redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
return 1
"""
# Picked by a replay of production follow-ups in `review-eval/experiments/2026-10-16-follow-up-value`.
LATE_FOLLOW_UP_RUN_INDEX = 9
SMALL_PR_REVIEWABLE_LINES_BELOW = 150
QUIET_PUSH_MAX_OWN_CODE_LINES = 30
# Picked by the replay in `review-eval/experiments/2026-10-14-review-throttle`.
PUSH_BUDGET = Budget(burst=2, per_hour=2)
# Longer than a turn and its retry take, so a retried turn finds that its head paid already.
_PAID_HEAD_TTL_SECONDS = 6 * 3600

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

SizeBand = Literal["<=200", "201-1000", ">1000"]


@frozen
class _NextPushCell:
    probability: float
    prs: int


# The chance that another automatic follow-up comes after follow-up number k, from review-eval
# experiments/2026-10-14-draft-deferral (NextPushLookup), fitted on closed PostHog/posthog PRs from
# Oct 8-14 2026. A refit updates these tables by hand. Key 8 holds every follow-up from the eighth on.
_NEXT_PUSH_LAST_FOLLOW_UP = 8
_NEXT_PUSH_MIN_CELL_PRS = 10
_NEXT_PUSH_BY_FOLLOW_UP: dict[int, float] = {
    1: 0.629,
    2: 0.625,
    3: 0.740,
    4: 0.812,
    5: 0.710,
    6: 0.731,
    7: 0.842,
    8: 0.783,
}
_NEXT_PUSH_BY_FOLLOW_UP_AND_SIZE: dict[tuple[int, SizeBand], _NextPushCell] = {
    (1, "<=200"): _NextPushCell(probability=0.559, prs=111),
    (1, "201-1000"): _NextPushCell(probability=0.652, prs=69),
    (1, ">1000"): _NextPushCell(probability=1.000, prs=17),
    (2, "<=200"): _NextPushCell(probability=0.542, prs=72),
    (2, "201-1000"): _NextPushCell(probability=0.667, prs=60),
    (2, ">1000"): _NextPushCell(probability=0.800, prs=20),
    (3, "<=200"): _NextPushCell(probability=0.722, prs=36),
    (3, "201-1000"): _NextPushCell(probability=0.735, prs=49),
    (3, ">1000"): _NextPushCell(probability=0.800, prs=15),
    (4, "<=200"): _NextPushCell(probability=0.667, prs=27),
    (4, "201-1000"): _NextPushCell(probability=0.824, prs=34),
    (4, ">1000"): _NextPushCell(probability=1.000, prs=19),
    (5, "<=200"): _NextPushCell(probability=0.706, prs=17),
    (5, "201-1000"): _NextPushCell(probability=0.606, prs=33),
    (5, ">1000"): _NextPushCell(probability=0.895, prs=19),
    (6, "<=200"): _NextPushCell(probability=0.833, prs=12),
    (6, "201-1000"): _NextPushCell(probability=0.524, prs=21),
    (6, ">1000"): _NextPushCell(probability=0.895, prs=19),
    (7, "<=200"): _NextPushCell(probability=0.900, prs=10),
    (7, "201-1000"): _NextPushCell(probability=0.909, prs=11),
    (7, ">1000"): _NextPushCell(probability=0.765, prs=17),
    (8, "<=200"): _NextPushCell(probability=0.643, prs=28),
    (8, "201-1000"): _NextPushCell(probability=0.719, prs=32),
    (8, ">1000"): _NextPushCell(probability=0.842, prs=101),
}

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

SkipReason = Literal[
    "no_new_commits",
    "reviewhog_commits_only",
    "merge_only",
    "docs_only",
    "small_change",
    "system_one_below_threshold",
    "draft",
    "late_follow_up",
    "small_pr",
    "quiet_small_push",
    "next_push_likely",
    "throttled",
]
RunReason = Literal[
    "commits_removed",
    "system_one_above_threshold",
    "system_one_unavailable",
    "interdiff_too_large",
    "compare_unavailable",
    "snapshot_unavailable",
    "small_change_not_stored",
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
    # Lines the new own commits change in code files, summed per commit. Set only when the gate read every file.
    own_code_lines: int | None = None
    next_push_probability: float | None = None
    # Lines the push changes in code files between the last reviewed head and this head.
    net_code_lines: int | None = None
    # Small-change deferrals in a row after this decision. None when the gate did not read the counter.
    small_change_deferrals: int | None = None
    # Inputs of rules 8 to 10. None when the gate could not read them.
    reviewable_lines: int | None = None
    previous_findings: int | None = None


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
    if reason == "docs_only":
        return SKIP_DOCS_ONLY
    if reason == "small_change":
        return SKIP_SMALL_CHANGE
    if reason == "draft":
        return SKIP_DRAFT
    if reason == "late_follow_up":
        return SKIP_LATE_FOLLOW_UP
    if reason == "small_pr":
        return SKIP_SMALL_PR
    if reason == "quiet_small_push":
        return SKIP_QUIET_SMALL_PUSH
    if reason == "next_push_likely":
        return SKIP_NEXT_PUSH
    if reason == "throttled":
        return SKIP_THROTTLED
    return SKIP_SYSTEM_ONE


def _size_band(pr_lines: int) -> SizeBand:
    if pr_lines <= 200:
        return "<=200"
    if pr_lines <= 1000:
        return "201-1000"
    return ">1000"


def next_push_probability(*, follow_up: int, pr_lines: int) -> float | None:
    """The chance that another automatic follow-up comes after follow-up number `follow_up` (1-based).

    `pr_lines` is the PR's additions plus deletions.
    """
    if follow_up < 1:
        return None
    follow_up = min(follow_up, _NEXT_PUSH_LAST_FOLLOW_UP)
    cell = _NEXT_PUSH_BY_FOLLOW_UP_AND_SIZE.get((follow_up, _size_band(pr_lines)))
    if cell is not None and cell.prs >= _NEXT_PUSH_MIN_CELL_PRS:
        return cell.probability
    return _NEXT_PUSH_BY_FOLLOW_UP[follow_up]


def _matched(
    reason: SkipReason,
    *,
    own_commits: int | None = None,
    probability: float | None = None,
    model: str | None = None,
    own_code_lines: int | None = None,
    net_code_lines: int | None = None,
    small_change_deferrals: int | None = None,
) -> PushGateDecision:
    return PushGateDecision(
        skip=_rule_enabled(reason),
        would_skip=True,
        reason=reason,
        probability=probability,
        model=model,
        own_commits=own_commits,
        own_code_lines=own_code_lines,
        net_code_lines=net_code_lines,
        small_change_deferrals=small_change_deferrals,
    )


def _runs(
    reason: RunReason,
    *,
    own_commits: int | None = None,
    probability: float | None = None,
    model: str | None = None,
    own_code_lines: int | None = None,
) -> PushGateDecision:
    return PushGateDecision(
        skip=False,
        would_skip=False,
        reason=reason,
        probability=probability,
        model=model,
        own_commits=own_commits,
        own_code_lines=own_code_lines,
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
    def __init__(self, *, team_id: int, repository: str, token: str, installation_id: str | None) -> None:
        self.team_id = team_id
        self.repository = repository
        self._token = token
        self._installation_id = installation_id
        # The counter value the last read saw, so the store can tell whether another turn moved it.
        self._small_change_seen = ""

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

    def _net_code_lines(self, previous_head_sha: str, head_sha: str) -> int | None:
        """Code lines the push changes between the two heads, or None when GitHub does not give every count."""
        comparison = self._get(
            f"/compare/{previous_head_sha}...{head_sha}",
            endpoint="/compare/{basehead}",
            params={"per_page": _COMPARE_COMMITS_PER_PAGE},
        )
        if comparison is None:
            return None
        # A three-dot compare starts at the merge base, so its files are the push's change only when
        # the push head descends from the last reviewed head.
        merge_base_sha = (comparison.get("merge_base_commit") or {}).get("sha")
        if comparison.get("status") != "ahead" or merge_base_sha != previous_head_sha:
            return None
        files: list[dict[str, Any]] = comparison.get("files") or []
        if len(files) >= GITHUB_COMPARE_FILES_CAP:
            return None
        lines = 0
        for file in files:
            if _NON_CODE_FILE.search(file["filename"]):
                continue
            additions = file.get("additions")
            deletions = file.get("deletions")
            if additions is None or deletions is None:
                return None
            lines += additions + deletions
        return lines

    def _small_change_key(self, pr_number: int) -> str:
        return f"reviewhog_small_change_deferrals:{self.repository}:{pr_number}"

    def _small_change_streak_after(self, *, pr_number: int, head_sha: str, small: bool) -> int | None:
        """The small-change deferrals in a row after this push, or None when Redis is unavailable.

        A small push below the limit adds one. Any other push sets the count to 0, which also makes the
        push after `SMALL_CHANGE_MAX_DEFERRALS` deferrals run the review. A retried turn at the same head
        gets the count of its first attempt, so a retry does not count the push again.
        """
        try:
            stored = get_client().get(self._small_change_key(pr_number))
        except RedisError:
            return None
        self._small_change_seen = stored.decode() if stored else ""
        stored_head, stored_count = self._small_change_seen.split(":") if stored else ("", "0")
        if stored_head == head_sha:
            return int(stored_count)
        if small and int(stored_count) < SMALL_CHANGE_MAX_DEFERRALS:
            return int(stored_count) + 1
        return 0

    def _ask_system_one(self, code_files: list[_ChangedFile], own_commits: int, lines_known: bool) -> PushGateDecision:
        lines = sum(file.changes for file in code_files) if lines_known else None
        if any(file.patch is None for file in code_files):
            return _runs("interdiff_too_large", own_commits=own_commits, own_code_lines=lines)
        state = "\n\n".join(f"--- {file.filename}\n{file.patch}" for file in code_files)
        if len(state) > MAX_STATE_CHARS:
            return _runs("interdiff_too_large", own_commits=own_commits, own_code_lines=lines)
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
            return _runs("system_one_unavailable", own_commits=own_commits, own_code_lines=lines)
        answer = result.answers[_QUESTION_ID]
        if not isinstance(answer, NoulAnswer):
            return _runs("system_one_unavailable", own_commits=own_commits, own_code_lines=lines)
        if answer.probability < SYSTEM_ONE_SKIP_BELOW:
            return _matched(
                "system_one_below_threshold",
                own_commits=own_commits,
                probability=answer.probability,
                model=result.model,
                own_code_lines=lines,
            )
        return _runs(
            "system_one_above_threshold",
            own_commits=own_commits,
            probability=answer.probability,
            model=result.model,
            own_code_lines=lines,
        )

    def _judge(self, *, previous_head_sha: str, head_sha: str, base_branch: str, pr_number: int) -> PushGateDecision:
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
        if not code_files:
            return _matched("docs_only", own_commits=len(own_shas), own_code_lines=0 if own_files.complete else None)
        net_code_lines = self._net_code_lines(previous_head_sha, head_sha)
        small = net_code_lines is not None and 1 <= net_code_lines <= SMALL_CHANGE_MAX_NET_CODE_LINES
        # The count moves in shadow mode too, so the logged would_skip sequence follows what live mode would
        # do. In shadow mode the review still runs and moves the baseline, so net lines count from the
        # previous push and do not add up over the deferred pushes as they would in live mode.
        deferrals = self._small_change_streak_after(pr_number=pr_number, head_sha=head_sha, small=small)
        if small and deferrals is not None and deferrals > 0:
            return _matched(
                "small_change",
                own_commits=len(own_shas),
                own_code_lines=sum(file.changes for file in code_files) if own_files.complete else None,
                net_code_lines=net_code_lines,
                small_change_deferrals=deferrals,
            )
        decision = self._ask_system_one(code_files, own_commits=len(own_shas), lines_known=own_files.complete)
        return replace(decision, net_code_lines=net_code_lines, small_change_deferrals=deferrals)

    def decide(self, *, previous_head_sha: str, head_sha: str, base_branch: str, pr_number: int) -> PushGateDecision:
        """Judge the push from `previous_head_sha`, the last automatically reviewed head, to `head_sha`.

        Rules 1 to 6 only: `apply_draft_rule` adds rule 7 on top of the result. The decision carries the
        small-change count, and `record_small_change_streak` stores it after the last rule has decided.
        """
        decision = self._judge(
            previous_head_sha=previous_head_sha, head_sha=head_sha, base_branch=base_branch, pr_number=pr_number
        )
        if decision.skip:
            return decision
        if decision.small_change_deferrals is not None:
            return decision
        deferrals = self._small_change_streak_after(pr_number=pr_number, head_sha=head_sha, small=False)
        return replace(decision, small_change_deferrals=deferrals)

    def record_small_change_streak(
        self, decision: PushGateDecision, *, pr_number: int, head_sha: str
    ) -> PushGateDecision:
        """Store the small-change count of the final decision, and return the decision that applies.

        The store succeeds only when the counter still holds the value `decide` read. When another turn
        moved it first, or the write fails, the next push would count from the old value, so a small-change
        match runs the review.
        """
        # Apart from `decide`, because the draft and throttle rules run later and can still skip the review.
        if decision.small_change_deferrals is None:
            return decision
        # A rule skipped the review, so the baseline did not move and the stored count stays.
        if decision.skip and decision.reason != "small_change":
            return decision
        try:
            stored = get_client().register_script(_STORE_STREAK_IF_UNCHANGED)(
                keys=[self._small_change_key(pr_number)],
                args=[
                    self._small_change_seen,
                    f"{head_sha}:{decision.small_change_deferrals}",
                    _SMALL_CHANGE_DEFERRALS_TTL_SECONDS,
                ],
            )
        except RedisError:
            stored = 0
        if stored or decision.reason != "small_change":
            return decision
        return replace(decision, skip=False, would_skip=False, reason="small_change_not_stored")


def apply_draft_rule(decision: PushGateDecision, *, draft: bool) -> PushGateDecision:
    """Rule 7, on top of `PushGate.decide`. A caller that finds the PR ready after all uses the decision it got."""
    if not draft or decision.skip:
        return decision
    return _matched(
        "draft",
        own_commits=decision.own_commits,
        probability=decision.probability,
        model=decision.model,
        own_code_lines=decision.own_code_lines,
        net_code_lines=decision.net_code_lines,
        small_change_deferrals=decision.small_change_deferrals,
    )


# A decision that runs the review because the gate could not judge the push. Rules 8 to 10 keep it.
_FAIL_OPEN_REASONS: frozenset[RunReason] = frozenset(
    {"commits_removed", "system_one_unavailable", "interdiff_too_large", "compare_unavailable", "snapshot_unavailable"}
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
    """Rules 8 to 10, on top of the draft rule. An input that is None matches no rule, so the push runs.

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


def apply_next_push_rule(
    decision: PushGateDecision, *, follow_up: int | None, pr_lines: int | None
) -> PushGateDecision:
    """Rule 11, only for a PR that is not a draft. It records the chance also when another rule decided.

    `follow_up` is the number of this automatic follow-up (1-based) and `pr_lines` is the PR's
    additions plus deletions. Both are None when they are unknown.
    """
    probability = None
    if follow_up is not None and pr_lines is not None:
        probability = next_push_probability(follow_up=follow_up, pr_lines=pr_lines)
    if probability is not None and probability >= NEXT_PUSH_SKIP_AT and not decision.would_skip:
        decision = replace(decision, skip=_rule_enabled("next_push_likely"), would_skip=True, reason="next_push_likely")
    return replace(decision, next_push_probability=probability)


def apply_throttle(decision: PushGateDecision, *, report_id: str, head_sha: str) -> PushGateDecision:
    """Rule 12, last: a push that the rules before it skip takes no token. Without Redis the push runs.

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
