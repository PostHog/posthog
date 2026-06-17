import hashlib
from collections.abc import Callable
from datetime import datetime, timedelta

from django.db import IntegrityError
from django.db.models import Q
from django.utils import timezone

import structlog
from posthoganalytics import capture_exception

from posthog.models import Team

from products.error_tracking.backend.logic.recommendations import RECOMMENDATIONS
from products.error_tracking.backend.logic.recommendations.base import Recommendation
from products.error_tracking.backend.models import ErrorTrackingRecommendation
from products.error_tracking.backend.tasks import compute_error_tracking_recommendation

logger = structlog.get_logger(__name__)

# How long a recommendation can stay in "computing" before we consider the worker
# to have died and re-kick the computation.
COMPUTING_STUCK_AFTER = timedelta(minutes=5)


def _refresh_window(ts: datetime, phase_seconds: float, interval_seconds: float) -> int:
    return int((ts.timestamp() - phase_seconds) // interval_seconds)


def _stable_phase_seconds(team_id: int, rec_type: str, interval_seconds: float) -> float:
    digest = hashlib.sha256(f"{team_id}:{rec_type}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % int(interval_seconds)


def is_stale(rec: Recommendation, obj: ErrorTrackingRecommendation, now: datetime) -> bool:
    if obj.computed_at is None:
        return True
    if rec.refresh_interval is None:
        return True
    interval_seconds = rec.refresh_interval.total_seconds()
    phase_seconds = _stable_phase_seconds(obj.team_id, rec.type, interval_seconds)
    return _refresh_window(now, phase_seconds, interval_seconds) > _refresh_window(
        obj.computed_at, phase_seconds, interval_seconds
    )


def ensure_recommendation_row(rec: Recommendation, team_id: int) -> ErrorTrackingRecommendation:
    try:
        return ErrorTrackingRecommendation.objects.get(team_id=team_id, type=rec.type)
    except ErrorTrackingRecommendation.DoesNotExist:
        try:
            return ErrorTrackingRecommendation.objects.create(
                team_id=team_id,
                type=rec.type,
                status=ErrorTrackingRecommendation.Status.READY,
            )
        except IntegrityError:
            return ErrorTrackingRecommendation.objects.get(team_id=team_id, type=rec.type)


def claim_for_compute(obj_id, team_id: int, now: datetime) -> bool:
    """Atomically transition this recommendation into the 'computing' state.

    Returns True if we claimed the row (caller should run the computation), False if
    another worker already owns it and is still within the stuck threshold.
    """
    stuck_threshold = now - COMPUTING_STUCK_AFTER
    return (
        ErrorTrackingRecommendation.objects.filter(id=obj_id, team_id=team_id)
        .filter(
            Q(status=ErrorTrackingRecommendation.Status.READY)
            | Q(
                status=ErrorTrackingRecommendation.Status.COMPUTING,
                status_changed_at__lt=stuck_threshold,
            )
        )
        .update(
            status=ErrorTrackingRecommendation.Status.COMPUTING,
            status_changed_at=now,
        )
        == 1
    )


def revert_to_ready(obj_id, team_id: int) -> None:
    ErrorTrackingRecommendation.objects.filter(
        id=obj_id,
        team_id=team_id,
        status=ErrorTrackingRecommendation.Status.COMPUTING,
    ).update(
        status=ErrorTrackingRecommendation.Status.READY,
        status_changed_at=timezone.now(),
    )


def _refresh_one(rec: Recommendation, team_id: int, now: datetime) -> int:
    try:
        obj = ensure_recommendation_row(rec, team_id)
        if not is_stale(rec, obj, now):
            return 0
        if not claim_for_compute(obj.id, team_id, now):
            return 0
        try:
            compute_error_tracking_recommendation.delay(str(obj.id), team_id)
            return 1
        except Exception:
            revert_to_ready(obj.id, team_id)
            raise
    except Exception as e:
        capture_exception(e)
        logger.warning(
            "error_tracking_recommendation_kick_failed",
            team_id=team_id,
            recommendation_type=rec.type,
            exc_info=True,
        )
        return 0


def refresh_team_recommendations(team_id: int) -> int:
    """Dispatch a Celery compute for every stale recommendation of a team.

    Staleness is governed by each recommendation's ``refresh_interval``, so an hourly
    caller only recomputes the types that have actually gone stale (e.g. source_maps
    and long_running_issues every 6h). Used by the on-demand API path, which
    must not block on compute.

    Returns the number of recommendations kicked.
    """
    now = timezone.now()
    return sum(_refresh_one(rec, team_id, now) for rec in RECOMMENDATIONS)


def refresh_teams_recommendations_batched(
    team_ids: list[int], on_progress: Callable[[str], None] | None = None
) -> tuple[int, int]:
    """Compute every stale recommendation for a batch of teams with a bounded number
    of queries, independent of batch size.

    Bookkeeping (row creation, staleness, claiming, result writes) is bulked across
    the batch, and each recommendation answers all claimed teams via one
    ``compute_batch`` call. Used by the Temporal background sweep.

    Returns ``(teams_processed, recommendations_computed)``, where ``teams_processed``
    excludes any teams dropped for no longer existing in Postgres.
    """
    now = timezone.now()
    types = [rec.type for rec in RECOMMENDATIONS]

    # Team ids come from a ClickHouse scan of recent events, which retains events for teams
    # that have since been deleted from Postgres. Writing a recommendation row for such a team
    # violates the team_id foreign key and (since it's a single INSERT) fails the whole batch,
    # so drop the deleted teams before any writes.
    existing_team_ids = list(Team.objects.filter(id__in=team_ids).values_list("id", flat=True))
    if len(existing_team_ids) != len(team_ids):
        logger.info(
            "error_tracking_recommendation_skipped_deleted_teams",
            skipped=len(team_ids) - len(existing_team_ids),
        )
    team_ids = existing_team_ids
    if not team_ids:
        return 0, 0

    def fetch_rows() -> dict[tuple[int, str], ErrorTrackingRecommendation]:
        return {
            (obj.team_id, obj.type): obj
            for obj in ErrorTrackingRecommendation.objects.filter(team_id__in=team_ids, type__in=types)
        }

    rows = fetch_rows()
    missing = [
        ErrorTrackingRecommendation(team_id=team_id, type=rec.type, status=ErrorTrackingRecommendation.Status.READY)
        for rec in RECOMMENDATIONS
        for team_id in team_ids
        if (team_id, rec.type) not in rows
    ]
    if missing:
        # ignore_conflicts means concurrently-created rows don't error, but it also
        # means we can't trust the in-memory ids — refetch instead.
        ErrorTrackingRecommendation.objects.bulk_create(missing, ignore_conflicts=True)
        rows = fetch_rows()

    computed = 0
    for rec in RECOMMENDATIONS:
        computed += _refresh_rec_for_teams(rec, team_ids, rows, now)
        if on_progress is not None:
            on_progress(rec.type)
    return len(team_ids), computed


def _refresh_rec_for_teams(
    rec: Recommendation,
    team_ids: list[int],
    rows: dict[tuple[int, str], ErrorTrackingRecommendation],
    now: datetime,
) -> int:
    stale_ids = [
        obj.id for team_id in team_ids if (obj := rows.get((team_id, rec.type))) is not None and is_stale(rec, obj, now)
    ]
    if not stale_ids:
        return 0

    claim_ts = timezone.now()
    stuck_threshold = claim_ts - COMPUTING_STUCK_AFTER
    # nosemgrep: idor-lookup-without-team (team_id__in scopes the update; background sweep, not user input)
    ErrorTrackingRecommendation.objects.filter(team_id__in=team_ids, id__in=stale_ids).filter(
        Q(status=ErrorTrackingRecommendation.Status.READY)
        | Q(status=ErrorTrackingRecommendation.Status.COMPUTING, status_changed_at__lt=stuck_threshold)
    ).update(status=ErrorTrackingRecommendation.Status.COMPUTING, status_changed_at=claim_ts)
    # claim_ts doubles as a claim marker: only rows this exact UPDATE transitioned
    # carry it, so rows owned by a concurrent worker (e.g. the on-demand API path)
    # are excluded here.
    claimed = dict(
        # nosemgrep: idor-lookup-without-team (team_id__in scopes the lookup; background sweep, not user input)
        ErrorTrackingRecommendation.objects.filter(
            team_id__in=team_ids,
            id__in=stale_ids,
            status=ErrorTrackingRecommendation.Status.COMPUTING,
            status_changed_at=claim_ts,
        ).values_list("id", "team_id")
    )
    if not claimed:
        return 0

    try:
        metas = rec.compute_batch(sorted(claimed.values()))
    except Exception as e:
        capture_exception(e)
        logger.warning(
            "error_tracking_recommendation_batch_compute_failed",
            recommendation_type=rec.type,
            team_count=len(claimed),
            exc_info=True,
        )
        _bulk_revert_to_ready(list(claimed))
        return 0

    computed_at = timezone.now()
    to_update = []
    to_revert = []
    for obj_id, team_id in claimed.items():
        meta = metas.get(team_id)
        if meta is None:
            to_revert.append(obj_id)
            continue
        to_update.append(
            ErrorTrackingRecommendation(
                id=obj_id,
                meta=meta,
                computed_at=computed_at,
                status=ErrorTrackingRecommendation.Status.READY,
                status_changed_at=computed_at,
            )
        )
    if to_update:
        ErrorTrackingRecommendation.objects.bulk_update(
            to_update, ["meta", "computed_at", "status", "status_changed_at"]
        )
    if to_revert:
        _bulk_revert_to_ready(to_revert)
    return len(to_update)


def _bulk_revert_to_ready(obj_ids: list) -> None:
    # nosemgrep: idor-lookup-without-team (ids come from a prior team-scoped query)
    ErrorTrackingRecommendation.objects.filter(
        id__in=obj_ids,
        status=ErrorTrackingRecommendation.Status.COMPUTING,
    ).update(
        status=ErrorTrackingRecommendation.Status.READY,
        status_changed_at=timezone.now(),
    )
