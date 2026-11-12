"""Approval rows of the baseline ledger: which ones a run counts, writing them at finalize, and evidence.

An approval says that one pull request approved one hash for one identifier. It applies to a run
only while the baseline it replaced still holds, so a run never compares against an approval that a
later merge made stale.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen

from ..classifier import ToleratedKey
from ..db import WRITER_DB
from ..facade.enums import (
    BaselineApprovalState,
    BaselineEvidence,
    BaselineMode,
    ReviewState,
    RunPurpose,
    RunStatus,
    SnapshotResult,
)
from ..models import BaselineApproval, Run, RunSnapshot, ToleratedHash
from . import baseline_record, github_api, ledger, quarantine, toleration
from .baseline_record import OverlayEntry

logger = structlog.get_logger(__name__)

DETAIL_SUPERSEDED = "A later approval in the same pull request replaced this one"
DETAIL_BACK_TO_BASELINE = "The pull request went back to the baseline picture"


def reproduces_by_hash(
    identifier: str, render_hash: str, target_hash: str, tolerated_lookup: dict[ToleratedKey, ToleratedHash]
) -> bool:
    """Whether a render stands for the target without a pixel diff: the same hash, or a live toleration.

    The lookup from `toleration.build_tolerated_lookup` already holds both directions of a pair.
    """
    if not render_hash or not target_hash:
        return False
    if render_hash == target_hash:
        return True
    return ToleratedKey(identifier=identifier, baseline_hash=target_hash, current_hash=render_hash) in tolerated_lookup


def base_still_holds(approval: BaselineApproval, current_hash: str) -> bool:
    """Whether the ledger's hash is still a baseline the approval was made over. An empty hash is a value too.

    The effective base counts because a stack parent that landed puts on the ledger what the reviewer compared against.
    """
    return current_hash in (approval.ledger_base_hash, approval.effective_base_hash)


def _approval_applies(approval: BaselineApproval, ledger_hashes: dict[str, str]) -> bool:
    return base_still_holds(approval, ledger_hashes.get(approval.identifier, ""))


@frozen
class Overlay:
    entries: dict[str, OverlayEntry]
    # Every candidate that applied, also the ones the reduction dropped.
    candidate_approval_ids: tuple[UUID, ...]
    conflicts: dict[str, tuple[int, ...]]


def _newest_run_commits(run: Run, pr_numbers: Iterable[int]) -> dict[int, str]:
    newest = (
        Run.objects.using(WRITER_DB)
        .filter(repo_id=run.repo_id, pr_number__in=list(pr_numbers), superseded_by__isnull=True)
        .order_by("pr_number", "-created_at")
        .distinct("pr_number")
        .values_list("pr_number", "commit_sha")
    )
    return {pr_number: commit_sha for pr_number, commit_sha in newest if pr_number is not None}


def _candidates(run: Run, comparison: github_api.Comparison | None) -> list[BaselineApproval]:
    """The open approvals whose commits the run's tree contains."""
    if comparison is None:
        return []
    open_approvals = BaselineApproval.objects.using(WRITER_DB).filter(
        repo_id=run.repo_id, run_type=run.run_type, state=BaselineApprovalState.OPEN
    )
    # A list cut short cannot prove that another pull request's commit is absent, so only the
    # run's own pull request counts.
    if not comparison.complete:
        if run.pr_number is None:
            return []
        return list(open_approvals.filter(pr_number=run.pr_number))

    contained = [commit.sha for commit in comparison.commits]
    in_tree = Q(commit_sha__in=contained) | Q(carried_commit_sha__in=contained)
    if run.pr_number is not None:
        in_tree |= Q(pr_number=run.pr_number)
    rest = open_approvals.exclude(in_tree)
    rest_prs = set(rest.values_list("pr_number", flat=True).distinct())
    prs_with_contained_head = [
        pr_number for pr_number, commit_sha in _newest_run_commits(run, rest_prs).items() if commit_sha in contained
    ]
    approvals = list(open_approvals.filter(in_tree))
    if prs_with_contained_head:
        approvals += list(rest.filter(pr_number__in=prs_with_contained_head))
    return approvals


