"""The ledger's view of a run that was classified against the baseline file, read from what the run stored.

A run created before the switch to `ledger` mode compared its renders with the YAML file. With the
commit status gate on, every publisher recomputes the status from that stored classification, so
without this check a YAML pass could post under the context the ruleset requires. That holds in
`shadow` mode too, because the ruleset requires the context before `mode --set ledger`. Nothing here asks GitHub: the merge-base
position comes from the run's baseline record, and the overlay from approvals that are still open.
"""

from __future__ import annotations

from django.db.models import Q
from django.utils import timezone

from posthog.dataclasses import frozen

from ..db import WRITER_DB
from ..facade.enums import BaselineApprovalState, BaselineMode, SnapshotResult
from ..models import BaselineApproval, Run, RunSnapshot
from . import baseline_approvals, baseline_record, baseline_resolution, ledger, quarantine, toleration


@frozen
class LedgerRecheck:
    """How many snapshots of the run the ledger cannot decide from the stored hashes alone."""

    unsure: int
    # The run's merge-base is older than the ledger's seed, so a merge of the default branch helps.
    clamped: bool
    # A run without a usable record cannot be placed on the ledger at all.
    has_record: bool

    @property
    def needs_new_run(self) -> bool:
        return not self.has_record or self.unsure > 0


def _candidates(
    run: Run, record: baseline_record.BaselineRecord, identifiers: set[str] | None
) -> list[BaselineApproval]:
    """The approvals the run's record applied and the approvals of the run's own pull request, outside the ledger it reads.

    An approval that landed after the record's position is promoted, but the ledger at that position
    does not hold its hash, so it still counts, as in ledger resolution.
    """
    applied_or_own = Q(id__in=record.candidate_approval_ids)
    if run.pr_number is not None:
        applied_or_own |= Q(pr_number=run.pr_number)
    outside_ledger = Q(state=BaselineApprovalState.OPEN) | Q(
        state=BaselineApprovalState.PROMOTED, landed_position__gt=record.position
    )
    approvals = BaselineApproval.objects.using(WRITER_DB).filter(
        applied_or_own, outside_ledger, repo_id=run.repo_id, run_type=run.run_type
    )
    if identifiers is not None:
        approvals = approvals.filter(identifier__in=identifiers)
    return list(approvals)


def recheck_run(run: Run) -> LedgerRecheck | None:
    """Recheck a run that the YAML file classified against the ledger. None for a run the ledger classified.

    A rendered snapshot counts as unsure when its ledger baseline differs from the stored baseline
    and its stored render is neither the ledger hash nor the overlay hash, nor tolerated against one
    of them. Only a pixel diff could decide it, and that needs a new run.

    A full run also counts each identifier that the ledger or an approval holds and the run has no
    snapshot of, unless an approval removes it or a quarantine covers it. The YAML file dropped it as well, so the run stored no
    removal, but a run in `ledger` mode reports it as removed.
    """
    record = baseline_record.record_for_run(run)
    if record is None:
        return LedgerRecheck(unsure=0, clamped=False, has_record=False)
    if record.mode == BaselineMode.LEDGER:
        return None

    snapshots = list(
        RunSnapshot.objects.using(WRITER_DB)
        .filter(run_id=run.id, is_quarantined=False)
        .exclude(result=SnapshotResult.REMOVED)
        .exclude(current_hash="")
        .only("identifier", "current_hash", "baseline_hash")
    )
    rendered = {snapshot.identifier for snapshot in snapshots}
    ledger_only: set[str] = set()
    # A partial run proves nothing about the stories outside its subset, so only a full run reads
    # every approval: one can add a story that the ledger does not hold yet.
    candidates = _candidates(run, record, None if not run.is_partial else rendered)
    if not run.is_partial:
        stored = set(RunSnapshot.objects.using(WRITER_DB).filter(run_id=run.id).values_list("identifier", flat=True))
        quarantined = set(
            quarantine.active_quarantined_identifiers(run.repo_id, run.team_id, run.run_type, using=WRITER_DB)
        )
        expected = set(ledger.ledger_at(run.repo_id, run.run_type, record.position))
        expected |= {approval.identifier for approval in candidates if approval.content_hash}
        ledger_only = expected - stored - quarantined
    identifiers = rendered | ledger_only
    ledger_hashes = ledger.hashes_at(run.repo_id, run.run_type, identifiers, record.position)
    overlay = baseline_approvals.reduce_overlay(
        [approval for approval in candidates if approval.identifier in identifiers], ledger_hashes
    )
    overlay_hashes = {identifier: entry.content_hash for identifier, entry in overlay.entries.items()}
    tolerated_lookup = toleration.build_tolerated_lookup(
        run.repo_id,
        rendered,
        set(ledger_hashes.values()) | {content_hash for content_hash in overlay_hashes.values() if content_hash},
        now=timezone.now(),
    )

    unsure = sum(1 for identifier in ledger_only if overlay_hashes.get(identifier) != "")
    for snapshot in snapshots:
        identifier = snapshot.identifier
        ledger_hash = ledger_hashes.get(identifier, "")
        overlay_hash = overlay_hashes.get(identifier, "")
        pick = baseline_resolution.pick_baseline(
            identifier, snapshot.current_hash, ledger_hash, overlay_hash, tolerated_lookup
        )
        if pick.baseline_hash == snapshot.baseline_hash:
            continue
        passes = baseline_approvals.reproduces_by_hash(
            identifier, snapshot.current_hash, ledger_hash, tolerated_lookup
        ) or baseline_approvals.reproduces_by_hash(identifier, snapshot.current_hash, overlay_hash, tolerated_lookup)
        if not passes:
            unsure += 1
    return LedgerRecheck(unsure=unsure, clamped=record.clamped_to_seed, has_record=True)
