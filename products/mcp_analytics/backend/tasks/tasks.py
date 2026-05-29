"""Celery tasks for mcp_analytics.

Async entrypoints that orchestrate the intent clustering pipeline. Task
functions stay thin: they coordinate state transitions and call into the pure
clustering module.
"""

import asyncio
from typing import Any

from django.db import transaction
from django.utils import timezone

import structlog
from celery import shared_task

from posthog.models.scoping import with_team_scope

logger = structlog.get_logger(__name__)


@shared_task(
    name="products.mcp_analytics.backend.tasks.compute_intent_clusters",
    bind=True,
    ignore_result=True,
    acks_late=True,
    max_retries=2,
)
@with_team_scope()
def compute_intent_clusters(
    self: Any, team_id: int, user_id: int | None = None, lookback_days: int | None = None
) -> None:
    """Recompute the intent cluster snapshot for a team.

    Flow:
      1. Mark the snapshot as ``computing`` (creates a row on first run).
      2. Fetch the intent corpus, embed it, cluster it, build the snapshot.
      3. Persist the snapshot atomically and mark ``idle``.
      4. On failure, mark ``error`` with the message; rely on Celery retry.

    ``lookback_days`` overrides the default window used by both the Postgres
    session query and the joined ClickHouse query. ``None`` keeps the default.
    """
    # Imports inside the task so Celery autoimport doesn't pull heavy deps
    # (numpy/sklearn/httpx) at worker startup.
    from posthog.models.team.team import Team

    from products.mcp_analytics.backend import intent_clustering
    from products.mcp_analytics.backend.models import MCPIntentClusterSnapshot

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        logger.warning("mcp_analytics.intent_clusters.team_not_found", team_id=team_id)
        return

    user = None
    if user_id is not None:
        from posthog.models.user import User

        user = User.objects.filter(pk=user_id).first()

    snapshot, _ = MCPIntentClusterSnapshot.objects.update_or_create(
        team=team,
        defaults={
            "status": MCPIntentClusterSnapshot.Status.COMPUTING,
            "error_message": "",
            "last_computed_by": user,
        },
    )

    corpus_kwargs: dict[str, int] = {}
    if lookback_days is not None:
        corpus_kwargs["lookback_days"] = lookback_days

    try:
        records, intent_by_session = intent_clustering.fetch_intent_corpus(team, **corpus_kwargs)
        if not records:
            _save_empty_snapshot(snapshot)
            logger.info("mcp_analytics.intent_clusters.no_intents_found", team_id=team_id)
            return

        embeddings, valid_indices = asyncio.run(
            intent_clustering.embed_intents_async(team, [r.intent_text for r in records])
        )
        if len(valid_indices) == 0:
            raise RuntimeError("All embedding requests failed")

        aligned_records = [records[i] for i in valid_indices]
        labels = intent_clustering.cluster_embeddings(embeddings)

        # Fetch ordered tool-call sequences for every session and aggregate
        # them per cluster so the UI can render a Sankey of agent journeys.
        session_journeys = intent_clustering.fetch_session_journeys(
            team, list(intent_by_session.keys()), **corpus_kwargs
        )
        intent_to_sessions: dict[str, list[str]] = {}
        for sid, intent_text in intent_by_session.items():
            intent_to_sessions.setdefault(intent_text, []).append(sid)
        journeys_by_cluster = intent_clustering.aggregate_journeys_per_cluster(
            aligned_records, labels, session_journeys, intent_to_sessions
        )

        clusters_blob = intent_clustering.build_snapshot(
            aligned_records, labels, embeddings, journeys_by_cluster=journeys_by_cluster
        )

        with transaction.atomic():
            snapshot.clusters = clusters_blob
            snapshot.status = MCPIntentClusterSnapshot.Status.IDLE
            snapshot.error_message = ""
            snapshot.last_computed_at = timezone.now()
            snapshot.save(update_fields=["clusters", "status", "error_message", "last_computed_at", "updated_at"])

        logger.info(
            "mcp_analytics.intent_clusters.computed",
            team_id=team_id,
            n_intents=len(aligned_records),
            n_clusters=len(clusters_blob.get("clusters", [])),
        )

    except Exception as exc:
        logger.exception("mcp_analytics.intent_clusters.failed", team_id=team_id, error=str(exc))
        snapshot.status = MCPIntentClusterSnapshot.Status.ERROR
        snapshot.error_message = str(exc)[:5000]
        snapshot.save(update_fields=["status", "error_message", "updated_at"])
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=60)
        raise


def _save_empty_snapshot(snapshot: Any) -> None:
    # Importing the module avoids a circular import at worker startup.
    from products.mcp_analytics.backend.intent_clustering import DEFAULT_DISTANCE_THRESHOLD, EMBEDDING_MODEL
    from products.mcp_analytics.backend.models import MCPIntentClusterSnapshot

    snapshot.clusters = {
        "clusters": [],
        "computed_with": {
            "distance_threshold": DEFAULT_DISTANCE_THRESHOLD,
            "embedding_model": EMBEDDING_MODEL,
            "n_intents": 0,
            "n_clusters": 0,
        },
    }
    snapshot.status = MCPIntentClusterSnapshot.Status.IDLE
    snapshot.error_message = ""
    snapshot.last_computed_at = timezone.now()
    snapshot.save(update_fields=["clusters", "status", "error_message", "last_computed_at", "updated_at"])
