"""Review decisions on pull request runs, and the one reader that every surface uses.

A decision accepts, rejects or clears one pair of pictures of a snapshot: the baseline the run
compared against and the picture it rendered. It is appended to the decision history of the
snapshot row it was made on, in `RunSnapshot.metadata["review_decisions"]`. In ledger mode it counts
on every completed review run of the same pull request and run type that renders the same pair, so
an accept made on an older push still holds on the newest one. The newest decision on a pair, by
`seq`, wins.

`review_state` on a row is not a decision. The classifier, a toleration and finalize own it.
Finalize writes the effective decisions onto the head run's rows before it commits them.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from django.db import connections
from django.db.models import Q

import structlog

from posthog.dataclasses import frozen
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team

from ..db import WRITER_DB
from ..facade.enums import (
    BaselineMode,
    DecisionAction,
    DecisionChannel,
    EarlierDecisionChange,
    ReviewState,
    RunPurpose,
    RunStatus,
    SnapshotResult,
)
from ..models import Run, RunSnapshot

logger = structlog.get_logger(__name__)

METADATA_KEY = "review_decisions"

# The time of an accept from before rows kept a history, when the row did not record one either.
_UNKNOWN_TIME = datetime.min.replace(tzinfo=UTC)


@frozen
class DecisionKey:
    """The pair of pictures a decision is about. An empty hash stands for no picture (new or removed)."""

    identifier: str
    old_hash: str
    new_hash: str


def key_of(identifier: str, baseline_hash: str, current_hash: str) -> DecisionKey:
    return DecisionKey(identifier=identifier, old_hash=baseline_hash or "", new_hash=current_hash or "")


@frozen
class Decision:
    """One entry of a snapshot's decision history, with the run it was made on."""

    action: DecisionAction
    key: DecisionKey
    by_id: int | None
    via: DecisionChannel
    reason: str
    at: datetime
    seq: int
    run_id: UUID
    commit_sha: str

    @property
    def by_person(self) -> bool:
        return self.via != DecisionChannel.MCP

    def to_json(self) -> dict:
        return {
            "action": self.action.value,
            "old_hash": self.key.old_hash,
            "new_hash": self.key.new_hash,
            "by": self.by_id,
            "via": self.via.value,
            "reason": self.reason,
            "at": self.at.isoformat(),
            "seq": self.seq,
        }


def _parse_entry(identifier: str, raw: object, run_id: UUID, commit_sha: str) -> Decision | None:
    """One history entry, or None for an entry that is not a decision.

    `decide` is the only writer, so a bad entry is a bug or a write that went around it. It is
    logged and skipped, so one bad row cannot fail every read of its pull request.
    """
    try:
        if not isinstance(raw, dict):
            raise TypeError(f"entry is a {type(raw).__name__}")
        by_id = raw.get("by")
        if by_id is not None and not isinstance(by_id, int):
            raise TypeError("by is not a user id")
        return Decision(
            action=DecisionAction(raw["action"]),
            key=key_of(identifier, str(raw.get("old_hash") or ""), str(raw.get("new_hash") or "")),
            by_id=by_id,
            via=DecisionChannel(raw.get("via", DecisionChannel.WEB)),
            reason=str(raw.get("reason") or ""),
            at=datetime.fromisoformat(raw["at"]),
            seq=int(raw["seq"]),
            run_id=run_id,
            commit_sha=commit_sha,
        )
    except (KeyError, TypeError, ValueError) as error:
        logger.warning("visual_review.review_decision_unreadable", run_id=str(run_id), error=str(error))
        return None


def changed_side(decision: Decision, key: DecisionKey) -> EarlierDecisionChange:
    """Which picture of `key` differs from the pair `decision` was about."""
    before = decision.key.old_hash != key.old_hash
    after = decision.key.new_hash != key.new_hash
    if before and after:
        return EarlierDecisionChange.BOTH
    if before:
        return EarlierDecisionChange.BEFORE
    return EarlierDecisionChange.AFTER