def reduce_overlay(candidates: list[BaselineApproval], ledger_hashes: dict[str, str]) -> Overlay:
    """The overlay entry per identifier from the candidate approvals of a run, and the conflicts.

    A candidate applies only while the ledger holds its base. A stack child wins over its parent,
    two pull requests with different hashes conflict, and otherwise the newest approval wins.
    """
    applicable = [approval for approval in candidates if _approval_applies(approval, ledger_hashes)]

    by_identifier: dict[str, list[BaselineApproval]] = {}
    for approval in applicable:
        by_identifier.setdefault(approval.identifier, []).append(approval)

    entries: dict[str, OverlayEntry] = {}
    conflicts: dict[str, tuple[int, ...]] = {}
    for identifier, approvals in sorted(by_identifier.items()):
        # A stack parent's hash is the base its child approved over, so the child wins.
        remaining = [
            approval
            for approval in approvals
            if not any(
                other.id != approval.id and other.effective_base_hash == approval.content_hash for other in approvals
            )
        ]
        if not remaining:
            continue
        if len({approval.content_hash for approval in remaining}) > 1:
            conflicts[identifier] = tuple(sorted({approval.pr_number for approval in remaining}))
            continue
        chosen = max(remaining, key=lambda approval: (approval.approved_at, approval.id))
        entries[identifier] = OverlayEntry(
            content_hash=chosen.content_hash,
            approval_id=chosen.id,
            pr_number=chosen.pr_number,
            ledger_hash=ledger_hashes.get(identifier, ""),
        )

    return Overlay(
        entries=entries,
        candidate_approval_ids=tuple(approval.id for approval in applicable),
        conflicts=conflicts,
    )


def overlay_for_run(run: Run, comparison: github_api.Comparison | None, ledger_hashes: dict[str, str]) -> Overlay:
    """The approvals a run compares against on top of the ledger, per identifier.

    `comparison` is None for a run on the default branch, which has no candidates.
    """
    return reduce_overlay(_candidates(run, comparison), ledger_hashes)


def _ledger_base_hashes(
    run: Run, record: baseline_record.BaselineRecord, snapshots: list[RunSnapshot]
) -> dict[str, str]:
    """The ledger hash each approved snapshot replaced, as the run resolved it, not as the ledger is now.

    In a ledger-mode record the stamped baseline is the ledger hash wherever no overlay supplied
    it. A shadow-mode record stamped the YAML baseline, which equals the ledger hash except for the
    identifiers in `differences`. Those cover rendered identifiers only, so a removed one is read from
    the ledger at the record's position.
    """
    bases: dict[str, str] = {}
    unknown: list[str] = []
    differences = record.differences or {}
    for snapshot in snapshots:
        identifier = snapshot.identifier
        if identifier in record.overlay:
            bases[identifier] = record.overlay[identifier].ledger_hash
        elif record.mode == BaselineMode.LEDGER:
            bases[identifier] = snapshot.baseline_hash
        elif identifier in differences:
            bases[identifier] = differences[identifier]
        elif record.differences_truncated or snapshot.result == SnapshotResult.REMOVED:
            unknown.append(identifier)
        else:
            bases[identifier] = snapshot.baseline_hash
    if unknown:
        fallback = ledger.hashes_at(run.repo_id, run.run_type, unknown, record.position)
        bases.update({identifier: fallback.get(identifier, "") for identifier in unknown})
    return bases


