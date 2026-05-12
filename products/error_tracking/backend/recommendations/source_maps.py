from datetime import timedelta
from typing import Any

from django.db.models import Count, Q
from django.utils import timezone

from posthog.models.team.team import Team

from products.error_tracking.backend.models import ErrorTrackingStackFrame

from .base import Recommendation

# Don't fire the recommendation unless we have a meaningful sample.
# Tiny teams with a couple of errors shouldn't get a noisy card.
MIN_SAMPLE_FRAMES = 20

# Show the card when more than this fraction of recent JS/TS frames are unresolved.
UNRESOLVED_THRESHOLD = 0.30

LOOKBACK_HOURS = 24


class SourceMapsRecommendation(Recommendation):
    type = "source_maps"
    refresh_interval = timedelta(hours=6)

    def compute(self, team: Team) -> dict[str, Any]:
        # `lang` is set on the resolved frame contents by cymbal — both browser JS
        # and Node frames are tagged "javascript". TypeScript frames also surface
        # as "javascript" pre-resolution; the source map is what would map them
        # back to the original .ts source, so they're exactly the population we
        # care about here.
        since = timezone.now() - timedelta(hours=LOOKBACK_HOURS)

        counts = ErrorTrackingStackFrame.objects.filter(
            team=team,
            created_at__gte=since,
            contents__lang="javascript",
        ).aggregate(
            total=Count("id"),
            unresolved=Count("id", filter=Q(resolved=False)),
        )

        total = counts["total"] or 0
        unresolved = counts["unresolved"] or 0
        unresolved_pct = (unresolved / total) if total > 0 else 0.0

        return {
            "total_frames": total,
            "unresolved_frames": unresolved,
            "unresolved_pct": unresolved_pct,
            "threshold_pct": UNRESOLVED_THRESHOLD,
            "min_sample_frames": MIN_SAMPLE_FRAMES,
            "lookback_hours": LOOKBACK_HOURS,
        }

    def is_completed(self, meta: dict[str, Any]) -> bool:
        total = meta.get("total_frames") or 0
        if total < MIN_SAMPLE_FRAMES:
            return True
        unresolved_pct = meta.get("unresolved_pct") or 0.0
        threshold = meta.get("threshold_pct") or UNRESOLVED_THRESHOLD
        return unresolved_pct <= threshold
