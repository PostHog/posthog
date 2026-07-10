import datetime as dt

from django.utils import timezone

import structlog

from products.pulse.backend.models import ProductBrief

logger = structlog.get_logger(__name__)

# Headroom above the workflow execution_timeout (currently 20m for the synthesize path; kept at
# 60m so a longer-running engine stays covered) so a brief still legitimately running is never
# reaped early.
STALE_AFTER = dt.timedelta(minutes=60)
BATCH_SIZE = 500
REASON = (
    "Generation exceeded the maximum runtime and was reaped. The workflow was likely terminated "
    "externally (execution timeout, worker restart, or crash), so the in-workflow failure path "
    "never ran to mark this brief FAILED."
)


def mark_stale_briefs_failed() -> int:
    """Reconcile briefs stranded in GENERATING by an externally-terminated workflow.

    A brief only leaves GENERATING from inside the workflow (success, or the ``except`` path that
    runs ``mark_brief_failed``). Anything that kills the workflow from outside — the execution
    timeout firing, a worker dying, an OOM — bypasses that, leaving the row GENERATING forever with
    no error. This periodic sweep is the backstop: it flips briefs stuck past ``STALE_AFTER`` to
    FAILED. Cross-team by design, so it reads through ``all_teams``. Ids are materialized first to
    avoid a self-referential update cursor, then a single set-based UPDATE re-asserts
    ``status=GENERATING`` so any row a worker finished between the select and the update is
    excluded atomically.
    """
    cutoff = timezone.now() - STALE_AFTER
    stale_ids = list(
        ProductBrief.all_teams.filter(status=ProductBrief.Status.GENERATING, updated_at__lt=cutoff).values_list(
            "id", flat=True
        )[:BATCH_SIZE]
    )
    if not stale_ids:
        return 0
    reaped = ProductBrief.all_teams.filter(id__in=stale_ids, status=ProductBrief.Status.GENERATING).update(
        status=ProductBrief.Status.FAILED, error=REASON, updated_at=timezone.now()
    )
    if reaped:
        logger.warning("pulse_stale_briefs_reaped", count=reaped, stale_after_minutes=STALE_AFTER.total_seconds() / 60)
    if len(stale_ids) == BATCH_SIZE:
        # Hit the cap; the next scheduled run drains the rest rather than doing it all in one pass.
        logger.warning("pulse_stale_brief_sweep_hit_batch_cap", batch_size=BATCH_SIZE)
    return reaped
