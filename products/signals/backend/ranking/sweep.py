"""The scoring sweep: a scheduled Temporal workflow that scores inbox reports with the serving set.

A report needs a score when its newest live vector is newer than the vector its latest score read,
or when the manifest changed since that score. The vector log is the change signal, because a new
vector lands only when a rendering's text changes. `SignalReport.updated_at` does not work: a scout
edit changes the text and leaves it as it is, and grouping moves it with no change to the text.

Nothing reads the scores to order the inbox yet.
"""

import uuid
import datetime
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, cast

from django.conf import settings
from django.utils import timezone

import structlog
from pydantic import ValidationError
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.sync import database_sync_to_async
from posthog.temporal.common.scoped import scoped_temporal

from products.signals.backend.artefact_schemas import RankingScore
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.ranking.inventory import SCORABLE_STATUSES, spine_report_filter
from products.signals.backend.ranking.model_store import ModelLoadError, load_serving_set
from products.signals.backend.ranking.scorer import NO_VECTOR, ScoringError, score_reports, served_rendering
from products.signals.backend.report_embedding_reader import REPORT_EMBEDDINGS_TABLE
from products.signals.backend.report_embeddings import EMBEDDING_DOCUMENT_TYPE, EMBEDDING_PRODUCT

logger = structlog.get_logger(__name__)

SCORING_WORKFLOW_NAME = "inbox-ranking-scoring-sweep"
SKIPPED_DISABLED = "disabled"
SKIPPED_NO_MANIFEST = "no manifest"

# Well under the default 15-minute interval, so a slow tick ends before the next one is due.
ACTIVITY_TIMEOUT = datetime.timedelta(minutes=10)

# `timestamp` is the report's `created_at` and the table is partitioned by `toMonday(timestamp)`,
# so the age filter prunes the read to a few weekly partitions. The `embedding` column is not read.
VECTOR_FEED_SQL = f"""
SELECT
    team_id,
    document_id,
    max(inserted_at) AS vector_inserted_at,
    argMax(JSONExtractBool(metadata, 'deleted'), inserted_at) AS is_tombstone
FROM {REPORT_EMBEDDINGS_TABLE}
WHERE product = %(product)s
  AND document_type = %(document_type)s
  AND rendering = %(rendering)s
  AND timestamp >= %(since)s
GROUP BY team_id, document_id
HAVING is_tombstone = 0
"""


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
    candidates: int
    scored: int
    no_vector: int
    teams: int
    failed_teams: int
    manifest_version: str | None
    skipped_reason: str | None


def _utc(value: datetime.datetime) -> datetime.datetime:
    # ClickHouse returns a naive DateTime in UTC.
    return value.replace(tzinfo=datetime.UTC) if value.tzinfo is None else value.astimezone(datetime.UTC)


def _live_vectors(since: datetime.datetime, rendering: str) -> dict[str, tuple[int, datetime.datetime]]:
    """The newest live vector time of each report, keyed by report id, with the vector's team id."""
    tag_queries(product=Product.SIGNALS, feature=Feature.ENRICHMENT, query_type="inbox_ranking_sweep_candidates")
    rows = cast(
        list[tuple[Any, ...]],
        sync_execute(
            VECTOR_FEED_SQL,
            {
                "product": EMBEDDING_PRODUCT,
                "document_type": EMBEDDING_DOCUMENT_TYPE,
                "rendering": rendering,
                "since": since,
            },
            workload=Workload.OFFLINE,
        )
        or [],
    )
    vectors: dict[str, tuple[int, datetime.datetime]] = {}
    for team_id, document_id, inserted_at, _ in rows:
        try:
            report_id = str(uuid.UUID(str(document_id)))
        except ValueError:
            continue
        vectors[report_id] = (int(team_id), _utc(inserted_at))
    return vectors


