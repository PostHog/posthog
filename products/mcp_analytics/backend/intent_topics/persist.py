"""Postgres side of the pipeline: topic registry updates, PCA basis storage and run bookkeeping."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

import numpy as np

from posthog.models.team.team import Team

from products.mcp_analytics.backend.intent_topics.assignment_sql import PcaBasis, TopicVector
from products.mcp_analytics.backend.intent_topics.clustering import FitOutput, project_2d
from products.mcp_analytics.backend.intent_topics.constants import TOPIC_ARCHIVE_AFTER_DAYS
from products.mcp_analytics.backend.intent_topics.labeling import TopicLabel, fallback_label
from products.mcp_analytics.backend.intent_topics.topic_registry import ExistingTopic, MatchResult
from products.mcp_analytics.backend.models import MCPIntentClusteringRun, MCPIntentTopic

PCA_BASIS_PARAM = "pca_basis"
# Runs are stored on the project, so each run records the environment whose events it read.
SOURCE_TEAM_PARAM = "source_team_id"


@dataclass(frozen=True)
class FitPersistResult:
    topic_ids_by_cluster: dict[int, str] = field(default_factory=dict)
    created: list[str] = field(default_factory=list)
    archived: list[str] = field(default_factory=list)


def project_team(team: Team) -> Team:
    """The team that owns topics and runs: an environment shares its project's registry."""
    return team.parent_team or team


def existing_topics(team: Team) -> list[ExistingTopic]:
    team = project_team(team)
    return [
        ExistingTopic(id=str(topic.pk), centroid=topic.decoded_centroid())
        for topic in MCPIntentTopic.active.filter(team=team).order_by("first_seen_at")
    ]


def active_topic_vectors(team: Team) -> list[TopicVector]:
    team = project_team(team)
    return [
        TopicVector(
            topic_id=str(topic.pk),
            centroid=topic.decoded_centroid().astype(float).tolist(),
            outlier_distance=float(topic.outlier_distance),
        )
        for topic in MCPIntentTopic.active.filter(team=team).order_by("first_seen_at")
    ]


def start_run(
    team: Team, *, kind: str, run_id: str, window_start: datetime, window_end: datetime
) -> MCPIntentClusteringRun:
    return MCPIntentClusteringRun.objects.create(
        team=project_team(team),
        kind=kind,
        run_id=run_id,
        window_start=window_start,
        window_end=window_end,
        params={SOURCE_TEAM_PARAM: team.pk},
    )


def finish_run(
    run: MCPIntentClusteringRun,
    *,
    status: str,
    error_message: str = "",
    window_end: datetime | None = None,
    **counts: int,
) -> None:
    run.status = status
    run.error_message = error_message
    if window_end is not None:
        run.window_end = window_end
    for name, value in counts.items():
        setattr(run, name, value)
    run.finished_at = timezone.now()
    run.save()


def latest_refit_started_at(team: Team) -> datetime | None:
    return (
        MCPIntentClusteringRun.objects.filter(
            team=project_team(team),
            kind=MCPIntentClusteringRun.Kind.REFIT,
            status=MCPIntentClusteringRun.Status.SUCCEEDED,
        )
        .order_by("-started_at")
        .values_list("started_at", flat=True)
        .first()
    )


def latest_pca_basis(team: Team) -> PcaBasis | None:
    run = (
        MCPIntentClusteringRun.objects.filter(
            team=project_team(team),
            kind=MCPIntentClusteringRun.Kind.REFIT,
            status=MCPIntentClusteringRun.Status.SUCCEEDED,
        )
        .order_by("-started_at")
        .first()
    )
    if run is None or PCA_BASIS_PARAM not in run.params:
        return None
    stored = run.params[PCA_BASIS_PARAM]
    return PcaBasis(mean=stored["mean"], pc1=stored["pc1"], pc2=stored["pc2"])


@dataclass(frozen=True)
class MapPosition:
    x: float
    y: float


def _member_centroid_2d(fit: FitOutput, cluster_idx: int) -> MapPosition:
    coords = fit.coords_2d[fit.labels == cluster_idx]
    if len(coords) == 0:
        return MapPosition(x=0.0, y=0.0)
    mean = coords.mean(axis=0)
    return MapPosition(x=float(mean[0]), y=float(mean[1]))


