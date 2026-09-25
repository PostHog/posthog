"""The scoring sweep: a scheduled Temporal workflow that scores the inbox reports that are due.

A report is due when its score is missing or out of date. The served model reads only the report's
vector, so the vector log is the change signal, not `SignalReport.updated_at`: a scout edit saves
`update_fields=["title", "summary"]` and leaves `updated_at` alone, and the grouping pipeline
moves `updated_at` with no text change. A new vector lands only when a rendering's text changes.

Nothing reads the `ranking_score` artefacts to order the inbox yet.
"""

import time
import uuid
import datetime
from collections import defaultdict
from collections.abc import Iterator, Sequence
from typing import Any, cast

from django.conf import settings
from django.utils import timezone

import pydantic
import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.sync import database_sync_to_async
from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.signals.backend.artefact_schemas import RankingScore
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.ranking import scorer
from products.signals.backend.ranking.inventory import SCORABLE_STATUSES, spine_report_filter
from products.signals.backend.ranking.model_store import ModelLoadError, load_serving_set
from products.signals.backend.report_embedding_reader import REPORT_EMBEDDINGS_TABLE
from products.signals.backend.report_embeddings import EMBEDDING_DOCUMENT_TYPE, EMBEDDING_PRODUCT

logger = structlog.get_logger(__name__)

SCORING_WORKFLOW_NAME = "inbox-ranking-scoring-sweep"

# Report ids per Postgres lookup, so a large vector feed does not become one huge `IN` list.
_POSTGRES_BATCH_SIZE = 5000

_ACTIVITY_TIMEOUT = datetime.timedelta(minutes=10)
# The activity timeout does not stop the scoring thread, and the schedule's SKIP stops guarding it
# when the workflow closes. The pass starts no new team after this budget, which is below the
# timeout, so only the team in progress can run past it and into the next tick.
_TIME_BUDGET = datetime.timedelta(minutes=8)

# `timestamp` is the report's `created_at` and the partition key, so the lower bound prunes the
# read to a few weekly partitions. The query does not read the `embedding` column.
CANDIDATE_VECTORS_SQL = f"""
SELECT
    team_id,
    document_id,
    max(inserted_at) AS vector_inserted_at
FROM {REPORT_EMBEDDINGS_TABLE}
WHERE product = %(product)s
  AND document_type = %(document_type)s
  AND rendering = %(rendering)s
  AND timestamp >= %(since)s
GROUP BY team_id, document_id
HAVING argMax(JSONExtractBool(metadata, 'deleted'), inserted_at) = 0
"""

# The scan is cross-team, so it cannot use the `team_id` sort-key prefix, and its cost grows with the
# whole window. The time cap sits well inside `_TIME_BUDGET`, so a slow scan fails the tick with an
# error instead of running into the activity timeout. It throws because a partial GROUP BY would
# give a wrong newest-vector time.
CANDIDATE_VECTORS_QUERY_SETTINGS: dict[str, int | str] = {
    "max_execution_time": 180,
    "timeout_overflow_mode": "throw",
}


@frozen
class ScoringCandidate:
    team_id: int
    report_id: str
    vector_inserted_at: datetime.datetime


@frozen
class ScoreInboxReportsInput:
    # A manual run can override the per-tick cap.
    limit: int | None = None


@frozen
class ScoreInboxReportsResult:
    candidates: int = 0
    scored: int = 0
    no_vector: int = 0
    teams: int = 0
    failed_teams: int = 0
    # Teams not started because the time budget ran out. The next tick scores them.
    deferred_teams: int = 0
    manifest_version: str | None = None
    # "disabled" or "no manifest". None when the pass ran.
    skipped_reason: str | None = None


def _batches(items: Sequence[str]) -> Iterator[Sequence[str]]:
    for start in range(0, len(items), _POSTGRES_BATCH_SIZE):
        yield items[start : start + _POSTGRES_BATCH_SIZE]


def _utc(value: datetime.datetime) -> datetime.datetime:
    # ClickHouse returns a naive DateTime in UTC.
    return value.replace(tzinfo=datetime.UTC) if value.tzinfo is None else value.astimezone(datetime.UTC)


def _live_vectors(since: datetime.datetime, rendering: str) -> dict[str, tuple[int, datetime.datetime]]:
    """Report id to `(team_id, newest vector time)`, for each report whose newest row is live."""
    tag_queries(product=Product.SIGNALS, feature=Feature.ENRICHMENT, query_type="inbox_ranking_sweep_candidates")
    rows = cast(
        list[tuple[Any, ...]],
        sync_execute(
            CANDIDATE_VECTORS_SQL,
            {
                "product": EMBEDDING_PRODUCT,
                "document_type": EMBEDDING_DOCUMENT_TYPE,
                "rendering": rendering,
                "since": since.astimezone(datetime.UTC).replace(tzinfo=None),
            },
            settings=CANDIDATE_VECTORS_QUERY_SETTINGS,
            workload=Workload.OFFLINE,
        )
        or [],
    )
    vectors: dict[str, tuple[int, datetime.datetime]] = {}
    for team_id, document_id, inserted_at in rows:
        try:
            report_id = str(uuid.UUID(str(document_id)))
        except ValueError:
            # A document id that is not a report UUID would fail the Postgres lookup.
            continue
        vectors[report_id] = (int(team_id), _utc(inserted_at))
    return vectors


def _scorable_report_teams(
    report_ids: Sequence[str], now: datetime.datetime, since: datetime.datetime
) -> dict[str, int]:
    teams: dict[str, int] = {}
    for batch in _batches(report_ids):
        rows = (
            SignalReport.objects.filter(spine_report_filter(now))
            .filter(id__in=batch, status__in=SCORABLE_STATUSES, created_at__gte=since)
            .values_list("id", "team_id")
        )
        teams.update({str(report_id): team_id for report_id, team_id in rows})
    return teams


