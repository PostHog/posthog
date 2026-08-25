"""Claim a NotebookNodeRun's RUNNING -> terminal transition and report it exactly once.

Every lane that finishes a run funnels through `finish_node_run`: the direct (hogql)
lane's pollers and grace-expiry watchdog, the kernel lane's watchdog below, dispatch
failures (the run view and the Temporal mark-failed activity), and the interrupt
endpoints. The sandbox callback is the one deliberate exception — it upserts losing
deliveries too, so a late real result can overwrite an interrupt placeholder — and keeps
its own block in sql_v2_callback.py.
"""

from typing import Any

from django.utils import timezone

from products.notebooks.backend.models import NotebookNodeRun
from products.notebooks.backend.sql_v2_metrics import OUTCOME_TIMED_OUT, outcome_for_status, record_node_run_terminal

# How long a RUNNING kernel run may go without a callback before a watchdog fails it.
# The kernel lane's analogue of DIRECT_RUN_RESULT_GRACE_SECONDS, and necessarily wider: a
# python node materializes its HogQL inputs before it executes any code, and that
# materialization is its own Temporal job with a 10 minute deadline, on top of the kernel's
# 5 minute execute cap. Sized above their sum so the watchdog can never kill a cell that is
# legitimately still working.
KERNEL_RUN_RESULT_GRACE_SECONDS = 20 * 60


def finish_node_run(
    run: NotebookNodeRun,
    status: NotebookNodeRun.Status,
    *,
    error: str | None,
    envelope: dict | None = None,
    outcome: str | None = None,
) -> bool:
    """Move a RUNNING `run` to a terminal state; return whether this call won the transition.

    Guarded on the current status so concurrent finishers are idempotent and a completed
    query can never overwrite an interrupt. Refreshes `run` either way so the caller
    always sees the row that won. The winner reports the run's terminal metrics, labeled
    `outcome` when the status alone undersells it (the direct lane's watchdog expiry is a
    timeout, not a user error). `envelope` is only written when given — a RUNNING row has
    none yet, and interrupts and failures must not invent one.
    """
    fields: dict[str, Any] = {"status": status, "error": error, "updated_at": timezone.now()}
    if envelope is not None:
        fields["envelope"] = envelope
        fields["result_id"] = envelope.get("result_id")
    updated = (
        NotebookNodeRun.objects.for_team(run.team_id)
        .filter(id=run.id, status=NotebookNodeRun.Status.RUNNING)
        .update(**fields)
    )
    # select_related: the recorder reads run.user and run.notebook; a plain refresh wipes
    # the FK caches and forces a lazy query per relation.
    run.refresh_from_db(from_queryset=NotebookNodeRun.objects.for_team(run.team_id).select_related("user", "notebook"))
    if updated:
        record_node_run_terminal(run, outcome or outcome_for_status(status))
    return bool(updated)


def expire_stale_kernel_run(run: NotebookNodeRun) -> bool:
    """Fail a kernel (python/duckdb) run whose callback never arrived; return whether it did.

    The sandbox POSTs its envelope exactly once, with no retry, so a lost delivery leaves
    the row RUNNING with nothing left to complete it. The dispatch workflow's mark-failed
    activity does not cover this: it fires when dispatch never landed, not when a run landed
    and then went quiet. This is the watchdog the kernel lane never had, mirroring
    `sync_direct_run`'s grace expiry for the lane that already has one.

    Anchored on `updated_at`, which dispatch writes when it records the kernel that took the
    run, so the budget measures time since the kernel held the work rather than time since
    the row was created. Nothing else touches the row mid-run, so the anchor holds.

    Safe to call from any reader: it is a no-op for a hogql run, for a run that already
    reached a terminal state, and for one still inside its budget.
    """
    if run.node_type == NotebookNodeRun.NodeType.HOGQL:
        return False
    if run.status != NotebookNodeRun.Status.RUNNING:
        return False
    if (timezone.now() - run.updated_at).total_seconds() <= KERNEL_RUN_RESULT_GRACE_SECONDS:
        return False
    return finish_node_run(
        run,
        NotebookNodeRun.Status.FAILED,
        error="The kernel never reported a result. Re-run the cell.",
        # A lost callback is a timeout, not a user error — the status alone would file it
        # under the same bucket as a failed query.
        outcome=OUTCOME_TIMED_OUT,
    )
