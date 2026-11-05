"""The three pipeline runs, as plain functions the Temporal activities wrap.

- ``run_sync``: distinct intents of a window that have no vector yet are sent to the embedding worker.
- ``run_assign``: every embedded intent of a window gets its nearest topic, inside ClickHouse.
- ``run_refit``: a sample of the last week's vectors is clustered; clusters are matched to the
  topic registry so ids stay stable; new topics get labels; the week is then re-assigned.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import structlog

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.models.scoping import team_scope
from posthog.models.team.team import Team

from products.mcp_analytics.backend.facade.contracts import (
    IntentGenerationUnavailable,
    IntentTopicsRunOutcome as RunOutcome,
)
from products.mcp_analytics.backend.intent_topics import clustering, corpus, embedding_sync, labeling, persist
from products.mcp_analytics.backend.intent_topics.assignment_sql import build_assignment_insert
from products.mcp_analytics.backend.intent_topics.constants import (
    EMBEDDING_DOCUMENT_TYPE,
    EMBEDDING_MODEL,
    EMBEDDING_PRODUCT,
    FIT_LOOKBACK_DAYS,
    FIT_SAMPLE_SIZE,
    MAX_INTENTS_PER_SYNC,
    MIN_INTENTS_FOR_FIT,
)
from products.mcp_analytics.backend.intent_topics.topic_registry import match_clusters_to_topics
from products.mcp_analytics.backend.models import MCPIntentClusteringRun, MCPIntentTopic

logger = structlog.get_logger(__name__)

Status = MCPIntentClusteringRun.Status
Kind = MCPIntentClusteringRun.Kind


def _query_tags(team: Team):  # noqa: ANN202
    """Every ClickHouse read and write of a run carries the product tags, as the query runners do."""
    return tags_context(product=Product.MCP_ANALYTICS, feature=Feature.QUERY, team_id=team.pk, kind="temporal")


DEFAULT_SYNC_LOOKBACK = timedelta(hours=1, minutes=15)
SYNC_RESUME_OVERLAP = timedelta(minutes=15)
MAX_SYNC_CATCH_UP = timedelta(days=3)
SYNC_SLICE = timedelta(hours=1)


def sync_window_start(team: Team, *, now: datetime) -> datetime:
    """Where the next sync starts: just before this environment's last successful sync end, so missed runs are drained.

    The catch-up is bounded; a longer outage drops intents older than MAX_SYNC_CATCH_UP that never recur.
    """
    last = (
        MCPIntentClusteringRun.objects.filter(
            team=persist.project_team(team),
            kind=Kind.SYNC,
            status=Status.SUCCEEDED,
            **{f"params__{persist.SOURCE_TEAM_PARAM}": team.pk},
        )
        .exclude(window_end=None)
        .order_by("-window_end")
        .values_list("window_end", flat=True)
        .first()
    )
    if last is None:
        return now - DEFAULT_SYNC_LOOKBACK
    return max(last - SYNC_RESUME_OVERLAP, now - MAX_SYNC_CATCH_UP)


def _run_id(kind: str, now: datetime) -> str:
    # A retry of the same window must get a fresh id: (team, run_id) is unique in Postgres.
    return f"{kind}-{now.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"


@dataclass(frozen=True)
class SyncSlice:
    start: datetime
    end: datetime


def _sync_slices(window_start: datetime, window_end: datetime) -> Iterator[SyncSlice]:
    cursor = window_start
    while cursor < window_end:
        slice_end = min(cursor + SYNC_SLICE, window_end)
        yield SyncSlice(start=cursor, end=slice_end)
        cursor = slice_end


def _run_sync(team: Team, *, window_start: datetime, window_end: datetime, budget: int, page_size: int) -> RunOutcome:
    run = persist.start_run(
        team, kind=Kind.SYNC, run_id=_run_id(Kind.SYNC, window_end), window_start=window_start, window_end=window_end
    )
    try:
        embedding_sync.ensure_embedding_allowed(team)
    except IntentGenerationUnavailable as e:
        persist.finish_run(run, status=Status.SKIPPED_NO_CONSENT, error_message=str(e))
        return RunOutcome(run.run_id, Kind.SYNC, Status.SKIPPED_NO_CONSENT, error_message=str(e))
    n_intents = 0
    emitted = 0
    drained_until = window_start
    # An intent called in two slices of one run is sent once; the worker has not stored the first vector yet.
    handled: set[str] = set()
    try:
        for sync_slice in _sync_slices(window_start, window_end):
            if n_intents >= budget:
                break
            for page in corpus.iter_distinct_intent_pages(
                team, since=sync_slice.start, until=sync_slice.end, page_size=page_size
            ):
                fresh = [intent for intent in page if intent.hash not in handled]
                handled.update(intent.hash for intent in fresh)
                seen = corpus.fetch_seen_hashes(team, [intent.hash for intent in fresh], now=window_end)
                to_emit = embedding_sync.select_intents_to_emit(fresh, seen)
                emitted += embedding_sync.emit_intent_embeddings(team, to_emit, now=window_end)
                n_intents += len(fresh)
            drained_until = sync_slice.end
    except Exception as e:
        persist.finish_run(run, status=Status.FAILED, error_message=str(e)[:500])
        raise
    # The run claims only the hours it read whole, so the next run resumes where this one stopped.
    persist.finish_run(
        run,
        status=Status.SUCCEEDED,
        window_end=drained_until,
        n_intents=n_intents,
        n_embeddings_requested=emitted,
    )
    return RunOutcome(run.run_id, Kind.SYNC, Status.SUCCEEDED, n_intents=n_intents, n_embeddings_requested=emitted)


_ASSIGNMENT_COUNTS_SQL = """
SELECT count(), countIf(is_outlier = 1)
FROM posthog.mcp_intent_assignments
WHERE run_id = {run_id}
"""


def _run_assign(team: Team, *, window_start: datetime, window_end: datetime) -> RunOutcome:
    run = persist.start_run(
        team,
        kind=Kind.ASSIGN,
        run_id=_run_id(Kind.ASSIGN, window_end),
        window_start=window_start,
        window_end=window_end,
    )
    topics = persist.active_topic_vectors(team)
    pca = persist.latest_pca_basis(team)
    if not topics or pca is None:
        message = "No topics yet; run a refit first"
        persist.finish_run(run, status=Status.SKIPPED_TOO_FEW, error_message=message)
        return RunOutcome(run.run_id, Kind.ASSIGN, Status.SKIPPED_TOO_FEW, error_message=message)
    try:
        sql, params = build_assignment_insert(
            team_id=team.pk, run_id=run.run_id, window_start=window_start, window_end=window_end, topics=topics, pca=pca
        )
        sync_execute(sql, params, team_id=team.pk, workload=Workload.OFFLINE)
        response = execute_hogql_query(
            query=parse_select(_ASSIGNMENT_COUNTS_SQL, placeholders={"run_id": ast.Constant(value=run.run_id)}),
            team=team,
            workload=Workload.OFFLINE,
        )
        n_intents, n_outliers = (
            (int(response.results[0][0]), int(response.results[0][1])) if response.results else (0, 0)
        )
    except Exception as e:
        persist.finish_run(run, status=Status.FAILED, error_message=str(e)[:500])
        raise
    persist.finish_run(run, status=Status.SUCCEEDED, n_intents=n_intents, n_topics=len(topics), n_outliers=n_outliers)
    return RunOutcome(
        run.run_id, Kind.ASSIGN, Status.SUCCEEDED, n_intents=n_intents, n_topics=len(topics), n_outliers=n_outliers
    )


_FIT_SAMPLE_SQL = """
SELECT document_id, embedding, content, JSONExtractUInt(metadata, 'calls') AS calls
FROM document_embeddings
WHERE model_name = {model}
  AND product = {product}
  AND document_type = {document_type}
  AND timestamp >= {since}
  AND timestamp < {until}
