from datetime import timedelta
from typing import Any

from django.db import connection
from django.utils import timezone

from .base import Recommendation

# Don't fire the recommendation unless we have a meaningful sample.
# Tiny teams with a couple of errors shouldn't get a noisy card.
MIN_SAMPLE_FRAMES = 20

# Show the card when more than this fraction of recent JS/TS frames are unresolved.
UNRESOLVED_THRESHOLD = 0.30

LOOKBACK_HOURS = 24

# The card reports a ratio, so the newest frames answer it as well as all of them.
# Without a cap the scan grows with a team's frame volume and never stops growing.
SAMPLE_FRAMES = 2000

# `lang` is set on the resolved frame contents by cymbal — both browser JS and Node
# frames are tagged "javascript". TypeScript frames also surface as "javascript"
# pre-resolution; the source map is what would map them back to the original .ts
# source, so they're exactly the population we care about here.
#
# The language test and the column list must stay byte-identical to
# et_frame_team_created_js_idx: the predicate has to match the index's own predicate
# for Postgres to use the partial index, and reading a column outside the index pulls
# the heap row, which detoasts the wide `contents` column with it. A LATERAL per team
# keeps the query count constant over the batch while each scan stops at the LIMIT.
SAMPLE_QUERY = """
SELECT sample.team_id, sample.resolved, count(*) AS frames
FROM unnest(%s::int[]) AS requested(team_id)
CROSS JOIN LATERAL (
    SELECT frame.team_id, frame.resolved
    FROM posthog_errortrackingstackframe frame
    WHERE frame.team_id = requested.team_id
      AND frame.created_at >= %s
      AND (frame.contents -> 'lang') = '"javascript"'::jsonb
    ORDER BY frame.created_at DESC
    LIMIT %s
) AS sample
GROUP BY 1, 2
"""


class SourceMapsRecommendation(Recommendation):
    type = "source_maps"
    refresh_interval = timedelta(hours=6)

    def compute_batch(self, team_ids: list[int]) -> dict[int, dict[str, Any]]:
        since = timezone.now() - timedelta(hours=LOOKBACK_HOURS)

        with connection.cursor() as cursor:
            cursor.execute(SAMPLE_QUERY, [team_ids, since, SAMPLE_FRAMES])
            rows = cursor.fetchall()

        counts_by_team: dict[int, dict[str, int]] = {}
        for team_id, resolved, frames in rows:
            counts = counts_by_team.setdefault(team_id, {"total": 0, "unresolved": 0})
            counts["total"] += frames
            if not resolved:
                counts["unresolved"] += frames

        return {team_id: self._build_meta(counts_by_team.get(team_id)) for team_id in team_ids}

    @staticmethod
    def _build_meta(counts: dict[str, Any] | None) -> dict[str, Any]:
        total = (counts or {}).get("total") or 0
        unresolved = (counts or {}).get("unresolved") or 0
        unresolved_pct = (unresolved / total) if total > 0 else 0.0

        return {
            "total_frames": total,
            "unresolved_frames": unresolved,
            "unresolved_pct": unresolved_pct,
            "threshold_pct": UNRESOLVED_THRESHOLD,
            "min_sample_frames": MIN_SAMPLE_FRAMES,
            "sample_frames": SAMPLE_FRAMES,
            "lookback_hours": LOOKBACK_HOURS,
        }

    def is_completed(self, meta: dict[str, Any]) -> bool:
        total = meta.get("total_frames") or 0
        if total < MIN_SAMPLE_FRAMES:
            return True
        unresolved_pct = meta.get("unresolved_pct") or 0.0
        threshold = meta.get("threshold_pct") or UNRESOLVED_THRESHOLD
        return unresolved_pct <= threshold