def apply_fit(
    team: Team, *, run: MCPIntentClusteringRun, fit: FitOutput, match: MatchResult, now: datetime
) -> FitPersistResult:
    """Write a weekly fit into the registry.

    Reused clusters refresh their topic's centroid, outlier distance, 2D position and member count.
    Created clusters become topics with a neutral fallback label (``label_topics`` names them next).
    Topics no cluster matched are archived once they have been unmatched for ``TOPIC_ARCHIVE_AFTER_DAYS``.
    The PCA basis is stored on the run so the nightly assignment can project new intents.
    """
    team = project_team(team)
    # One transaction: a partial registry next to the previous basis would mislabel the nightly assignment.
    with transaction.atomic():
        topic_ids: dict[int, str] = {}
        created: list[str] = []

        for cluster_idx, topic_id in match.reused.items():
            topic = MCPIntentTopic.objects.get(team=team, pk=topic_id)
            _write_cluster(topic, fit, cluster_idx, run.run_id)
            topic.save()
            topic_ids[cluster_idx] = topic_id

        for cluster_idx in match.created:
            topic = MCPIntentTopic(team=team, label="", centroid=b"")
            _write_cluster(topic, fit, cluster_idx, run.run_id)
            topic.label = fallback_label(str(topic.pk))
            topic.save()
            topic_ids[cluster_idx] = str(topic.pk)
            created.append(str(topic.pk))

        # last_seen_at is auto_now, so save() writes the wall clock; a replayed refit must record its own time.
        MCPIntentTopic.objects.filter(team=team, pk__in=list(topic_ids.values())).update(last_seen_at=now)

        archived: list[str] = []
        cutoff = now - timedelta(days=TOPIC_ARCHIVE_AFTER_DAYS)
        for topic in MCPIntentTopic.active.filter(team=team, pk__in=match.unmatched_topics, last_seen_at__lt=cutoff):
            topic.status = MCPIntentTopic.Status.ARCHIVED
            topic.save(update_fields=["status"])
            archived.append(str(topic.pk))

        # Unmatched topics that stay active keep their centroid, but their map position must use the new basis.
        for topic in MCPIntentTopic.active.filter(team=team, pk__in=match.unmatched_topics):
            position = project_2d(topic.decoded_centroid()[None, :], fit.pca_mean, fit.pca_components)[0]
            MCPIntentTopic.objects.filter(pk=topic.pk).update(
                centroid_x=float(position[0]), centroid_y=float(position[1])
            )

        run.params = {
            **run.params,
            PCA_BASIS_PARAM: {
                "mean": fit.pca_mean.astype(float).tolist(),
                "pc1": fit.pca_components[0].astype(float).tolist(),
                "pc2": fit.pca_components[1].astype(float).tolist(),
            },
        }
        run.save(update_fields=["params"])
    return FitPersistResult(topic_ids_by_cluster=topic_ids, created=created, archived=archived)


def _write_cluster(topic: MCPIntentTopic, fit: FitOutput, cluster_idx: int, run_id: str) -> None:
    topic.centroid = MCPIntentTopic.encode_centroid(fit.centroids[cluster_idx])
    topic.outlier_distance = float(fit.outlier_distances[cluster_idx])
    position = _member_centroid_2d(fit, cluster_idx)
    topic.centroid_x, topic.centroid_y = position.x, position.y
    topic.member_count = int(np.sum(fit.labels == cluster_idx))
    topic.last_run_id = run_id


def update_topic_labels(team: Team, labels: dict[str, TopicLabel]) -> None:
    team = project_team(team)
    for topic_id, topic_label in labels.items():
        # An empty summary means the labeler gave no answer for this topic, so the stored summary stays.
        fields = {"label": topic_label.label, **({"summary": topic_label.summary} if topic_label.summary else {})}
        MCPIntentTopic.objects.filter(team=team, pk=topic_id).update(**fields)


def run_params(run: MCPIntentClusteringRun) -> dict[str, Any]:
    return dict(run.params)