@frozen
class EffectiveDecision:
    """The newest decision on a pair, and for display the newest one on another pair of the same snapshot."""

    decision: Decision | None = None
    # Only set when no decision covers the pair itself.
    earlier: Decision | None = None

    @property
    def accepted(self) -> bool:
        return self.decision is not None and self.decision.action == DecisionAction.ACCEPT

    @property
    def rejected(self) -> bool:
        return self.decision is not None and self.decision.action == DecisionAction.REJECT


class PullRequestDecisions:
    """Every decision of one pull request and run type, indexed by pair and by snapshot identifier."""

    def __init__(self, decisions: list[Decision]) -> None:
        newest_first = sorted(decisions, key=lambda decision: (decision.seq, decision.at), reverse=True)
        self._newest_by_key: dict[DecisionKey, Decision] = {}
        self._by_identifier: dict[str, list[Decision]] = {}
        for decision in newest_first:
            self._newest_by_key.setdefault(decision.key, decision)
            self._by_identifier.setdefault(decision.key.identifier, []).append(decision)
        self.max_seq = max((decision.seq for decision in decisions), default=0)

    def newest(self, key: DecisionKey) -> Decision | None:
        return self._newest_by_key.get(key)

    def effective(self, key: DecisionKey) -> EffectiveDecision:
        decision = self._newest_by_key.get(key)
        if decision is not None:
            return EffectiveDecision(decision=decision)
        others = self._by_identifier.get(key.identifier, [])
        return EffectiveDecision(earlier=others[0] if others else None)

    def open_rejections(self) -> list[Decision]:
        """The pairs whose newest decision is a rejection."""
        return [decision for decision in self._newest_by_key.values() if decision.action == DecisionAction.REJECT]


def decides_by_pull_request(run: Run) -> bool:
    """Whether the run's decisions are read across its pull request: a ledger-mode review run of a pull request.

    Other runs keep the review state on their own rows, as before the decision history existed.
    """
    return (
        run.repo.baseline_mode == BaselineMode.LEDGER and run.purpose == RunPurpose.REVIEW and run.pr_number is not None
    )


def _pull_request_runs(run: Run) -> Q:
    return Q(
        team_id=run.team_id,
        repo_id=run.repo_id,
        run_type=run.run_type,
        pr_number=run.pr_number,
        purpose=RunPurpose.REVIEW,
    )


def organization_member_ids(team_id: int) -> set[int]:
    """The users who belong to the organization of the team, the only ones whose decisions count."""
    organization_id = Team.objects.filter(id=team_id).values_list("organization_id", flat=True).first()
    if organization_id is None:
        return set()
    return set(OrganizationMembership.objects.filter(organization_id=organization_id).values_list("user_id", flat=True))


def has_decisions() -> Q:
    """Matches the rows that hold a decision, for queries over `RunSnapshot`.

    An approved row without a history holds an accept from before rows kept one (see `_read_decisions`).
    The reader and retention both use this, so retention keeps every row whose decision can count.
    """
    return Q(metadata__has_key=METADATA_KEY) | Q(review_state=ReviewState.APPROVED)