def record_approvals(run: Run, user_id: int, *, carried_commit_sha: str = "") -> int:
    """Write one approval row per approved change of a finalized run. Returns the number written.

    `carried_commit_sha` is the baseline commit finalize pushed to the pull request branch, if any.
    The caller holds the ledger lock and then the run's row lock, inside a transaction on the
    writer database.
    """
    record = baseline_record.record_for_run(run)
    if record is None:
        logger.warning("visual_review.baseline_approvals_without_record", run_id=str(run.id))
        return 0
    if run.pr_number is None:
        logger.warning("visual_review.baseline_approvals_without_pull_request", run_id=str(run.id))
        return 0

    approved_snapshots = list(
        run.snapshots.using(WRITER_DB).filter(
            review_state=ReviewState.APPROVED,
            result__in=(SnapshotResult.NEW, SnapshotResult.CHANGED, SnapshotResult.REMOVED),
        )
    )
    if not approved_snapshots:
        return 0
    ledger_bases = _ledger_base_hashes(run, record, approved_snapshots)
    now = timezone.now()

    new_approvals: list[BaselineApproval] = []
    back_to_baseline: list[str] = []
    for snapshot in approved_snapshots:
        approved_hash = "" if snapshot.result == SnapshotResult.REMOVED else snapshot.approved_hash
        ledger_base_hash = ledger_bases.get(snapshot.identifier, "")
        if approved_hash == ledger_base_hash:
            back_to_baseline.append(snapshot.identifier)
            continue
        new_approvals.append(
            BaselineApproval(
                repo_id=run.repo_id,
                team_id=run.team_id,
                run_type=run.run_type,
                pr_number=run.pr_number,
                identifier=snapshot.identifier,
                content_hash=approved_hash,
                ledger_base_hash=ledger_base_hash,
                effective_base_hash=snapshot.baseline_hash,
                commit_sha=run.commit_sha,
                carried_commit_sha=carried_commit_sha,
                source_run=run,
                approved_by_id=user_id,
                approved_at=now,
            )
        )

    open_approvals = BaselineApproval.objects.using(WRITER_DB).filter(
        repo_id=run.repo_id, run_type=run.run_type, pr_number=run.pr_number, state=BaselineApprovalState.OPEN
    )
    open_approvals.filter(identifier__in=back_to_baseline).update(
        state=BaselineApprovalState.SUPERSEDED, detail=DETAIL_BACK_TO_BASELINE, resolved_at=now, updated_at=now
    )
    open_approvals.filter(identifier__in=[approval.identifier for approval in new_approvals]).update(
        state=BaselineApprovalState.SUPERSEDED, detail=DETAIL_SUPERSEDED, resolved_at=now, updated_at=now
    )
    BaselineApproval.objects.using(WRITER_DB).bulk_create(new_approvals)
    return len(new_approvals)


def rendered_approved_hash(
    approval: BaselineApproval,
    snapshot: RunSnapshot | None,
    is_partial: bool,
    tolerated_lookup: dict[ToleratedKey, ToleratedHash],
) -> bool:
    """Whether a run's render of the approval's identifier reproduces the approved picture."""
    rendered = snapshot is not None and snapshot.result != SnapshotResult.REMOVED
    if not approval.content_hash:
        # A partial run leaves stories out on purpose, so a missing render proves no removal.
        return not rendered and not is_partial
    if snapshot is None or not rendered:
        return False
    if snapshot.result == SnapshotResult.UNCHANGED and snapshot.baseline_hash == approval.content_hash:
        return True
    return reproduces_by_hash(approval.identifier, snapshot.current_hash, approval.content_hash, tolerated_lookup)


def _reproduction(run: Run, approvals: list[BaselineApproval]) -> dict[UUID, bool]:
    identifiers = {approval.identifier for approval in approvals}
    snapshots = {
        snapshot.identifier: snapshot
        for snapshot in run.snapshots.using(WRITER_DB)
        .filter(identifier__in=identifiers)
        .only("identifier", "current_hash", "baseline_hash", "result")
    }
    tolerated_lookup = toleration.build_tolerated_lookup(
        run.repo_id,
        identifiers,
        {approval.content_hash for approval in approvals if approval.content_hash},
        now=timezone.now(),
    )
    return {
        approval.id: rendered_approved_hash(
            approval, snapshots.get(approval.identifier), run.is_partial, tolerated_lookup
        )
        for approval in approvals
    }


def _back_to_baseline(run: Run, approvals: list[BaselineApproval]) -> list[UUID]:
    """The approvals whose identifier this run rendered unchanged against a baseline that is not the approved hash.

    The pull request went back to that baseline, so the approval would otherwise stay open and
    land without evidence. Quarantined identifiers are left alone, because their renders gate nothing.
    """
    unchanged_baselines = dict(
        run.snapshots.using(WRITER_DB)
        .filter(identifier__in={approval.identifier for approval in approvals}, result=SnapshotResult.UNCHANGED)
        .values_list("identifier", "baseline_hash")
    )
    quarantined = set(
        quarantine.active_quarantined_identifiers(run.repo_id, run.team_id, run.run_type, using=WRITER_DB)
    )
    return [
        approval.id
        for approval in approvals
        if approval.identifier in unchanged_baselines
        and unchanged_baselines[approval.identifier] != approval.content_hash
        and approval.identifier not in quarantined
    ]