def _chunks(values: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _scorable_team_ids(report_ids: Sequence[str], now: datetime.datetime, since: datetime.datetime) -> dict[str, int]:
    team_ids: dict[str, int] = {}
    for chunk in _chunks(report_ids, settings.INBOX_RANKING_SCORING_BATCH_SIZE):
        rows = (
            SignalReport.objects.filter(spine_report_filter(now))
            .filter(id__in=chunk, status__in=SCORABLE_STATUSES, created_at__gte=since)
            .values_list("id", "team_id")
        )
        team_ids.update({str(report_id): team_id for report_id, team_id in rows})
    return team_ids


def _latest_scores(report_ids: Sequence[str]) -> dict[str, RankingScore]:
    """The latest `ranking_score` of each report. A row that does not parse counts as no score."""
    scores: dict[str, RankingScore] = {}
    for chunk in _chunks(report_ids, settings.INBOX_RANKING_SCORING_BATCH_SIZE):
        rows = (
            SignalReportArtefact.objects.filter(
                report_id__in=chunk, type=SignalReportArtefact.ArtefactType.RANKING_SCORE
            )
            .order_by("report_id", "-created_at")
            .distinct("report_id")
            .values_list("report_id", "content")
        )
        for report_id, content in rows:
            try:
                scores[str(report_id)] = RankingScore.model_validate_json(content)
            except ValidationError:
                logger.warning("inbox_ranking_score_unreadable", report_id=str(report_id))
    return scores


def _is_due(vector_inserted_at: datetime.datetime, score: RankingScore | None, manifest_version: str) -> bool:
    if score is None or score.embedding_inserted_at is None:
        return True
    return vector_inserted_at > score.embedding_inserted_at or score.manifest_version != manifest_version


def reports_due_for_scoring(
    now: datetime.datetime, *, manifest_version: str, rendering: str, limit: int
) -> list[ScoringCandidate]:
    """Scorable reports whose newest live vector in `rendering` has no score under this manifest.

    Unscored reports come first, then the oldest scores, so no report starves under the cap. A
    report with no live vector is never a candidate, so a suppressed or retracted report is not
    tried again on every tick. It comes back when a new vector lands.
    """
    since = now - datetime.timedelta(days=settings.INBOX_RANKING_SCORING_MAX_AGE_DAYS)
    vectors = _live_vectors(since, rendering)
    team_ids = _scorable_team_ids(sorted(vectors), now, since)
    # The report row owns the team id. A vector filed under another team is not this report's.
    kept = sorted(report_id for report_id, team_id in team_ids.items() if vectors[report_id][0] == team_id)
    latest = _latest_scores(kept)

    due: list[tuple[tuple[bool, datetime.datetime, str], ScoringCandidate]] = []
    for report_id in kept:
        vector_inserted_at = vectors[report_id][1]
        score = latest.get(report_id)
        if not _is_due(vector_inserted_at, score, manifest_version):
            continue
        order_key = (score is not None, score.scored_at if score else vector_inserted_at, report_id)
        due.append(
            (
                order_key,
                ScoringCandidate(
                    team_id=team_ids[report_id], report_id=report_id, vector_inserted_at=vector_inserted_at
                ),
            )
        )
    due.sort(key=lambda item: item[0])
    return [candidate for _, candidate in due[:limit]]


def _by_team(candidates: Sequence[ScoringCandidate]) -> Mapping[int, list[str]]:
    grouped: defaultdict[int, list[str]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.team_id].append(candidate.report_id)
    return grouped


def score_inbox_reports(limit: int | None = None) -> ScoreInboxReportsResult:
    if not settings.INBOX_RANKING_SCORING_ENABLED:
        return ScoreInboxReportsResult(
            candidates=0,
            scored=0,
            no_vector=0,
            teams=0,
            failed_teams=0,
            manifest_version=None,
            skipped_reason=SKIPPED_DISABLED,
        )
    # Raises when the served model does not load: a pass without a served score is worse than no pass.
    serving = load_serving_set()
    if serving is None:
        return ScoreInboxReportsResult(
            candidates=0,
            scored=0,
            no_vector=0,
            teams=0,
            failed_teams=0,
            manifest_version=None,
            skipped_reason=SKIPPED_NO_MANIFEST,
        )
    manifest_version = serving.manifest.manifest_version
    rendering = served_rendering(serving.served.feature_set)
    if rendering is None:
        raise ScoringError(
            f"served model {serving.served.entry.key} is on feature set {serving.served.feature_set.name}, not served yet"
        )

    now = timezone.now()
    candidates = reports_due_for_scoring(
        now,
        manifest_version=manifest_version,
        rendering=rendering,
        limit=limit or settings.INBOX_RANKING_SCORING_MAX_REPORTS_PER_TICK,
    )
    by_team = _by_team(candidates)
    scored = no_vector = failed_teams = 0
    for team_id, report_ids in by_team.items():
        try:
            outcomes = score_reports(team_id, report_ids, persist=True, now=now)
        except (ScoringError, ModelLoadError):
            raise
        except Exception:
            logger.exception("inbox_ranking_sweep_team_failed", team_id=team_id)
            failed_teams += 1
            continue
        scored += sum(1 for outcome in outcomes if outcome.score is not None)
        no_vector += sum(1 for outcome in outcomes if outcome.reason == NO_VECTOR)

    result = ScoreInboxReportsResult(
        candidates=len(candidates),
        scored=scored,
        no_vector=no_vector,
        teams=len(by_team),
        failed_teams=failed_teams,
        manifest_version=manifest_version,
        skipped_reason=None,
    )
    logger.info(
        "inbox_ranking_sweep_finished",
        candidates=result.candidates,
        scored=result.scored,
        no_vector=result.no_vector,
        teams=result.teams,
        failed_teams=result.failed_teams,
        manifest_version=result.manifest_version,
    )
    return result


@activity.defn
@scoped_temporal()
async def score_inbox_reports_activity(input: ScoreInboxReportsInput) -> ScoreInboxReportsResult:
    return await database_sync_to_async(score_inbox_reports, thread_sensitive=False)(input.limit)


@workflow.defn(name=SCORING_WORKFLOW_NAME)
class InboxRankingScoringWorkflow:
    @workflow.run
    async def run(self, inputs: ScoreInboxReportsInput) -> ScoreInboxReportsResult:
        return await workflow.execute_activity(
            score_inbox_reports_activity,
            inputs,
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            # No retry: a timed-out attempt keeps running in its thread, so a second attempt would
            # score the same batch at the same time. The next tick finds what this one left.
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
