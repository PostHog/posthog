from datetime import timedelta
from functools import partial

from django.db.models import Count, Max
from django.utils import timezone

from posthog.models import FileSystemViewLog

from ...facade.enums import HighlightMetricReason
from ..highlight_types import Context, Found, Source
from ..pulse_pins import INSIGHT_PREFIX
from .routine import ViewedItem, own_candidates, progressive_metrics

ROW_TILES = 4
POPULAR_DAYS = 30
POPULAR_REFS = 12
MIN_VIEWERS = 2


def _popular_refs(context: Context) -> list[str]:
    rows = (
        FileSystemViewLog.objects.filter(
            team=context.team, type="insight", viewed_at__gte=timezone.now() - timedelta(days=POPULAR_DAYS)
        )
        .values("ref")
        .annotate(viewers=Count("user_id", distinct=True), last_viewed=Max("viewed_at"))
        .filter(viewers__gte=MIN_VIEWERS)
        .order_by("-viewers", "-last_viewed", "ref")[:POPULAR_REFS]
    )
    return [row["ref"] for row in rows]


def find(context: Context) -> Found:
    excluded = context.pinned | context.hidden
    own = own_candidates(context, excluded)
    free = ROW_TILES - len(context.pinned) - len(own)
    if free <= 0:
        return Found()
    none: list[str] = []
    refs = context.guard(
        "popular insights", partial(context.daily, "popular_insights", partial(_popular_refs, context)), none
    )
    known = {item.ref for item in own if item.kind == "insight"}
    items = [
        ViewedItem(kind="insight", ref=ref, days=frozenset(), reason=HighlightMetricReason.POPULAR)
        for ref in refs
        if ref not in known and f"{INSIGHT_PREFIX}{ref}" not in excluded
    ]
    return Found(pulse=tuple(progressive_metrics(context, excluded, free, items)))


SOURCE = Source(name="popular", find=find, scopes=("insight:read",), pulse_order=3)