def _read_decisions(team_id: int, commits_by_run: dict[UUID, str]) -> list[Decision]:
    """The decision entries on the rows of these runs.

    A row that says approved but holds no entry was accepted before rows kept a history. It counts
    as an accept with seq 0, older than any entry, so an accept from before the history still holds.

    Snapshot metadata came from the client before uploads dropped this key, so a stored entry that
    names someone outside the team's organization is not trusted: its accept or undo is dropped,
    and its rejection still counts without a name.
    """
    rows = list(
        RunSnapshot.objects.using(WRITER_DB)
        .filter(team_id=team_id, run_id__in=list(commits_by_run))
        .filter(has_decisions())
        .values_list(
            "run_id",
            "identifier",
            "baseline_hash",
            "current_hash",
            "review_state",
            "reviewed_by_id",
            "reviewed_at",
            "metadata",
        )
    )
    if not rows:
        return []
    members = organization_member_ids(team_id)
    decisions: list[Decision] = []
    newest_by_outsider: dict[tuple[int | None, DecisionKey], Decision] = {}
    for run_id, identifier, baseline_hash, current_hash, review_state, reviewed_by_id, reviewed_at, metadata in rows:
        commit_sha = commits_by_run[run_id]
        entries = (metadata or {}).get(METADATA_KEY) or []
        if entries:
            if not isinstance(entries, list):
                logger.warning("visual_review.review_decision_unreadable", run_id=str(run_id), error="not a list")
                continue
            for entry in entries:
                decision = _parse_entry(identifier, entry, run_id, commit_sha)
                if decision is None:
                    continue
                if decision.by_id not in members:
                    logger.warning("visual_review.review_decision_untrusted", run_id=str(run_id), by_id=decision.by_id)
                    slot = (decision.by_id, decision.key)
                    newest = newest_by_outsider.get(slot)
                    if newest is None or (decision.seq, decision.at) > (newest.seq, newest.at):
                        newest_by_outsider[slot] = decision
                    continue
                decisions.append(decision)
            continue
        if review_state == ReviewState.APPROVED:
            # The server sets reviewed_by, and deleting the user empties it, so an empty one still counts.
            if reviewed_by_id is not None and reviewed_by_id not in members:
                logger.warning("visual_review.review_decision_untrusted", run_id=str(run_id), by_id=reviewed_by_id)
                continue
            decisions.append(
                Decision(
                    action=DecisionAction.ACCEPT,
                    key=key_of(identifier, baseline_hash, current_hash),
                    by_id=reviewed_by_id,
                    via=DecisionChannel.WEB,
                    reason="",
                    at=reviewed_at or _UNKNOWN_TIME,
                    seq=0,
                    run_id=run_id,
                    commit_sha=commit_sha,
                )
            )
    # A rejection only blocks, and a person can still accept over it, so a non-member's rejection
    # stays while it is that person's newest decision on the pair. It names nobody, because the ID
    # may belong to a user outside the organization.
    decisions.extend(
        dataclasses.replace(decision, by_id=None)
        for decision in newest_by_outsider.values()
        if decision.action == DecisionAction.REJECT
    )
    return decisions


def pull_request_decisions(run: Run) -> PullRequestDecisions:
    """Every decision that can count on the run.

    In ledger mode these are the decisions on all completed review runs of the run's pull request
    and run type, superseded ones included. Otherwise only the run's own rows count.
    """
    if not decides_by_pull_request(run):
        return PullRequestDecisions(_read_decisions(run.team_id, {run.id: run.commit_sha}))
    commits_by_run = dict(
        Run.objects.using(WRITER_DB)
        .filter(_pull_request_runs(run), status=RunStatus.COMPLETED)
        .values_list("id", "commit_sha")
    )
    commits_by_run[run.id] = run.commit_sha
    return PullRequestDecisions(_read_decisions(run.team_id, commits_by_run))


class Standing(StrEnum):
    """Where one snapshot of a run stands for the gate and for finalize."""

    REJECTED = "rejected"
    # Unchanged, quarantined or tolerated, and not rejected
    RESOLVED = "resolved"
    # Accepted, and waits for finalize unless the run is finalized
    ACCEPTED = "accepted"
    NEEDS_REVIEW = "needs_review"


def standing_of(result: str, is_quarantined: bool, tolerated: bool, effective: EffectiveDecision) -> Standing:
    """A rejection blocks before every exemption, so neither a quarantine nor a toleration hides it."""
    if effective.rejected:
        return Standing.REJECTED
    if result == SnapshotResult.UNCHANGED or is_quarantined or tolerated:
        return Standing.RESOLVED
    if effective.accepted:
        return Standing.ACCEPTED
    return Standing.NEEDS_REVIEW


def effective_review_state(row_review_state: str, effective: EffectiveDecision) -> str:
    """The review state a reader sees for a row: the effective decision first, then the row's own state."""
    if effective.rejected:
        return ReviewState.REJECTED
    if effective.accepted:
        return ReviewState.APPROVED
    if row_review_state == ReviewState.TOLERATED:
        return ReviewState.TOLERATED
    if row_review_state in (ReviewState.APPROVED, ReviewState.REJECTED):
        return ReviewState.PENDING
    return row_review_state