def _latest_scores(report_ids: Sequence[str]) -> dict[str, RankingScore | None]:
    """The latest `ranking_score` of each report that has one. A row that no longer parses is None."""
    scores: dict[str, RankingScore | None] = {}
    for batch in _batches(report_ids):
        rows = (
            SignalReportArtefact.objects.filter(
                report_id__in=batch, type=SignalReportArtefact.ArtefactType.RANKING_SCORE
            )
            .order_by("report_id", "-created_at")
            .distinct("report_id")
            .values_list("report_id", "content")
        )
        for report_id, content in rows:
            try:
                scores[str(report_id)] = RankingScore.model_validate_json(content)
            except pydantic.ValidationError:
                scores[str(report_id)] = None
    return scores


def _is_due(score: RankingScore | None, vector_inserted_at: datetime.datetime, manifest_version: str) -> bool:
    return (
        score is None
        or score.embedding_inserted_at is None
        or vector_inserted_at > score.embedding_inserted_at
        or score.manifest_version != manifest_version
    )


def reports_due_for_scoring(
    now: datetime.datetime, *, manifest_version: str, rendering: str, limit: int
) -> list[ScoringCandidate]:
    """In-window scorable reports whose score is missing, older than their vector, or from another manifest.

    Unscored reports come first, then the oldest scores, so no report starves under the cap. A
    report with no live vector is never a candidate, so a safety-suppressed or retracted report is
    not retried every tick. It comes back when a new vector lands.
    """
    since = now - datetime.timedelta(days=settings.INBOX_RANKING_SCORING_MAX_AGE_DAYS)
    vectors = _live_vectors(since, rendering)
    report_teams = _scorable_report_teams(list(vectors), now, since)
    kept = [report_id for report_id, team_id in report_teams.items() if vectors[report_id][0] == team_id]
    latest = _latest_scores(kept)

    due: list[tuple[datetime.datetime | None, ScoringCandidate]] = []
    for report_id in kept:
        team_id, vector_inserted_at = vectors[report_id]
        score = latest.get(report_id)
        if not _is_due(score, vector_inserted_at, manifest_version):
            continue
        candidate = ScoringCandidate(team_id=team_id, report_id=report_id, vector_inserted_at=vector_inserted_at)
        due.append((score.scored_at if score else None, candidate))
    due.sort(key=lambda item: (item[0] is not None, item[0] or now, item[1].report_id))
    return [candidate for _, candidate in due[:limit]]


def score_inbox_reports(limit: int | None = None) -> ScoreInboxReportsResult:
    if not settings.INBOX_RANKING_SCORING_ENABLED:
        return ScoreInboxReportsResult(skipped_reason="disabled")
    deadline = time.monotonic() + _TIME_BUDGET.total_seconds()
    # A served model that does not load raises here and aborts the run.
    serving = load_serving_set()
    if serving is None:
        return ScoreInboxReportsResult(skipped_reason="no manifest")
    manifest_version = serving.manifest.manifest_version
    now = timezone.now()
    candidates = reports_due_for_scoring(
        now,
        manifest_version=manifest_version,
        rendering=scorer.served_rendering(serving),
        limit=limit or settings.INBOX_RANKING_SCORING_MAX_REPORTS_PER_TICK,
    )
    ids_by_team: dict[int, list[str]] = defaultdict(list)
    for candidate in candidates:
        ids_by_team[candidate.team_id].append(candidate.report_id)

    scored = no_vector = failed_teams = deferred_teams = 0
    for team_id, report_ids in ids_by_team.items():
        if time.monotonic() >= deadline:
            deferred_teams += 1
            continue
        try:
            outcomes = scorer.score_reports(team_id, report_ids, persist=True, now=now)
        except (scorer.ScoringError, ModelLoadError):
            # A pass without a served score is worse than no pass.
            raise
        except Exception:
            logger.exception("inbox_ranking_sweep_team_failed", team_id=team_id)
            failed_teams += 1
            continue
        scored += sum(1 for outcome in outcomes if outcome.score is not None)
        no_vector += sum(1 for outcome in outcomes if outcome.reason == scorer.NO_VECTOR)

    result = ScoreInboxReportsResult(
        candidates=len(candidates),
        scored=scored,
        no_vector=no_vector,
        teams=len(ids_by_team),
        failed_teams=failed_teams,
        deferred_teams=deferred_teams,
        manifest_version=manifest_version,
    )
    logger.info(
        "inbox_ranking_sweep_finished",
        candidates=result.candidates,
        scored=result.scored,
        no_vector=result.no_vector,
        teams=result.teams,
        failed_teams=result.failed_teams,
        deferred_teams=result.deferred_teams,
        manifest_version=result.manifest_version,
    )
    return result


@activity.defn
@scoped_temporal()
@close_db_connections
async def score_inbox_reports_activity(input: ScoreInboxReportsInput) -> ScoreInboxReportsResult:
    return await database_sync_to_async(score_inbox_reports, thread_sensitive=False)(input.limit)


@workflow.defn(name=SCORING_WORKFLOW_NAME)
class InboxRankingScoringWorkflow:
    @workflow.run
    async def run(self, inputs: ScoreInboxReportsInput) -> ScoreInboxReportsResult:
        return await workflow.execute_activity(
            score_inbox_reports_activity,
            inputs,
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            # No retry: a timed-out attempt keeps running in its thread, so a second attempt could
            # score the same batch at the same time. The next tick finds what this one left,
            # because the vector comparison finds it again.
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
