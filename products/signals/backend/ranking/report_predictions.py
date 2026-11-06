"""Read the served model's predictions for one report from its latest `ranking_score` artefact.

The `ranking` field of the report serializer and the personal inbox ranking both read predictions here, so
they agree on what scored, stale and unscored mean.
"""

from datetime import datetime
from typing import Literal

import structlog

from posthog.dataclasses import frozen

from products.signals.backend.artefact_schemas import RankingScore
from products.signals.backend.models import SignalReportArtefact
from products.signals.backend.ranking.public_outcomes import PUBLIC_OUTCOMES, PublicOutcomeName
from products.signals.backend.ranking.staleness import is_stale_score

logger = structlog.get_logger(__name__)

PredictionStatus = Literal["scored", "stale", "unscored"]


@frozen
class OutcomePrediction:
    outcome: PublicOutcomeName
    probability: float
    # Null when the model has no saved base rate for the outcome.
    lift: float | None
    readable: bool


@frozen
class ReportPredictions:
    status: PredictionStatus
    model: str | None = None
    scored_at: datetime | None = None
    predictions: tuple[OutcomePrediction, ...] = ()

    def probability(self, outcome: PublicOutcomeName) -> float | None:
        """The probability that the model sorts and filters use: None unless the score describes the current text."""
        if self.status != "scored":
            return None
        return next((entry.probability for entry in self.predictions if entry.outcome == outcome), None)


UNSCORED = ReportPredictions(status="unscored")


def read_report_predictions(
    artefact: SignalReportArtefact | None, latest_edit_at: datetime | None
) -> ReportPredictions:
    """`artefact` is the report's latest `ranking_score` artefact, and `latest_edit_at` the time of its latest edit artefact."""
    from products.signals.backend.ranking.model_contract import (  # noqa: PLC0415 — keeps numpy and pandas off the API import path
        head_lifts,
        readable_head_names,
    )

    if artefact is None:
        return UNSCORED
    try:
        score = RankingScore.model_validate_json(artefact.content)
        served = score.results[score.served_key]
    except (ValueError, KeyError):
        logger.warning(
            "signals.ranking_score.invalid_content", report_id=str(artefact.report_id), artefact_id=str(artefact.id)
        )
        return UNSCORED
    # The ranking filters read the score alone, so bad readability or threshold metadata must not hide it here.
    try:
        readable_heads = readable_head_names(served.metadata)
    except (KeyError, TypeError, AttributeError):
        readable_heads = frozenset()
    try:
        # A score written before lifts were stored carries the metadata to compute them.
        lifts = served.lifts or head_lifts(served.scores, served.metadata)
    except (ValueError, KeyError, TypeError, AttributeError):
        lifts = {}
    predictions = tuple(
        OutcomePrediction(
            outcome=entry.outcome,
            probability=probability,
            lift=lifts.get(entry.model_head),
            readable=entry.model_head in readable_heads,
        )
        for entry in PUBLIC_OUTCOMES
        if (probability := served.scores.get(entry.model_head)) is not None
    )
    if not predictions:
        return UNSCORED
    return ReportPredictions(
        status="stale" if is_stale_score(score, latest_edit_at) else "scored",
        model=score.served_key,
        scored_at=score.scored_at,
        predictions=predictions,
    )