ORDER BY cityHash64(concat(document_id, {salt}))
LIMIT 1 BY document_id
LIMIT {limit}
"""


@dataclass(frozen=True)
class FitSample:
    hashes: list[str]
    vectors: np.ndarray
    weights: np.ndarray
    texts: list[str]


def fetch_fit_sample(team: Team, *, since: datetime, until: datetime, limit: int = FIT_SAMPLE_SIZE) -> FitSample:
    """A deterministic random sample of the window's embedded intents, with call counts as weights."""
    query = parse_select(
        _FIT_SAMPLE_SQL,
        placeholders={
            "model": ast.Constant(value=EMBEDDING_MODEL),
            "product": ast.Constant(value=EMBEDDING_PRODUCT),
            "document_type": ast.Constant(value=EMBEDDING_DOCUMENT_TYPE),
            "since": ast.Constant(value=since),
            "until": ast.Constant(value=until),
            "salt": ast.Constant(value=until.strftime("%Y%m%d")),
            "limit": ast.Constant(value=limit),
        },
    )
    rows = execute_hogql_query(query=query, team=team, workload=Workload.OFFLINE).results
    if not rows:
        return FitSample(hashes=[], vectors=np.zeros((0, 0), dtype=np.float32), weights=np.zeros(0), texts=[])
    return FitSample(
        hashes=[row[0] for row in rows],
        vectors=np.asarray([row[1] for row in rows], dtype=np.float32),
        weights=np.asarray([max(int(row[3] or 0), 1) for row in rows], dtype=np.float32),
        texts=[row[2] for row in rows],
    )


