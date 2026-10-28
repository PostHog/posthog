"""Cuts a thumbnail for each feed pick scanned before observations had one, from the analysis video its scan kept."""

from datetime import datetime

from django.db.models import Count, Exists, Min, OuterRef, Value

from posthog.dataclasses import frozen

from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.replay_observation_media import ReplayObservationMedia
from products.replay_vision.backend.scanner_access import scanners_for_reading_observations
from products.replay_vision.backend.temporal.activities.ensure_session_asset import analysis_assets_for_sessions
from products.replay_vision.backend.temporal.media_types import ObservationMediaInputs
from products.replay_vision.backend.watch_rank import select_embedding_picks


@frozen
class ThumbnailBackfillTargets:
    picks: int
    renders: list[ObservationMediaInputs]
    # Picks with no thumbnail whose analysis video has expired or never rendered, so no frame can be cut.
    without_video: int


def thumbnail_backfill_targets(team_id: int, since: datetime, now: datetime, cap: int) -> ThumbnailBackfillTargets:
    """The window's feed picks, as any viewer would get them, that have no thumbnail but still have their video."""
    window = ReplayObservation.objects.filter(
        team_id=team_id,
        status=ObservationStatus.SUCCEEDED,
        created_at__gte=since,
        created_at__lte=now,
        completed_at__lte=now,
    )
    scanner_ids = list(scanners_for_reading_observations(team_id).values_list("id", flat=True))
    # No viewer, so no row is dropped as viewed or as hidden behind an experiment.
    picks = select_embedding_picks(window, scanner_ids, Value(False), None, team_id, cap)
    missing = list(
        ReplayObservation.objects.filter(team_id=team_id, id__in=[row["id"] for row in picks])
        .alias(
            has_thumbnail=Exists(
                ReplayObservationMedia.objects.for_team(team_id).filter(
                    observation_id=OuterRef("id"), kind=ReplayObservationMedia.Kind.THUMBNAIL
                )
            )
        )
        .filter(has_thumbnail=False)
        .values_list("id", "session_id")
    )
    videos = _analysis_video_ids(team_id, [session_id for _, session_id in missing])
    renders = [
        ObservationMediaInputs(
            team_id=team_id, observation_id=observation_id, session_id=session_id, analysis_asset_id=videos[session_id]
        )
        for observation_id, session_id in missing
        if session_id in videos
    ]
    return ThumbnailBackfillTargets(picks=len(picks), renders=renders, without_video=len(missing) - len(renders))


def _analysis_video_ids(team_id: int, session_ids: list[str]) -> dict[str, int]:
    """Each session's first analysis video that still has its object, as the scan's own lookup picks it."""
    videos: dict[str, int] = {}
    # The default manager hides expired assets, so every id here still has its object.
    for asset_id, session_id in (
        analysis_assets_for_sessions(team_id, session_ids)
        .exclude(content_location__isnull=True)
        .exclude(content_location="")
        .order_by("-id")
        .values_list("id", "export_context__session_recording_id")
    ):
        videos[session_id] = asset_id
    return videos


def teams_scanned_before_thumbnails(since: datetime) -> list[int]:
    """Teams with observations in the window from before the first thumbnail was cut, busiest first."""
    first_thumbnail = (
        ReplayObservationMedia.objects.unscoped()
        .filter(kind=ReplayObservationMedia.Kind.THUMBNAIL)
        .aggregate(first=Min("created_at"))["first"]
    )
    observations = ReplayObservation.objects.filter(status=ObservationStatus.SUCCEEDED, created_at__gte=since)
    if first_thumbnail is not None:
        observations = observations.filter(created_at__lt=first_thumbnail)
    return list(observations.values("team_id").annotate(n=Count("id")).order_by("-n").values_list("team_id", flat=True))
