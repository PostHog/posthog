"""Move the baseline ledger along the default branch, and land approvals as their pull requests merge.

`advance` is the only writer of ledger positions and of entries after the seed. It reads GitHub
first and writes afterwards in one transaction under the ledger lock, so a slow GitHub never holds
the lock, and a failed read writes nothing.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from uuid import UUID

from django.db import transaction
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority

from ..db import WRITER_DB
from ..facade.enums import BaselineApprovalState, BaselineEntrySource, BaselineEvidence, BaselineMode, RunStatus
from ..models import BaselineApproval, BaselineCommit, BaselineEntry, Repo, Run
from . import baseline_approvals, baseline_record, errors, github_api, ledger, quarantine

logger = structlog.get_logger(__name__)

# GitHub can list a squash commit on the default branch before it shows its pull request as merged.
# Past this window a commit that still does not resolve is left alone, and the hourly pass over
# open approvals lands a pull request that merged after all.
UNRESOLVED_RETRY_WINDOW = timedelta(hours=24)
# GitHub's lag right after a merge lasts seconds. Only a commit recorded this recently starts the
# quick follow-up passes after a push, so one that stays unresolved longer waits for the periodic task.
RECENTLY_UNRESOLVED_WINDOW = timedelta(minutes=2)

DETAIL_ALREADY_IN_BASELINE = "The baseline already had this picture when the pull request merged"
DETAIL_LATER_MERGE_CHANGED_IT = "A later merge changed this baseline before the pull request was recorded"
DETAIL_BASELINE_MOVED = "The baseline changed after this approval. Approve the story again in a new pull request"
DETAIL_QUARANTINED = "Added to the baseline without a check because the story is quarantined"
DETAIL_NOT_REPRODUCED = "Not added because the last run before the merge did not reproduce the approved picture"
DETAIL_REPRODUCED = "Added to the baseline after the last run before the merge reproduced it"
DETAIL_UNVERIFIED = "Added to the baseline without a run that confirmed the picture"
DETAIL_NOT_RENDERED_AT_MERGE = (
    "Not added because no run rendered this picture at the merged commit. Approve it again in a pull request "
    "whose run renders the story"
)
DETAIL_SEEDED_AFTER_MERGE = (
    "The baseline was seeded after this pull request merged and holds another picture. Approve the story "
    "again in a new pull request"
)
DETAIL_CLOSED_WITHOUT_MERGE = "The pull request closed without merging"
DETAIL_MERGED_ELSEWHERE = (
    "The pull request merged into another branch, and no pull request brought its commits to the default "
    "branch within 14 days"
)

# A pull request merged into another branch can still reach the default branch through a pull
# request that carries its commits, so its approvals wait this long before they are abandoned.
MERGED_ELSEWHERE_WINDOW = timedelta(days=14)

_PULL_REQUEST_SUFFIX_RE = re.compile(r"\(#(\d+)\)")


def named_pull_request(subject: str) -> int | None:
    """The pull request a squash subject names. The last `(#N)` counts, as GitHub appends it."""
    numbers = _PULL_REQUEST_SUFFIX_RE.findall(subject)
    if not numbers:
        return None
    return int(numbers[-1])


@frozen
class AdvanceResult:
    commits_added: int
    commits_resolved_late: int
    approvals_landed: int
    commits_unresolved_recently: int


@frozen
class _Landing:
    """A verified merge of one pull request, with the evidence checks done before the lock."""

    pr_number: int
    merged_head_sha: str
    # The evidence commit each approval had when it was checked. A different one under the lock
    # means new evidence arrived, and the check has to run again.
    checked_evidence: dict[UUID, str]
    evidence_applies: frozenset[UUID]

    def covers(self, approvals: list[BaselineApproval]) -> bool:
        return all(self.checked_evidence.get(approval.id) == approval.evidence_commit_sha for approval in approvals)


@frozen
class _CommitPlan:
    pr_number: int | None
    resolved: bool
    landing: _Landing | None = None


@frozen
class LandingVerdict:
    state: BaselineApprovalState
    detail: str
    appends_entry: bool


def _parents_first(approvals: list[BaselineApproval]) -> list[BaselineApproval]:
    """The approvals of one snapshot, each stack parent before its child, otherwise in the given order."""
    remaining = list(approvals)
    ordered: list[BaselineApproval] = []
    while remaining:
        pending_hashes = {approval.content_hash for approval in remaining}
        ready = [approval for approval in remaining if approval.effective_base_hash not in pending_hashes]
        # A cycle (a child that restores the parent's base) has no parent first, so keep approval order.
        chosen = ready[0] if ready else remaining[0]
        ordered.append(chosen)
        remaining.remove(chosen)
    return ordered


def landing_order(approvals: list[BaselineApproval]) -> list[BaselineApproval]:
    """Each stack parent before the child approval whose base is the parent's hash.

    The later entry wins at one position, so a child that landed first would be overwritten by
    its parent, and the parent's own base check would then fail against the child's hash.
    Approvals of different snapshots never depend on each other, so the stack order runs per snapshot
    (in the order of each snapshot's first approval) and a landing of many snapshots, which holds the
    ledger lock, does not compare every approval with every other.
    """
    by_snapshot: dict[tuple[str, str], list[BaselineApproval]] = {}
    for approval in sorted(approvals, key=lambda approval: (approval.approved_at, approval.id)):
        by_snapshot.setdefault((approval.run_type, approval.identifier), []).append(approval)
    ordered: list[BaselineApproval] = []
    for snapshot_approvals in by_snapshot.values():
        ordered.extend(_parents_first(snapshot_approvals))
    return ordered


def landing_verdict(
    approval: BaselineApproval,
    current_hash: str,
    *,
    landing_pr_number: int,
    merged_head_sha: str,
    evidence_applies: bool,
    quarantined: bool,
    has_newer_entry: bool,
    position: int,
) -> LandingVerdict | None:
    """The landing table's verdict, or None for another pull request's approval that stays open."""
    # An absent identifier and an approved removal both read as the empty hash.
    if current_hash == approval.content_hash:
        return LandingVerdict(
            state=BaselineApprovalState.PROMOTED, detail=DETAIL_ALREADY_IN_BASELINE, appends_entry=False
        )
    # Only a merge at or before the seed commit lands at position 0, and the seed already holds a later baseline.
    if position == 0:
        return LandingVerdict(
            state=BaselineApprovalState.CONFLICTED, detail=DETAIL_SEEDED_AFTER_MERGE, appends_entry=False
        )
    if has_newer_entry:
        return LandingVerdict(
            state=BaselineApprovalState.CONFLICTED, detail=DETAIL_LATER_MERGE_CHANGED_IT, appends_entry=False
        )
    if not baseline_approvals.base_still_holds(approval, current_hash):
        return LandingVerdict(state=BaselineApprovalState.CONFLICTED, detail=DETAIL_BASELINE_MOVED, appends_entry=False)
    if quarantined:
        return LandingVerdict(state=BaselineApprovalState.PROMOTED, detail=DETAIL_QUARANTINED, appends_entry=True)
    if evidence_applies:
        if approval.evidence == BaselineEvidence.NOT_REPRODUCED:
            return LandingVerdict(state=BaselineApprovalState.VOIDED, detail=DETAIL_NOT_REPRODUCED, appends_entry=False)
        return LandingVerdict(state=BaselineApprovalState.PROMOTED, detail=DETAIL_REPRODUCED, appends_entry=True)
    # Without evidence only a run at the merged head shows that the merge renders the picture. A pull
    # request can approve a change, then drop the code that renders it and merge without any run.
    if approval.pr_number != landing_pr_number:
        return None
    if merged_head_sha in (approval.commit_sha, approval.carried_commit_sha):
        return LandingVerdict(state=BaselineApprovalState.PROMOTED, detail=DETAIL_UNVERIFIED, appends_entry=True)
    return LandingVerdict(state=BaselineApprovalState.VOIDED, detail=DETAIL_NOT_RENDERED_AT_MERGE, appends_entry=False)


class _LedgerAdvancer:
    """Reads and lands for one repo. Caches what GitHub said for the length of one call.

    Every GitHub read of the call is made at `priority`.
    """

    def __init__(self, repo: Repo, priority: Priority = Priority.CRITICAL) -> None:
        self.repo = repo
        self.priority = priority
        self.now = timezone.now()
        self.commits_added = 0
        self.commits_resolved_late = 0
        self.approvals_landed = 0
        self.commits_unresolved_recently = 0
        self._default_branch: str | None = None
        self._pull_requests: dict[int, github_api.PullRequestState] = {}
        self._evidence_contains: dict[tuple[str, str], bool | None] = {}
        self._open_approvals: list[BaselineApproval] | None = None
        self._run_candidates: dict[int, set[UUID]] = {}

    def result(self) -> AdvanceResult:
        return AdvanceResult(
            commits_added=self.commits_added,
            commits_resolved_late=self.commits_resolved_late,
            approvals_landed=self.approvals_landed,
            commits_unresolved_recently=self.commits_unresolved_recently,
        )

    def _require_default_branch(self) -> str:
        if self._default_branch is None:
            self._default_branch = github_api.default_branch_name(self.repo, self.priority)
            if self._default_branch is None:
                raise errors.BaselineAdvanceError(f"GitHub did not name the default branch of {self.repo}.")
        return self._default_branch

    def _require_pull_request(self, pr_number: int) -> github_api.PullRequestState:
        if pr_number not in self._pull_requests:
            pull_request = github_api.pull_request_state(self.repo, pr_number, self.priority)
            if pull_request is None:
                raise errors.BaselineAdvanceError(f"GitHub did not return pull request #{pr_number} of {self.repo}.")
            self._pull_requests[pr_number] = pull_request
        return self._pull_requests[pr_number]

    def _read_open_approvals(self) -> list[BaselineApproval]:
        self._open_approvals = list(
            BaselineApproval.objects.using(WRITER_DB)
            .filter(repo_id=self.repo.id, state=BaselineApprovalState.OPEN)
            .order_by("approved_at", "id")
        )
        return self._open_approvals

    def _known_open_approvals(self) -> list[BaselineApproval]:
        if self._open_approvals is None:
            return self._read_open_approvals()
        return self._open_approvals

    def _read_run_candidates(self, pr_numbers: set[int]) -> None:
        """The approvals each pull request's newest completed run per run type counted, in one query."""
        missing = pr_numbers - set(self._run_candidates)
        if not missing:
            return
        for pr_number in missing:
            self._run_candidates[pr_number] = set()
        newest_runs = (
            Run.objects.using(WRITER_DB)
            .filter(repo_id=self.repo.id, pr_number__in=missing, status=RunStatus.COMPLETED)
            .order_by("pr_number", "run_type", "-created_at")
            .distinct("pr_number", "run_type")
            .only("id", "pr_number", "run_type", "metadata")
        )
        for run in newest_runs:
            record = baseline_record.record_for_run(run)
            if record is not None and run.pr_number is not None:
                self._run_candidates[run.pr_number].update(record.candidate_approval_ids)

    def landing_set(self, pr_number: int) -> list[BaselineApproval]:
        """The open approvals of the pull request, and those its newest completed runs counted as candidates."""
        self._read_run_candidates({pr_number})
        open_approvals = self._known_open_approvals()
        candidate_ids = self._run_candidates[pr_number]
        return [
            approval for approval in open_approvals if approval.pr_number == pr_number or approval.id in candidate_ids
        ]

    def _evidence_contains_head(self, merged_head_sha: str, evidence_commit_sha: str) -> bool | None:
        key = (merged_head_sha, evidence_commit_sha)
        if key not in self._evidence_contains:
            self._evidence_contains[key] = github_api.commit_ancestry(
                self.repo, merged_head_sha, evidence_commit_sha, self.priority
            )
        return self._evidence_contains[key]

    def plan_landing(self, pr_number: int, merged_head_sha: str) -> _Landing | None:
        """The landing of one merged pull request, or None when GitHub cannot say which evidence applies.

        Landing on an unknown answer would add an approval that its evidence voids, so the caller
        leaves the commit unresolved and a later pass asks again.
        """
        approvals = self.landing_set(pr_number)
        evidence_applies: set[UUID] = set()
        for approval in approvals:
            if not approval.evidence or not approval.evidence_commit_sha:
                continue
            contains_head = self._evidence_contains_head(merged_head_sha, approval.evidence_commit_sha)
            if contains_head is None:
                return None
            if contains_head:
                evidence_applies.add(approval.id)
        return _Landing(
            pr_number=pr_number,
            merged_head_sha=merged_head_sha,
            checked_evidence={approval.id: approval.evidence_commit_sha for approval in approvals},
            evidence_applies=frozenset(evidence_applies),
        )

    def _merged_here(self, pull_request: github_api.PullRequestState, commit_sha: str) -> bool:
        return (
            pull_request.merged
            and pull_request.merge_commit_sha == commit_sha
            and pull_request.base_ref == self._require_default_branch()
        )

    def _plan_from_commit_pulls(self, commit_sha: str, first_seen_at: datetime) -> _CommitPlan:
        pull_requests = github_api.merged_pull_requests_for_commit(self.repo, commit_sha, self.priority)
        if pull_requests is None:
            raise errors.BaselineAdvanceError(f"GitHub did not list the pull requests of commit {commit_sha}.")
        default_branch = self._require_default_branch()
        for pull_request in pull_requests:
            if pull_request.base_ref == default_branch and pull_request.head_sha:
                landing = self.plan_landing(pull_request.number, pull_request.head_sha)
                return _CommitPlan(pr_number=pull_request.number, resolved=landing is not None, landing=landing)
        # GitHub links a new commit to its pull request with a short delay, so an empty list for a commit
        # seen moments ago can still change. Without an open approval nothing can land, so nothing waits.
        seen_recently = first_seen_at >= self.now - RECENTLY_UNRESOLVED_WINDOW
        if not pull_requests and seen_recently and self._known_open_approvals():
            return _CommitPlan(pr_number=None, resolved=False)
        return _CommitPlan(pr_number=None, resolved=True)

    def plan_commit(self, commit_sha: str, named_pr: int | None, first_seen_at: datetime) -> _CommitPlan:
        if named_pr is None:
            return self._plan_from_commit_pulls(commit_sha, first_seen_at)
        # Most commits stop here: a pull request without approvals needs no proof that it is the one.
        if not self.landing_set(named_pr):
            return _CommitPlan(pr_number=named_pr, resolved=True)
        pull_request = self._require_pull_request(named_pr)
        if self._merged_here(pull_request, commit_sha) and pull_request.head_sha:
            landing = self.plan_landing(named_pr, pull_request.head_sha)
            return _CommitPlan(pr_number=named_pr, resolved=landing is not None, landing=landing)
        if pull_request.state == "open":
            return _CommitPlan(pr_number=named_pr, resolved=False)
        return self._plan_from_commit_pulls(commit_sha, first_seen_at)

    def _forget(self, approval_ids: set[UUID]) -> None:
        if self._open_approvals is not None:
            self._open_approvals = [other for other in self._open_approvals if other.id not in approval_ids]

    def land(self, landing: _Landing, approvals: list[BaselineApproval], position: int, commit_sha: str) -> None:
        """Apply the landing table to each approval, with a fixed number of queries per run type.

        The caller holds the ledger lock. Every writer of approvals takes it too, so the approvals
        read under it are still open, and the writes need no per-row check.
        """
        run_types = {approval.run_type for approval in approvals}
        identifiers = {
            run_type: {approval.identifier for approval in approvals if approval.run_type == run_type}
            for run_type in run_types
        }
        quarantined = {
            run_type: set(
                quarantine.active_quarantined_identifiers(self.repo.id, self.repo.team_id, run_type, using=WRITER_DB)
            )
            for run_type in run_types
        }
        # Read at the landing position, not below it, so entries an earlier landing wrote at this
        # position count as the current baseline.
        current = {
            run_type: ledger.hashes_at(self.repo.id, run_type, identifiers[run_type], position)
            for run_type in run_types
        }
        newer = {
            run_type: ledger.identifiers_with_newer_entries(self.repo.id, run_type, identifiers[run_type], position)
            for run_type in run_types
        }
        landed_by_verdict: dict[tuple[BaselineApprovalState, str], list[UUID]] = {}
        entries: list[BaselineEntry] = []
        for approval in landing_order(approvals):
            current_hash = current[approval.run_type].get(approval.identifier, "")
            verdict = landing_verdict(
                approval,
                current_hash,
                landing_pr_number=landing.pr_number,
                merged_head_sha=landing.merged_head_sha,
                evidence_applies=approval.id in landing.evidence_applies,
                quarantined=approval.identifier in quarantined[approval.run_type],
                has_newer_entry=approval.identifier in newer[approval.run_type],
                position=position,
            )
            # Stays open and cached, because its own pull request can merge later in this same pass.
            if verdict is None:
                continue
            landed_by_verdict.setdefault((verdict.state, verdict.detail), []).append(approval.id)
            if verdict.appends_entry:
                entries.append(
                    BaselineEntry(
                        repo=self.repo,
                        team_id=self.repo.team_id,
                        run_type=approval.run_type,
                        identifier=approval.identifier,
                        content_hash=approval.content_hash,
                        previous_hash=current_hash,
                        position=position,
                        commit_sha=commit_sha,
                        source=BaselineEntrySource.MERGE,
                        approval=approval,
                        pr_number=approval.pr_number,
                    )
                )
                # A stack child later in the order compares against its parent's hash.
                current[approval.run_type][approval.identifier] = approval.content_hash
            logger.info(
                "visual_review.baseline_approval_landed",
                repo_id=str(self.repo.id),
                approval_id=str(approval.id),
                pr_number=approval.pr_number,
                landing_pr_number=landing.pr_number,
                position=position,
                state=verdict.state,
            )

        for (state, detail), approval_ids in landed_by_verdict.items():
            BaselineApproval.objects.using(WRITER_DB).filter(team_id=self.repo.team_id, id__in=approval_ids).update(
                state=state,
                detail=detail,
                landed_position=position,
                landed_commit_sha=commit_sha,
                resolved_at=self.now,
                updated_at=self.now,
            )
        ledger.append_entries(entries)
        landed_ids = {approval_id for approval_ids in landed_by_verdict.values() for approval_id in approval_ids}
        self.approvals_landed += len(landed_ids)
        self._forget(landed_ids)

    def _approvals_to_land(self, plan: _CommitPlan) -> list[BaselineApproval] | None:
        """The approvals to land under the lock, or None when the commit has to stay unresolved.

        Approvals or evidence that changed after the reads outside the lock leave the commit
        unresolved, so the retry checks them again instead of landing on stale answers.
        """
        if not plan.resolved:
            return None
        if plan.pr_number is None:
            return []
        approvals = self.landing_set(plan.pr_number)
        if not approvals:
            return []
        if plan.landing is None or not plan.landing.covers(approvals):
            return None
        return approvals

    def _new_commits(self, cursor_sha: str, head_sha: str) -> list[github_api.ComparedCommit]:
        """The first-parent commits after the cursor up to the head, oldest first."""
        comparison = github_api.compare_commits(self.repo, cursor_sha, head_sha, self.priority)
        if comparison is None:
            raise errors.BaselineAdvanceError(f"GitHub did not compare {cursor_sha} with {head_sha} in {self.repo}.")
        if not comparison.complete:
            raise errors.BaselineCommitGapTooLargeError(
                f"The default branch of {self.repo} is more than {github_api.MAX_COMPARE_COMMITS} commits past "
                "the baseline ledger. Seed it again with `visual_review_baseline_ledger seed --from-ledger`."
            )
        commits_by_sha = {commit.sha: commit for commit in comparison.commits}
        chain: list[github_api.ComparedCommit] = []
        sha = head_sha
        while sha != cursor_sha:
            commit = commits_by_sha.get(sha)
            if commit is None or not commit.parent_shas:
                raise errors.BaselineBranchRewrittenError(
                    f"The baseline ledger of {self.repo} ends at {cursor_sha}, which is not on the default "
                    "branch's first-parent line. Seed it again with `visual_review_baseline_ledger seed --from-ledger`."
                )
            chain.append(commit)
            sha = commit.parent_shas[0]
        chain.reverse()
        return chain

    def _write_new_commits(self, plans: list[tuple[github_api.ComparedCommit, _CommitPlan]]) -> None:
        with transaction.atomic(using=WRITER_DB):
            ledger.lock_ledger(self.repo.id)
            # Approvals can change while GitHub is read, and `covers` compares against this read.
            self._read_open_approvals()
            head = ledger.cursor(self.repo.id)
            for commit, plan in plans:
                # Another caller wrote this commit while this one read GitHub.
                if ledger.position_of(self.repo.id, commit.sha) is not None:
                    continue
                if head is None or commit.parent_shas[0] != head.commit_sha:
                    logger.warning(
                        "visual_review.baseline_ledger_moved_during_advance",
                        repo_id=str(self.repo.id),
                        commit_sha=commit.sha,
                    )
                    return
                approvals = self._approvals_to_land(plan)
                position = head.position + 1
                head = ledger.append_commit(
                    self.repo,
                    position=position,
                    commit_sha=commit.sha,
                    pr_number=plan.pr_number,
                    resolved=approvals is not None,
                )
                self.commits_added += 1
                if approvals and plan.landing is not None:
                    self.land(plan.landing, approvals, position, commit.sha)

    def _retry_unresolved(self) -> None:
        unresolved = list(
            BaselineCommit.objects.using(WRITER_DB)
            .filter(repo_id=self.repo.id, resolved=False, created_at__gte=self.now - UNRESOLVED_RETRY_WINDOW)
            .order_by("position")
        )
        if not unresolved:
            return
        self._read_run_candidates({commit.pr_number for commit in unresolved if commit.pr_number is not None})
        plans = [
            (commit, self.plan_commit(commit.commit_sha, commit.pr_number, commit.created_at)) for commit in unresolved
        ]
        with transaction.atomic(using=WRITER_DB):
            ledger.lock_ledger(self.repo.id)
            self._read_open_approvals()
            for commit, plan in plans:
                approvals = self._approvals_to_land(plan)
                if approvals is None:
                    if commit.created_at >= self.now - RECENTLY_UNRESOLVED_WINDOW:
                        self.commits_unresolved_recently += 1
                    continue
                updated = (
                    BaselineCommit.objects.using(WRITER_DB)
                    .filter(id=commit.id, resolved=False)
                    .update(resolved=True, pr_number=plan.pr_number)
                )
                if not updated:
                    continue
                self.commits_resolved_late += 1
                if approvals and plan.landing is not None:
                    self.land(plan.landing, approvals, commit.position, commit.commit_sha)

    def advance(self, cursor_sha: str) -> None:
        head_sha = github_api.default_branch_head_sha(self.repo, self.priority)
        if head_sha is None:
            raise errors.BaselineAdvanceError(f"GitHub did not name the default branch head of {self.repo}.")
        if head_sha != cursor_sha:
            commits = [
                (commit, named_pull_request(commit.subject)) for commit in self._new_commits(cursor_sha, head_sha)
            ]
            self._read_run_candidates({named_pr for _commit, named_pr in commits if named_pr is not None})
            plans = [(commit, self.plan_commit(commit.sha, named_pr, self.now)) for commit, named_pr in commits]
            self._write_new_commits(plans)
        self._retry_unresolved()

    def _landing_commit(self, merge_commit_sha: str, seed: BaselineCommit) -> BaselineCommit | None:
        """The ledger commit a merged pull request lands at, or None when this pass cannot place it.

        A merge commit without a position is either past the cursor, and the next advance lands it,
        or older than the seed, which carried the ledger from before that merge. The approval then
        lands at position 0, where the landing table judges it against the seed.
        """
        commit = (
            BaselineCommit.objects.using(WRITER_DB).filter(repo_id=self.repo.id, commit_sha=merge_commit_sha).first()
        )
        if commit is not None:
            return commit
        if github_api.commit_ancestry(self.repo, merge_commit_sha, seed.commit_sha, self.priority) is True:
            return seed
        return None

    def reconcile_open_approvals(self) -> None:
        pr_numbers = sorted({approval.pr_number for approval in self._read_open_approvals()})
        if not pr_numbers:
            return
        try:
            default_branch = self._require_default_branch()
        except errors.BaselineAdvanceError:
            return
        seed = BaselineCommit.objects.using(WRITER_DB).get(repo_id=self.repo.id, position=0)
        self._read_run_candidates(set(pr_numbers))
        closed: list[int] = []
        merged_elsewhere: list[int] = []
        late_landings: list[tuple[BaselineCommit, _Landing]] = []
        for pr_number in pr_numbers:
            pull_request = github_api.pull_request_state(self.repo, pr_number, self.priority)
            if pull_request is None:
                continue
            if not pull_request.merged:
                if pull_request.state == "closed":
                    closed.append(pr_number)
                continue
            if pull_request.base_ref != default_branch:
                if pull_request.merged_at is not None and pull_request.merged_at < self.now - MERGED_ELSEWHERE_WINDOW:
                    merged_elsewhere.append(pr_number)
                continue
            if not pull_request.merge_commit_sha or not pull_request.head_sha:
                continue
            commit = self._landing_commit(pull_request.merge_commit_sha, seed)
            if commit is None:
                continue
            landing = self.plan_landing(pr_number, pull_request.head_sha)
            if landing is not None:
                late_landings.append((commit, landing))

        with transaction.atomic(using=WRITER_DB):
            ledger.lock_ledger(self.repo.id)
            open_approvals = BaselineApproval.objects.using(WRITER_DB).filter(
                repo_id=self.repo.id, state=BaselineApprovalState.OPEN
            )
            for pr_numbers_to_abandon, detail in (
                (closed, DETAIL_CLOSED_WITHOUT_MERGE),
                (merged_elsewhere, DETAIL_MERGED_ELSEWHERE),
            ):
                if pr_numbers_to_abandon:
                    open_approvals.filter(pr_number__in=pr_numbers_to_abandon).update(
                        state=BaselineApprovalState.ABANDONED, detail=detail, resolved_at=self.now, updated_at=self.now
                    )
            self._read_open_approvals()
            # The landing table judges each approval against the entries at and above its position,
            # so merges have to land in the order they reached the default branch.
            late_landings.sort(key=lambda late_landing: late_landing[0].position)
            for commit, landing in late_landings:
                approvals = self.landing_set(landing.pr_number)
                # Changed since the read outside the lock. The next pass reads it again.
                if not approvals or not landing.covers(approvals):
                    continue
                BaselineCommit.objects.using(WRITER_DB).filter(id=commit.id, resolved=False).update(
                    resolved=True, pr_number=landing.pr_number
                )
                self.land(landing, approvals, commit.position, commit.commit_sha)


def advance(repo: Repo, priority: Priority = Priority.CRITICAL) -> AdvanceResult:
    """Record the default branch's new commits in the ledger, and land the pull requests they merged.

    Raises `BaselineBranchRewrittenError` and `BaselineCommitGapTooLargeError`, which need an
    operator to seed again, and `BaselineAdvanceError` when GitHub cannot answer a read. A rate
    limit raises `GitHubRateLimitError`, and a read that the egress budget refuses at a priority
    below `CRITICAL` raises `GitHubEgressBudgetExhausted`. Commits written by an earlier call stay
    either way.
    """
    advancer = _LedgerAdvancer(repo, priority)
    if repo.baseline_mode == BaselineMode.YAML:
        return advancer.result()
    start = ledger.cursor(repo.id)
    if start is None:
        return advancer.result()
    advancer.advance(start.commit_sha)
    return advancer.result()


def reconcile_open_approvals(repo: Repo, priority: Priority = Priority.CRITICAL) -> None:
    """Land the open approvals of pull requests that merged, and abandon those of closed ones.

    This catches a merge the commit walk missed, whatever the cause. A pull request GitHub cannot
    read stays as it is until the next pass.
    """
    if repo.baseline_mode == BaselineMode.YAML or ledger.cursor(repo.id) is None:
        return
    _LedgerAdvancer(repo, priority).reconcile_open_approvals()


def repos_with_ledger() -> list[Repo]:
    """Every repo whose ledger moves forward, for the periodic fan-out and the push lookup."""
    # nosemgrep: idor-lookup-without-team — cross-team beat sweep, no user input
    return list(
        Repo.objects.unscoped()
        .filter(baseline_mode__in=[BaselineMode.SHADOW, BaselineMode.LEDGER])
        .only("id", "team_id", "repo_external_id")
        .order_by("created_at")
    )