def _sample_texts_by_cluster(
    fit: clustering.FitOutput, sample: FitSample, per_cluster: int = labeling.MAX_SAMPLES_PER_TOPIC
) -> dict[int, list[str]]:
    texts: dict[int, list[str]] = {}
    order = np.argsort(-sample.weights)
    for idx in order:
        cluster_idx = int(fit.labels[idx])
        if cluster_idx < 0:
            continue
        bucket = texts.setdefault(cluster_idx, [])
        if len(bucket) < per_cluster:
            bucket.append(sample.texts[idx])
    return texts


def _run_refit(
    team: Team, *, now: datetime, lookback_days: int = FIT_LOOKBACK_DAYS, sample_size: int = FIT_SAMPLE_SIZE
) -> RunOutcome:
    window_start = now - timedelta(days=lookback_days)
    run = persist.start_run(
        team, kind=Kind.REFIT, run_id=_run_id(Kind.REFIT, now), window_start=window_start, window_end=now
    )
    try:
        embedding_sync.ensure_embedding_allowed(team)
    except IntentGenerationUnavailable as e:
        persist.finish_run(run, status=Status.SKIPPED_NO_CONSENT, error_message=str(e))
        return RunOutcome(run.run_id, Kind.REFIT, Status.SKIPPED_NO_CONSENT, error_message=str(e))
    try:
        sample = fetch_fit_sample(team, since=window_start, until=now, limit=sample_size)
        if len(sample.hashes) < MIN_INTENTS_FOR_FIT:
            message = f"Only {len(sample.hashes)} embedded intents in the window; need {MIN_INTENTS_FOR_FIT}"
            persist.finish_run(run, status=Status.SKIPPED_TOO_FEW, error_message=message, n_intents=len(sample.hashes))
            return RunOutcome(
                run.run_id, Kind.REFIT, Status.SKIPPED_TOO_FEW, n_intents=len(sample.hashes), error_message=message
            )

        fit = clustering.fit_topics(sample.vectors, sample.weights)
        cluster_sizes = [int(np.sum(fit.labels == idx)) for idx in range(len(fit.centroids))]
        match = match_clusters_to_topics(fit.centroids, cluster_sizes, persist.existing_topics(team))
        persisted = persist.apply_fit(team, run=run, fit=fit, match=match, now=now)

        texts_by_cluster = _sample_texts_by_cluster(fit, sample)
        labels_by_id = {str(t.pk): t.label for t in MCPIntentTopic.active.filter(team=persist.project_team(team))}
        candidates = [
            labeling.TopicLabelInput(
                topic_id=topic_id,
                existing_label="" if topic_id in persisted.created else labels_by_id.get(topic_id, ""),
                sample_intents=texts_by_cluster.get(cluster_idx, []),
            )
            for cluster_idx, topic_id in persisted.topic_ids_by_cluster.items()
        ]
        try:
            persist.update_topic_labels(team, labeling.label_topics(team, candidates))
        except IntentGenerationUnavailable:
            logger.warning("mcp_analytics.intent_topics.labeling_unavailable", team_id=team.pk, run_id=run.run_id)
        n_outliers = int(np.sum(fit.labels < 0))
    except Exception as e:
        persist.finish_run(run, status=Status.FAILED, error_message=str(e)[:500])
        raise
    persist.finish_run(
        run,
        status=Status.SUCCEEDED,
        n_intents=len(sample.hashes),
        n_topics=len(persisted.topic_ids_by_cluster),
        n_outliers=n_outliers,
    )
    logger.info(
        "mcp_analytics.intent_topics.refit_done",
        team_id=team.pk,
        run_id=run.run_id,
        topics=len(persisted.topic_ids_by_cluster),
        created=len(persisted.created),
        archived=len(persisted.archived),
    )
    return RunOutcome(
        run.run_id,
        Kind.REFIT,
        Status.SUCCEEDED,
        n_intents=len(sample.hashes),
        n_topics=len(persisted.topic_ids_by_cluster),
        n_outliers=n_outliers,
    )


def run_sync(
    team: Team,
    *,
    window_start: datetime,
    window_end: datetime,
    budget: int = MAX_INTENTS_PER_SYNC,
    page_size: int = MAX_SELECT_RETURNED_ROWS,
) -> RunOutcome:
    with team_scope(team.pk), _query_tags(team):
        return _run_sync(team, window_start=window_start, window_end=window_end, budget=budget, page_size=page_size)


def run_assign(team: Team, *, window_start: datetime, window_end: datetime) -> RunOutcome:
    with team_scope(team.pk), _query_tags(team):
        return _run_assign(team, window_start=window_start, window_end=window_end)


def run_refit(
    team: Team, *, now: datetime, lookback_days: int = FIT_LOOKBACK_DAYS, sample_size: int = FIT_SAMPLE_SIZE
) -> RunOutcome:
    with team_scope(team.pk), _query_tags(team):
        return _run_refit(team, now=now, lookback_days=lookback_days, sample_size=sample_size)
