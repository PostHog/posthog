"""Experiment reads over session recordings: the experiments a recording saw, the recordings of an experiment that
match a bucket, and the recordings worth watching.

Each read takes the viewer, because its queries apply the viewer's property access rules. The caller decides which
single recordings the viewer may open, and passes them to `finalize_session_bucket` and `finalize_watch_cards`.
"""

from posthog.models.team.team import Team
from posthog.models.user import User

from products.experiments.backend import session_buckets, session_context, session_event_deltas
from products.experiments.backend.facade.contracts import (
    ExperimentSessionBucket,
    ExperimentWatchResult,
    ListAccess,
    SessionBucketScan,
    SessionExperiment,
    SessionMetricHit,
    SessionMetricSourceHit,
)
from products.experiments.backend.logic.list_access import visible_experiments
from products.experiments.backend.metric_events import MetricHit
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.session_buckets import finalize_session_bucket
from products.experiments.backend.session_event_deltas import all_card_session_ids, finalize_watch_cards

__all__ = [
    "all_card_session_ids",
    "finalize_session_bucket",
    "finalize_watch_cards",
    "get_experiment_session_bucket",
    "get_experiment_session_event_deltas",
    "get_session_experiment_context",
    "get_session_experiment_contexts",
]


def _to_metric_hit(hit: MetricHit) -> SessionMetricHit:
    return SessionMetricHit(
        metric_uuid=hit.metric_uuid,
        metric_name=hit.metric_name,
        event_count=hit.event_count,
        first_timestamp=hit.first_timestamp,
        timestamps=hit.timestamps,
        sources=tuple(
            SessionMetricSourceHit(
                role=source.role,
                name=source.name,
                index=source.index,
                total=source.total,
                event_count=source.event_count,
                first_timestamp=source.first_timestamp,
                timestamps=source.timestamps,
            )
            for source in hit.sources
        ),
    )


def _to_session_experiments(items: list[session_context.ExperimentSessionContextItem]) -> tuple[SessionExperiment, ...]:
    return tuple(
        SessionExperiment(
            experiment_id=item.experiment_id,
            experiment_name=item.experiment_name,
            flag_key=item.flag_key,
            variant=item.variant,
            variants_seen=tuple(item.variants_seen),
            multiple_variants=item.multiple_variants,
            first_exposure_timestamp=item.first_exposure_timestamp,
            experiment_start_date=item.experiment_start_date,
            experiment_end_date=item.experiment_end_date,
            metrics_in_session=tuple(_to_metric_hit(hit) for hit in item.metrics_in_session),
        )
        for item in items
    )


def _experiment(project_id: int, experiment_id: int) -> Experiment | None:
    # Scoped by project, as the experiments API scopes it. `RootTeamQuerySet` resolves a `team_id=` filter to one
    # team, the parent team or the team itself, so it misses an experiment stored on another team of the project.
    return (
        Experiment.live_objects.filter(team__project_id=project_id, pk=experiment_id)
        .select_related("feature_flag")
        .first()
    )


def get_session_experiment_context(
    *, team: Team, user: User, session_id: str, experiment_access: ListAccess | None
) -> tuple[SessionExperiment, ...] | None:
    """The experiments the session saw, among those `experiment_access` lets the viewer see. None when the recording
    doesn't exist for this team. See `session_context.get_session_experiment_context`."""
    items = session_context.get_session_experiment_context(
        team, session_id, visible_experiments(team.pk, experiment_access), user
    )
    return None if items is None else _to_session_experiments(items)


def get_session_experiment_contexts(
    *, team: Team, user: User, session_ids: list[str], experiment_access: ListAccess | None
) -> dict[str, tuple[SessionExperiment, ...]]:
    """The batch form of `get_session_experiment_context`: session id to experiments, in input order. Sessions it
    can't answer for are left out. See `session_context.get_session_experiment_contexts`."""
    contexts = session_context.get_session_experiment_contexts(
        team, session_ids, visible_experiments(team.pk, experiment_access), user
    )
    return {session_id: _to_session_experiments(items) for session_id, items in contexts.items()}


def get_experiment_session_bucket(
    *,
    team: Team,
    user: User,
    experiment_id: int,
    bucket: ExperimentSessionBucket,
    metric_uuids: list[str],
    variant: str | None,
    limit: int,
) -> SessionBucketScan | None:
    """The experiment's exposed sessions that match `bucket`, most recent first, for `finalize_session_bucket`. None
    when the project has no live experiment with this id.

    Raises SessionBucketUnavailable when the bucket can't be computed for the experiment. See
    `session_buckets.get_experiment_session_bucket`.
    """
    experiment = _experiment(team.project_id, experiment_id)
    if experiment is None:
        return None
    return session_buckets.get_experiment_session_bucket(
        team, user, experiment, bucket=bucket, metric_uuids=metric_uuids, variant=variant, limit=limit
    )


def get_experiment_session_event_deltas(*, team: Team, user: User, experiment_id: int) -> ExperimentWatchResult | None:
    """The recordings worth watching for the experiment, grouped into cards, for `finalize_watch_cards`. None when
    the project has no live experiment with this id.

    Raises SessionEventDeltasUnavailable when nothing can be compared. See
    `session_event_deltas.get_experiment_session_event_deltas`.
    """
    experiment = _experiment(team.project_id, experiment_id)
    if experiment is None:
        return None
    return session_event_deltas.get_experiment_session_event_deltas(team, user, experiment)
