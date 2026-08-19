"""Which reports count as inbox inventory.

Shared by the dataset dag's daily spine and the scoring sweep: the sweep must score exactly the
population the snapshots describe, or the model trains on one inventory and serves another.
"""

from datetime import datetime

from django.db.models import Q

from products.signals.backend.models import SignalReport

# Statuses a report can be authored straight into and still be in the inbox (`create_scout_report`
# and `create_custom_agent_ready_report`), which is how a report reaches the inventory without a
# promotion. Suppressed and deleted are absent on purpose: authored-then-hidden is not inventory.
BORN_VISIBLE_STATUSES = (
    SignalReport.Status.READY,
    SignalReport.Status.PENDING_INPUT,
    SignalReport.Status.IN_PROGRESS,
    SignalReport.Status.RESOLVED,
)

# Inventory a user can still act on; the sweep scores these. Resolved reports stay in the dataset
# spine (their history matters for labels) but there is nothing left to rank.
SCORABLE_STATUSES = (
    SignalReport.Status.READY,
    SignalReport.Status.PENDING_INPUT,
    SignalReport.Status.IN_PROGRESS,
)


def inventory_filter(as_of: datetime) -> Q:
    """Reports that were in the inbox before `as_of`.

    Two ways in, because not every visible report was promoted: the pipeline promotes a `potential`
    report and stamps promoted_at, but the scout and custom-agent authoring paths create a report
    already in a visible status and never stamp it. Keying only on promotion dropped every
    directly-authored report until a user happened to interact with it, biasing the inventory toward
    reports that already had engagement - the wrong bias for a ranking model. A never-promoted report
    is only eligible while it is still visible, so a promotion after the cutoff (promoted_at set, not
    null) still cannot leak in through the second branch."""
    return Q(promoted_at__isnull=False, promoted_at__lt=as_of) | Q(
        promoted_at__isnull=True, status__in=BORN_VISIBLE_STATUSES, created_at__lt=as_of
    )
