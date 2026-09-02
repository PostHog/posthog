"""Baseline timeline for a single snapshot identifier."""

from __future__ import annotations

from uuid import UUID

from django.db import connections

from ..db import READER_DB
from ..models import RunSnapshot
from . import run_queries

_SNAPSHOT_HISTORY_DEDUP_SQL = """
WITH ordered AS (
    SELECT rs.id,
           rs.baseline_artifact_id,
           LAG(rs.baseline_artifact_id) OVER (ORDER BY r.created_at) AS prev_baseline_id,
           r.created_at
    FROM visual_review_runsnapshot rs
    JOIN visual_review_run r ON r.id = rs.run_id
    WHERE r.repo_id = %s
      AND r.run_type = %s
      AND r.branch = ANY(%s)
      AND r.status = 'completed'
      AND rs.identifier = %s
)
SELECT id
FROM ordered
WHERE prev_baseline_id IS DISTINCT FROM baseline_artifact_id
ORDER BY created_at DESC
"""


def get_snapshot_history(repo_id: UUID, identifier: str, run_type: str) -> list[RunSnapshot]:
    """Baseline timeline for a snapshot identifier on the default branch.

    Returns one entry per *baseline transition* — every time the committed
    `.snapshots.yml` baseline actually moved. LAG-on-`baseline_artifact_id`
    (over ASC ordering) keeps the FIRST run of each baseline period, so the
    user sees the inception event plus every change since.

    Why LAG on `baseline_artifact_id` and not `current_artifact_id`:
      - `current_artifact_id` is the bytes captured by THIS run. Pixel jitter
        and tolerated drift produce different content_hash → different Artifact
        rows even though the *baseline* didn't move. Keying on current_ caused
        a prod regression (252 fake history events on a single tolerated-drift
        story) because the artifact alternated between near-identical hashes
        the matcher kept absorbing. LAG-on-current-with-result-filter (the
        prior fix) hid those false events but also hid genuine first-appearance
        rows whose `result=unchanged` against an existing YAML baseline.
      - `baseline_artifact_id` reflects the YAML state at run time. It only
        changes when a baseline-update PR merges. Pixel jitter and tolerated
        drift leave it untouched, so LAG dedup naturally collapses noise while
        catching every real baseline flip — without needing a `result` filter.

    DB-level filters:
      - branch ∈ master/main, run_type, repo: scope to default-branch runs of
        this kind
      - status=completed: drop pre-classification rows where the baseline FK
        hasn't been hydrated yet (pending/processing leave NULL baseline_artifact)
    """
    with connections[READER_DB].cursor() as cursor:
        cursor.execute(
            _SNAPSHOT_HISTORY_DEDUP_SQL,
            [str(repo_id), run_type, list(run_queries._DEFAULT_BRANCHES), identifier],
        )
        ordered_ids: list[UUID] = [row[0] for row in cursor.fetchall()]

    if not ordered_ids:
        return []

    # `id__in` doesn't preserve order, so look rows up by id and re-emit in the
    # cursor's order. Fetched count equals the deduped baseline-event count
    # (typically <20), so this hydration is cheap regardless of raw history size.
    rows_by_id: dict[UUID, RunSnapshot] = {
        row.id: row for row in RunSnapshot.objects.filter(id__in=ordered_ids).select_related("run", "current_artifact")
    }
    return [rows_by_id[rid] for rid in ordered_ids if rid in rows_by_id]