@frozen
class SnapshotReview:
    identifier: str
    result: SnapshotResult
    key: DecisionKey
    is_quarantined: bool
    tolerated: bool
    standing: Standing
    effective: EffectiveDecision


@frozen
class RunProgress:
    """How far the review of a run got.

    `total` is `approved + rejected + needs_review + tolerated`. The two `approved_*` counts are
    subsets of `approved`.
    """

    total: int
    approved: int
    approved_on_earlier_commits: int
    approved_via_mcp: int
    rejected: int
    needs_review: int
    tolerated: int


@frozen
class RunReview:
    """The standing of every snapshot of a run that a decision can change."""

    run_id: UUID
    commit_sha: str
    approved: bool
    # Changed, new and removed snapshots, and unchanged ones whose pair is rejected.
    snapshots: tuple[SnapshotReview, ...]
    # Open rejections of snapshots a partial run did not render. They block it like a rendered rejection.
    unrendered_rejections: tuple[Decision, ...]

    def with_standing(self, standing: Standing) -> list[SnapshotReview]:
        return [snapshot for snapshot in self.snapshots if snapshot.standing == standing]

    def rejections(self) -> list[Decision]:
        rendered = [snapshot.effective.decision for snapshot in self.with_standing(Standing.REJECTED)]
        return [decision for decision in rendered if decision is not None] + list(self.unrendered_rejections)

    @property
    def rejected_count(self) -> int:
        return len(self.rejections())

    @property
    def needs_review_count(self) -> int:
        return len(self.with_standing(Standing.NEEDS_REVIEW))

    @property
    def awaiting_finalize_count(self) -> int:
        return 0 if self.approved else len(self.with_standing(Standing.ACCEPTED))

    def progress(self) -> RunProgress:
        accepted = self.with_standing(Standing.ACCEPTED)
        tolerated = [
            snapshot
            for snapshot in self.with_standing(Standing.RESOLVED)
            if snapshot.tolerated and not snapshot.is_quarantined and snapshot.result != SnapshotResult.UNCHANGED
        ]
        accepts = [snapshot.effective.decision for snapshot in accepted if snapshot.effective.decision is not None]
        approved = len(accepted)
        rejected = self.rejected_count
        needs_review = self.needs_review_count
        return RunProgress(
            total=approved + rejected + needs_review + len(tolerated),
            approved=approved,
            approved_on_earlier_commits=sum(1 for decision in accepts if decision.commit_sha != self.commit_sha),
            approved_via_mcp=sum(1 for decision in accepts if not decision.by_person),
            rejected=rejected,
            needs_review=needs_review,
            tolerated=len(tolerated),
        )


def review_run(run: Run, decisions: PullRequestDecisions | None = None) -> RunReview:
    """Read the standing of a run's snapshots under the decisions that count on it."""
    if decisions is None:
        decisions = pull_request_decisions(run)
    rejected_identifiers = {decision.key.identifier for decision in decisions.open_rejections()}
    rows = (
        RunSnapshot.objects.using(WRITER_DB)
        .filter(team_id=run.team_id, run_id=run.id)
        .filter(~Q(result=SnapshotResult.UNCHANGED) | Q(identifier__in=rejected_identifiers))
        .values_list("identifier", "result", "baseline_hash", "current_hash", "is_quarantined", "review_state")
    )
    snapshots: list[SnapshotReview] = []
    rendered: set[str] = set()
    for identifier, result, baseline_hash, current_hash, is_quarantined, review_state in rows:
        rendered.add(identifier)
        key = key_of(identifier, baseline_hash, current_hash)
        effective = decisions.effective(key)
        tolerated = review_state == ReviewState.TOLERATED
        snapshots.append(
            SnapshotReview(
                identifier=identifier,
                result=SnapshotResult(result),
                key=key,
                is_quarantined=is_quarantined,
                tolerated=tolerated,
                standing=standing_of(result, is_quarantined, tolerated, effective),
                effective=effective,
            )
        )
    unrendered: list[Decision] = []
    if run.is_partial and decides_by_pull_request(run):
        unrendered = sorted(
            (decision for decision in decisions.open_rejections() if decision.key.identifier not in rendered),
            key=lambda decision: decision.key.identifier,
        )
    return RunReview(
        run_id=run.id,
        commit_sha=run.commit_sha,
        approved=run.approved,
        snapshots=tuple(sorted(snapshots, key=lambda snapshot: snapshot.identifier)),
        unrendered_rejections=tuple(unrendered),
    )