def record_carried_commits(run: Run) -> None:
    """Point the pull request's open approvals that this run reproduced at the run's commit.

    After a rebase the approved commit is no longer in the branch, and the carried commit is what
    keeps the approval among a later run's candidates. In ledger mode an approval the run went
    back from is superseded. In shadow mode the snapshot was compared with the YAML file, so
    finalize handles that case instead.
    """
    if run.pr_number is None or run.superseded_by_id is not None:
        return
    approvals = list(
        BaselineApproval.objects.using(WRITER_DB).filter(
            repo_id=run.repo_id, run_type=run.run_type, pr_number=run.pr_number, state=BaselineApprovalState.OPEN
        )
    )
    if not approvals:
        return
    superseded = _back_to_baseline(run, approvals) if run.repo.baseline_mode == BaselineMode.LEDGER else []
    remaining = [approval for approval in approvals if approval.id not in superseded]
    reproduced = [approval_id for approval_id, ok in _reproduction(run, remaining).items() if ok] if remaining else []
    if not reproduced and not superseded:
        return
    now = timezone.now()
    with transaction.atomic(using=WRITER_DB):
        ledger.lock_ledger(run.repo_id)
        # A newer run may have superseded this one and been finalized since the read above.
        if not Run.objects.using(WRITER_DB).filter(id=run.id, superseded_by__isnull=True).exists():
            return
        BaselineApproval.objects.using(WRITER_DB).filter(
            team_id=run.team_id, id__in=superseded, state=BaselineApprovalState.OPEN
        ).update(
            state=BaselineApprovalState.SUPERSEDED, detail=DETAIL_BACK_TO_BASELINE, resolved_at=now, updated_at=now
        )
        BaselineApproval.objects.using(WRITER_DB).filter(
            team_id=run.team_id, id__in=reproduced, state=BaselineApprovalState.OPEN
        ).update(carried_commit_sha=run.commit_sha, updated_at=now)


def _is_evidence_candidate(run: Run) -> bool:
    return run.status != RunStatus.FAILED and not run.is_partial and run.purpose == RunPurpose.OBSERVE


def record_evidence(run: Run) -> None:
    """Record on each candidate approval whether this full off-default-branch run reproduced it.

    The caller runs this before it saves the run as completed, so a merge that follows a green
    queue run always finds the evidence.
    """
    if not _is_evidence_candidate(run):
        return
    record = baseline_record.record_for_run(run)
    if record is None or not record.candidate_approval_ids:
        return
    approvals = list(
        BaselineApproval.objects.using(WRITER_DB).filter(
            team_id=run.team_id,
            repo_id=run.repo_id,
            id__in=record.candidate_approval_ids,
            state=BaselineApprovalState.OPEN,
        )
    )
    if not approvals:
        return
    reproduction = _reproduction(run, approvals)
    by_outcome: dict[BaselineEvidence, list[UUID]] = {
        BaselineEvidence.REPRODUCED: [],
        BaselineEvidence.NOT_REPRODUCED: [],
    }
    for approval in approvals:
        outcome = BaselineEvidence.REPRODUCED if reproduction[approval.id] else BaselineEvidence.NOT_REPRODUCED
        by_outcome[outcome].append(approval.id)

    now = timezone.now()
    with transaction.atomic(using=WRITER_DB):
        ledger.lock_ledger(run.repo_id)
        for outcome, approval_ids in by_outcome.items():
            if not approval_ids:
                continue
            BaselineApproval.objects.using(WRITER_DB).filter(
                team_id=run.team_id, id__in=approval_ids, state=BaselineApprovalState.OPEN
            ).filter(Q(evidence_run_created_at__isnull=True) | Q(evidence_run_created_at__lt=run.created_at)).update(
                evidence=outcome,
                evidence_run=run,
                evidence_commit_sha=run.commit_sha,
                evidence_run_created_at=run.created_at,
                updated_at=now,
            )
