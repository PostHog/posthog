"""The scoring sweep: a scheduled Temporal workflow that scores inbox reports with the champion.

Shadow mode. Every tick scores the reports that are due - never scored, changed since their last
score, or last scored longer ago than the re-score interval - and appends one `SignalReportScore`
row per report. Nothing reads the rows to order the inbox yet; they exist so the online read
(issue 15 in the `inbox-ranking` skill) can compare the model's order against the heuristic's, and
so the next training run can learn from the exact features the model saw.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db.models import F, OuterRef, Q, QuerySet, Subquery
from django.utils import timezone

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.sync import database_sync_to_async
from posthog.temporal.common.scoped import scoped_temporal

from products.signals.backend.models import SignalReport, SignalReportScore
from products.signals.backend.ranking.inventory import SCORABLE_STATUSES, inventory_filter
from products.signals.backend.ranking.judgments import latest_judgments
from products.signals.backend.ranking.model_store import load_champion
from products.signals.backend.ranking.scorer import score_reports

logger = structlog.get_logger(__name__)

SCORING_WORKFLOW_NAME = "inbox-ranking-scoring-sweep"


@dataclass(frozen=True)
class ScoreInboxReportsInput:
    # Settings are read in the activity; the input exists so a manual run can override the batch.
    limit: int | None = None


@dataclass(frozen=True)
class ScoreInboxReportsResult:
    scored: int
    model_version: str | None
    skipped_reason: str | None


def reports_due_for_scoring(now, limit: int) -> QuerySet[SignalReport]:  # noqa: ANN001
    """Scorable inventory that has no score yet, changed since its last score (signal ingestion and
    status changes bump `updated_at`), or was last scored longer ago than the re-score interval."""
    latest_score = (
        SignalReportScore.all_teams.filter(report_id=OuterRef("pk")).order_by("-scored_at").values("scored_at")[:1]
    )
    return (
        SignalReport.objects.filter(inventory_filter(now))
        .filter(
            status__in=SCORABLE_STATUSES,
            created_at__gte=now - timedelta(days=settings.SIGNALS_RANKING_SCORE_MAX_AGE_DAYS),
        )
        .annotate(last_scored_at=Subquery(latest_score))
        .filter(
            Q(last_scored_at__isnull=True)
            | Q(updated_at__gt=F("last_scored_at"))
            | Q(last_scored_at__lt=now - timedelta(hours=settings.SIGNALS_RANKING_RESCORE_HOURS))
        )
        .order_by("created_at")[:limit]
    )


def score_inbox_reports(limit: int | None = None) -> ScoreInboxReportsResult:
    if not settings.SIGNALS_RANKING_SCORING_ENABLED:
        return ScoreInboxReportsResult(scored=0, model_version=None, skipped_reason="disabled")
    model = load_champion()
    if model is None:
        return ScoreInboxReportsResult(scored=0, model_version=None, skipped_reason="no champion")
    if not model.boosters:
        return ScoreInboxReportsResult(scored=0, model_version=model.model_version, skipped_reason="no readable head")

    now = timezone.now()
    reports = list(reports_due_for_scoring(now, limit or settings.SIGNALS_RANKING_SCORE_BATCH_LIMIT))
    if not reports:
        return ScoreInboxReportsResult(scored=0, model_version=model.model_version, skipped_reason=None)
    judgments = latest_judgments([str(report.id) for report in reports], now)
    scored = score_reports(model, reports, judgments, now)
    SignalReportScore.all_teams.bulk_create(
        [
            SignalReportScore(
                team_id=item.team_id,
                report_id=item.report_id,
                model_version=model.model_version,
                feature_schema_version=model.feature_schema_version,
                features=item.features,
                scores=item.scores,
                scored_at=now,
            )
            for item in scored
        ],
        batch_size=500,
    )
    logger.info("inbox ranking sweep scored reports", scored=len(scored), model_version=model.model_version)
    return ScoreInboxReportsResult(scored=len(scored), model_version=model.model_version, skipped_reason=None)


@activity.defn
@scoped_temporal()
async def score_inbox_reports_activity(input: ScoreInboxReportsInput) -> ScoreInboxReportsResult:
    return await database_sync_to_async(score_inbox_reports, thread_sensitive=False)(input.limit)


@workflow.defn(name=SCORING_WORKFLOW_NAME)
class InboxRankingScoringWorkflow:
    @workflow.run
    async def run(self, inputs: ScoreInboxReportsInput) -> ScoreInboxReportsResult:
        result = await workflow.execute_activity(
            score_inbox_reports_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        workflow.logger.info(
            "inbox ranking sweep finished",
            extra={"scored": result.scored, "model_version": result.model_version, "skipped": result.skipped_reason},
        )
        return result