def head_run(run: Run, head_sha: str | None = None) -> Run:
    """The run whose verdict gates the run's pull request.

    That is the newest completed review run of the pull request's head commit, when GitHub named
    the head. Without it, or before that run exists, it is the pull request's newest current run,
    which can still be processing. A run without a pull request is its own head.
    """
    if run.pr_number is None:
        return run
    runs = Run.objects.using(WRITER_DB).select_related("repo").filter(_pull_request_runs(run))
    if head_sha:
        at_head = runs.filter(commit_sha=head_sha, status=RunStatus.COMPLETED).order_by("-created_at", "-id").first()
        if at_head is not None:
            return at_head
    current = runs.filter(superseded_by__isnull=True).order_by("-created_at", "-id").first()
    if current is not None:
        return current
    return runs.order_by("-created_at", "-id").first() or run


def _pull_request_lock_key(repo_id: UUID, run_type: str, pr_number: int) -> str:
    return f"visual_review_pull_request:{repo_id}:{run_type}:{pr_number}"


def lock_pull_request(repo_id: UUID, run_type: str, pr_number: int) -> None:
    """Serialize decisions, tolerations, finalize and retention on one pull request until the transaction ends.

    Take it before any run row lock. Finalize takes the ledger lock before it, and nothing may take
    the ledger lock after it, so the two never wait on each other in opposite orders.
    """
    if not connections[WRITER_DB].in_atomic_block:
        raise RuntimeError("lock_pull_request needs a transaction on the visual review writer database")
    with connections[WRITER_DB].cursor() as db_cursor:
        db_cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))", [_pull_request_lock_key(repo_id, run_type, pr_number)]
        )


def database_now() -> datetime:
    """The database clock, so two app servers with skewed clocks cannot order decisions wrongly."""
    with connections[WRITER_DB].cursor() as db_cursor:
        db_cursor.execute("SELECT clock_timestamp()")
        return db_cursor.fetchone()[0]


def append_decisions(decided: list[tuple[RunSnapshot, Decision]]) -> None:
    """Add decisions to the rows' histories in one statement. The caller holds the pull request lock, which orders `seq`."""
    if not decided:
        return
    at = decided[0][1].at
    rows: dict[UUID, RunSnapshot] = {}
    for row, decision in decided:
        row = rows.setdefault(row.id, row)
        metadata = dict(row.metadata or {})
        metadata[METADATA_KEY] = [*(metadata.get(METADATA_KEY) or []), decision.to_json()]
        row.metadata = metadata
        row.updated_at = at
    RunSnapshot.objects.using(WRITER_DB).bulk_update(list(rows.values()), ["metadata", "updated_at"])


@frozen
class ApproverGroup:
    """The accepts of one person through one channel that a run counts."""

    by_id: int | None
    via: DecisionChannel
    count: int
    commit_shas: tuple[str, ...]


def approver_groups(review: RunReview) -> list[ApproverGroup]:
    """Who accepted the run's accepted snapshots, grouped by person and channel, most accepts first."""
    groups: dict[tuple[int | None, DecisionChannel], list[Decision]] = {}
    for snapshot in review.with_standing(Standing.ACCEPTED):
        decision = snapshot.effective.decision
        if decision is not None:
            groups.setdefault((decision.by_id, decision.via), []).append(decision)
    result = [
        ApproverGroup(
            by_id=by_id,
            via=via,
            count=len(decisions),
            commit_shas=tuple(sorted({decision.commit_sha for decision in decisions})),
        )
        for (by_id, via), decisions in groups.items()
    ]
    return sorted(result, key=lambda group: (-group.count, group.by_id or 0, group.via))
