from uuid import UUID

from django.db.models import Exists, OuterRef
from django.db.models.fields.json import KeyTextTransform
from django.utils.timezone import now

import structlog
from asgiref.sync import sync_to_async
from temporalio import activity

from products.exports.backend.models.exported_asset import ExportedAsset
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.replay_observation_media import ReplayObservationMedia
from products.replay_vision.backend.temporal.activities.ensure_session_asset import analysis_export_context
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.media_backfill.constants import (
    ATTEMPT_COOLDOWN,
    CANDIDATE_SCAN_LIMIT,
    MAX_OBSERVATION_AGE,
    MAX_OBSERVATIONS_PER_TICK,
    MAX_RENDER_ATTEMPTS,
    MIN_OBSERVATION_AGE,
)
from products.replay_vision.backend.temporal.media_backfill.types import (
    FindMediaBackfillCandidatesOutput,
    MediaBackfillCandidate,
    MediaBackfillInputs,
)
from products.replay_vision.backend.temporal.metrics import record_media_backfill_tick

logger = structlog.get_logger(__name__)


def _analysis_asset_ids(rows: list[tuple[UUID, int, str]]) -> dict[tuple[int, str], int]:
    """The usable analysis video per (team, session), in one query for the whole page."""
    if not rows:
        return {}
    # The render settings come from the activity that writes these assets, so a change there cannot
    # leave the sweep matching videos the scan would not read back.
    settings = analysis_export_context("")
    discriminators = {
        f"export_context__{key}": value for key, value in settings.items() if key != "session_recording_id"
    }
    found = (
        ExportedAsset.objects.filter(
            export_format=ExportedAsset.ExportFormat.MP4,
            is_system=True,
            team_id__in={team_id for _, team_id, _ in rows},
            **discriminators,
        )
        .annotate(session=KeyTextTransform("session_recording_id", "export_context"))
        .filter(session__in={session_id for _, _, session_id in rows})
        .exclude(content_location=None)
        .exclude(content_location="")
        .order_by("id")
        .values_list("team_id", "session", "id")
    )
    by_session: dict[tuple[int, str], int] = {}
    for team_id, session_id, asset_id in found:
        by_session.setdefault((team_id, session_id), asset_id)
    return by_session


def _find(limit: int) -> FindMediaBackfillCandidatesOutput:
    # A sweep is genuinely cross-team and has no request to take a team from, so the media model's
    # fail-closed manager needs its escape hatch. ReplayObservation is not team-scoped.
    has_media = ReplayObservationMedia.objects.unscoped().filter(observation_id=OuterRef("pk"))
    rows = list(
        ReplayObservation.objects.filter(
            status=ObservationStatus.SUCCEEDED,
            created_at__lt=now() - MIN_OBSERVATION_AGE,
            created_at__gt=now() - MAX_OBSERVATION_AGE,
        )
        .annotate(has_media=Exists(has_media))
        .filter(has_media=False)
        .exclude(media_render_attempts__gte=MAX_RENDER_ATTEMPTS)
        .exclude(media_render_attempted_at__gt=now() - ATTEMPT_COOLDOWN)
        .order_by("-created_at")
        .values_list("id", "team_id", "session_id")[:CANDIDATE_SCAN_LIMIT]
    )
    # Counted separately so a stalled sweep shows why it is finding nothing.
    cooling_off = (
        ReplayObservation.objects.filter(
            status=ObservationStatus.SUCCEEDED,
            media_render_attempted_at__gt=now() - ATTEMPT_COOLDOWN,
            media_render_attempts__lt=MAX_RENDER_ATTEMPTS,
        )
        .annotate(has_media=Exists(has_media))
        .filter(has_media=False)
        .count()
    )

    assets = _analysis_asset_ids(rows)

    candidates: list[MediaBackfillCandidate] = []
    without_video = 0
    for observation_id, team_id, session_id in rows:
        asset_id = assets.get((team_id, session_id))
        if asset_id is None:
            # The video outlives the observation by about 30 days, so the oldest gaps stay unfillable.
            without_video += 1
            continue
        candidates.append(
            MediaBackfillCandidate(
                team_id=team_id, observation_id=observation_id, session_id=session_id, analysis_asset_id=asset_id
            )
        )
        if len(candidates) >= limit:
            break

    return FindMediaBackfillCandidatesOutput(
        candidates=candidates, without_video=without_video, cooling_off=cooling_off
    )


@activity.defn
@track_activity()
async def find_media_backfill_candidates_activity(
    inputs: MediaBackfillInputs,
) -> FindMediaBackfillCandidatesOutput:
    """Succeeded observations with no media whose analysis video is still stored, newest first."""
    limit = max(1, inputs.limit or MAX_OBSERVATIONS_PER_TICK)
    result = await sync_to_async(_find)(limit)
    record_media_backfill_tick(
        dispatched=len(result.candidates), without_video=result.without_video, cooling_off=result.cooling_off
    )
    logger.info(
        "replay_vision.media_backfill.candidates",
        found=len(result.candidates),
        without_video=result.without_video,
        cooling_off=result.cooling_off,
    )
    return result
