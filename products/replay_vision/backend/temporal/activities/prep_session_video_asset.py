from datetime import timedelta

from django.db import transaction
from django.utils.timezone import now

import structlog
import temporalio
from temporalio.exceptions import ApplicationError

from posthog.models import Team
from posthog.models.exported_asset import ExportedAsset
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.sync import database_sync_to_async

from products.replay_vision.backend.temporal.constants import (
    EXPORTED_ASSET_EXPIRES_AFTER_DAYS,
    FULL_VIDEO_EXPORT_FORMAT,
    MIN_SESSION_DURATION_FOR_LENS_S,
    VIDEO_PLAYBACK_SPEED,
    VIDEO_RECORDING_FPS,
)
from products.replay_vision.backend.temporal.types import ApplyLensInputs, PrepSessionVideoAssetResult

logger = structlog.get_logger(__name__)


def _refresh_asset_input_params_locked(asset_id: int, session_id: str) -> None:
    """SELECT FOR UPDATE so the JSONB write doesn't race the rasterizer's own update."""
    with transaction.atomic():
        asset = ExportedAsset.objects.select_for_update().get(id=asset_id)
        ctx = dict(asset.export_context or {})
        ctx["session_recording_id"] = session_id
        ctx["playback_speed"] = VIDEO_PLAYBACK_SPEED
        ctx["recording_fps"] = VIDEO_RECORDING_FPS
        ctx["show_metadata_footer"] = True
        if ctx != asset.export_context:
            asset.export_context = ctx
            asset.save(update_fields=["export_context"])


@temporalio.activity.defn
async def prep_session_video_asset_activity(inputs: ApplyLensInputs) -> PrepSessionVideoAssetResult:
    """Get-or-create the system-owned ExportedAsset for this session's rendered video.

    Asset reuse is keyed on (team_id, session_id, FULL_VIDEO_EXPORT_FORMAT, is_system=True), so multiple
    Vision lenses (and the legacy summarizer) on the same session share one render via the rasterizer cache.
    """
    team = await Team.objects.aget(id=inputs.team_id)
    metadata = await database_sync_to_async(SessionReplayEvents().get_metadata)(
        session_id=inputs.session_id,
        team=team,
    )
    if not metadata:
        raise ApplicationError(f"No metadata found for session {inputs.session_id}", non_retryable=True)
    if metadata["duration"] < MIN_SESSION_DURATION_FOR_LENS_S:
        raise ApplicationError(
            f"Session {inputs.session_id} too short ({metadata['duration']:.2f}s) to apply a lens",
            non_retryable=True,
        )

    existing_asset = await ExportedAsset.objects.filter(
        team_id=inputs.team_id,
        export_format=FULL_VIDEO_EXPORT_FORMAT,
        export_context__session_recording_id=inputs.session_id,
        is_system=True,
    ).afirst()

    if existing_asset:
        await database_sync_to_async(_refresh_asset_input_params_locked, thread_sensitive=False)(
            existing_asset.id, inputs.session_id
        )
        return PrepSessionVideoAssetResult(
            asset_id=existing_asset.id, team_api_token=team.api_token, team_name=team.name
        )

    created_at = now()
    exported_asset = await ExportedAsset.objects.acreate(
        team_id=inputs.team_id,
        export_format=FULL_VIDEO_EXPORT_FORMAT,
        export_context={
            "session_recording_id": inputs.session_id,
            "playback_speed": VIDEO_PLAYBACK_SPEED,
            "recording_fps": VIDEO_RECORDING_FPS,
            "show_metadata_footer": True,
        },
        created_by_id=inputs.user_id,
        created_at=created_at,
        expires_after=created_at + timedelta(days=EXPORTED_ASSET_EXPIRES_AFTER_DAYS),
        is_system=True,
    )
    return PrepSessionVideoAssetResult(asset_id=exported_asset.id, team_api_token=team.api_token, team_name=team.name)
