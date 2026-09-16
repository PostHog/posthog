"""The shadow read as events, next to the training and unseen series.

The Parquet is the durable record, but a daily object in S3 cannot be charted. One event per
(model, outcome, order) makes the three lines a trends insight with a `ranking_order` breakdown,
so "does the model order better than the list people get" is one chart. A run event rides
alongside them, one per partition whether or not anything was graded, so an alert can tell a
quiet day from a run that never finished. The capture plumbing is the training dag's, shared
rather than duplicated.
"""

from collections.abc import Sequence

from products.signals.dags.inbox_ranking.shadow.metrics import RankingGrade
from products.signals.dags.inbox_ranking.training.telemetry import TrainingEvent

SHADOW_RANKING_GRADED_EVENT = "inbox_ranking_shadow_ranking_graded"
SHADOW_RUN_COMPLETED_EVENT = "inbox_ranking_shadow_run_completed"


def shadow_grade_events(
    *,
    run_id: str,
    served_rows: int,
    served_lists: int,
    run_score_coverage: float | None,
    grades: Sequence[RankingGrade],
) -> list[TrainingEvent]:
    """One run event, then one event per grade.

    The run event is unconditional, for the reason `candidate_events` reports a head it could not
    fit: a day that graded nothing is a day with a zero on it, not a gap, and a gap is what a
    crashed run looks like on the same chart. Lists with no score available at impression time
    grade nothing, which is every partition before the first usable scores object.

    The run-level counts ride on every grade event too, so a chart can filter on them without a
    join. Each grade also carries its own `score_coverage`, which is the one to filter a single
    line on.
    """
    reason = None
    if not grades:
        reason = (
            "no_complete_lists"
            if not served_lists
            else "no_available_scores"
            if not run_score_coverage
            else "no_gradeable_outcomes"
        )
    run: dict[str, object] = {
        "run_id": run_id,
        "served_rows": served_rows,
        "served_lists": served_lists,
        "run_score_coverage": run_score_coverage,
    }
    return [
        TrainingEvent(event=SHADOW_RUN_COMPLETED_EVENT, properties={**run, "grades": len(grades), "reason": reason}),
        *(TrainingEvent(event=SHADOW_RANKING_GRADED_EVENT, properties={**grade.as_dict(), **run}) for grade in grades),
    ]
