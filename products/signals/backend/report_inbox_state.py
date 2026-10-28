"""Daily check that the cached implementation PR flags still agree with the link tables.

Receivers keep `has_implementation_pr` and `has_active_implementation_pr` current, but a bulk write
that skips Django signals can leave a row stale. This sweep counts those rows as drift, then
corrects them. Sustained zero drift is the evidence that the inbox can read the columns instead of
the live subqueries.
"""

from django.db.models import F, Q

import structlog
from prometheus_client import Counter

from products.signals.backend.implementation_pr_cache import (
    live_implementation_pr_flags,
    refresh_implementation_pr_cache,
)
from products.signals.backend.models import SignalReport

logger = structlog.get_logger(__name__)

IMPLEMENTATION_PR_CACHE_DRIFT = Counter(
    "signals_implementation_pr_cache_drift_total",
    "Reports whose cached implementation PR flags disagreed with the link tables and were corrected.",
)

_RECONCILE_BATCH_SIZE = 500


def reconcile_report_inbox_state(team_id: int) -> int:
    """Correct the team's reports whose cached flags disagree with the live filter. Returns how many changed."""
    live = live_implementation_pr_flags(team_id)
    stale_ids = list(
        SignalReport.objects.filter(team_id=team_id)
        .annotate(live_has_implementation_pr=live.has_pr, live_has_active_implementation_pr=live.has_active_pr)
        .filter(
            ~Q(has_implementation_pr=F("live_has_implementation_pr"))
            | ~Q(has_active_implementation_pr=F("live_has_active_implementation_pr"))
        )
        .values_list("id", flat=True)
    )
    corrected = 0
    try:
        for start in range(0, len(stale_ids), _RECONCILE_BATCH_SIZE):
            batch = refresh_implementation_pr_cache(
                team_id=team_id, report_ids=stale_ids[start : start + _RECONCILE_BATCH_SIZE]
            )
            # Counted per committed batch, so a later failure cannot hide repairs that already landed.
            IMPLEMENTATION_PR_CACHE_DRIFT.inc(batch)
            corrected += batch
    finally:
        if corrected:
            logger.warning("signals.report_inbox_state.drift_corrected", team_id=team_id, implementation_pr=corrected)
    return corrected


def teams_with_reports() -> list[int]:
    return list(SignalReport.objects.values_list("team_id", flat=True).distinct().order_by("team_id"))
