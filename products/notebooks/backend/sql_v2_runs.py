"""Claim a NotebookNodeRun's RUNNING -> terminal transition and report it exactly once.

Every lane that finishes a run funnels through `finish_node_run`: the direct (hogql)
lane's pollers and grace-expiry watchdog, dispatch failures (the run view and the
Temporal mark-failed activity), and the interrupt endpoints. The sandbox callback is
the one deliberate exception — it upserts losing deliveries too, so a late real result
can overwrite an interrupt placeholder — and keeps its own block in sql_v2_callback.py.
"""

from typing import Any

from django.utils import timezone

from products.notebooks.backend.models import NotebookNodeRun
from products.notebooks.backend.sql_v2_metrics import outcome_for_status, record_node_run_terminal


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
