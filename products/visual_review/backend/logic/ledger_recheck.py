"""The ledger's view of a run that was classified against the baseline file, read from what the run stored.

A run created before the switch to `ledger` mode compared its renders with the YAML file. After the
switch every publisher recomputes the status from that stored classification, so without this check
a YAML pass could post under the context the ruleset requires. Nothing here asks GitHub: the merge-base
position comes from the run's baseline record, and the overlay from approvals that are still open.
"""

from __future__ import annotations

from django.db.models import Q
from django.utils import timezone

from posthog.dataclasses import frozen

from ..db import WRITER_DB
from ..facade.enums import BaselineApprovalState, BaselineMode, SnapshotResult
from ..models import BaselineApproval, Run, RunSnapshot
from . import baseline_approvals, baseline_record, baseline_resolution, ledger, toleration


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


def _candidates(run: Run, record: baseline_record.BaselineRecord, identifiers: set[str]) -> list[BaselineApproval]:
    """The open approvals the run's record applied, and the open approvals of the run's own pull request."""
    applied_or_own = Q(id__in=record.candidate_approval_ids)
    if run.pr_number is not None:
        applied_or_own |= Q(pr_number=run.pr_number)
    return list(
        BaselineApproval.objects.using(WRITER_DB).filter(
            applied_or_own,
            repo_id=run.repo_id,
            run_type=run.run_type,
            identifier__in=identifiers,
            state=BaselineApprovalState.OPEN,
        )
    )


def recheck_run(run: Run) -> LedgerRecheck | None:
    """Recheck a run that the YAML file classified against the ledger. None for a run the ledger classified.

    A rendered snapshot counts as unsure when its ledger baseline differs from the stored baseline
    and its stored render is neither the ledger hash nor the overlay hash, nor tolerated against one
    of them. Only a pixel diff could decide it, and that needs a new run.
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
    identifiers = {snapshot.identifier for snapshot in snapshots}
    ledger_hashes = ledger.hashes_at(run.repo_id, run.run_type, identifiers, record.position)
    overlay = baseline_approvals.reduce_overlay(_candidates(run, record, identifiers), ledger_hashes)
    overlay_hashes = {identifier: entry.content_hash for identifier, entry in overlay.entries.items()}
    tolerated_lookup = toleration.build_tolerated_lookup(
        run.repo_id,
        identifiers,
        set(ledger_hashes.values()) | {content_hash for content_hash in overlay_hashes.values() if content_hash},
        now=timezone.now(),
    )

    unsure = 0
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
