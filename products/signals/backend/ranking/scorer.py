"""Turns SignalReport rows into feature vectors and p_<head> scores."""

from collections.abc import Iterable, Mapping
from datetime import datetime

import numpy as np
import xgboost as xgb

from posthog.dataclasses import frozen

from products.signals.backend.models import SignalReport
from products.signals.backend.ranking.features import FEATURE_NAMES, feature_vector
from products.signals.backend.ranking.judgments import Judgment
from products.signals.backend.ranking.model_store import RankingModel


@frozen
class ScoredReport:
    report_id: str
    team_id: int
    features: dict[str, float | None]
    scores: dict[str, float]


def report_feature_row(report: SignalReport, judgment: Judgment | None, now: datetime) -> dict[str, object]:
    """The same columns the dataset dag's report-state snapshot carries, read live."""
    return {
        "signal_count": report.signal_count,
        "total_weight": report.total_weight,
        "run_count": report.run_count,
        "title_chars": len(report.title or ""),
        "summary_chars": len(report.summary or ""),
        "priority": judgment.priority if judgment else None,
        "actionability": judgment.actionability if judgment else None,
        "age_hours": (now - report.created_at).total_seconds() / 3600,
    }


def score_reports(
    model: RankingModel,
    reports: Iterable[SignalReport],
    judgments: Mapping[str, Judgment],
    now: datetime,
) -> list[ScoredReport]:
    reports = list(reports)
    if not reports:
        return []
    vectors = [feature_vector(report_feature_row(report, judgments.get(str(report.id)), now)) for report in reports]
    matrix = xgb.DMatrix(np.asarray(vectors, dtype=np.float32), feature_names=list(FEATURE_NAMES))
    predictions = {head: booster.predict(matrix) for head, booster in model.boosters.items()}
    scored: list[ScoredReport] = []
    for index, report in enumerate(reports):
        # NaN features are stored as None: JSON has no NaN, and the booster's own missing handling
        # already consumed them.
        features = {
            name: (None if np.isnan(value) else float(value))
            for name, value in zip(FEATURE_NAMES, vectors[index], strict=True)
        }
        scored.append(
            ScoredReport(
                report_id=str(report.id),
                team_id=report.team_id,
                features=features,
                scores={head: float(values[index]) for head, values in predictions.items()},
            )
        )
    return scored
