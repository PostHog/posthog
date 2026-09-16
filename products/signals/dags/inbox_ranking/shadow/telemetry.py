"""The shadow read as events, next to the training and unseen series.

The Parquet is the durable record, but a daily object in S3 cannot be charted. One event per
(model, outcome, order) makes the three lines a trends insight with a `ranking_order` breakdown,
so "does the model order better than the list people get" is one chart. The capture plumbing is
the training dag's, shared rather than duplicated.
"""

from collections.abc import Sequence

from products.signals.dags.inbox_ranking.shadow.metrics import RankingGrade
from products.signals.dags.inbox_ranking.training.telemetry import TrainingEvent

SHADOW_RANKING_GRADED_EVENT = "inbox_ranking_shadow_ranking_graded"


def shadow_grade_events(
    *,
    run_id: str,
    served_rows: int,
    served_lists: int,
    score_coverage: float | None,
    grades: Sequence[RankingGrade],
) -> list[TrainingEvent]:
    """The run-level counts ride on every row so a chart can filter on coverage without a join:
    a day whose lists were mostly unscored says little about either order."""
    return [
        TrainingEvent(
            event=SHADOW_RANKING_GRADED_EVENT,
            properties={
                **grade.as_dict(),
                "run_id": run_id,
                "served_rows": served_rows,
                "served_lists": served_lists,
                "score_coverage": score_coverage,
            },
        )
        for grade in grades
    ]
