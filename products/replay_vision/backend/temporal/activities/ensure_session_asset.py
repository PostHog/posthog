import datetime as dt

from django.utils.timezone import now

from temporalio import activity

from posthog.models.exported_asset import ExportedAsset

from products.replay_vision.backend.temporal.types import EnsureSessionAssetInputs, EnsureSessionAssetOutput

# Render params match the session-summary path so the rasterize fingerprint cache hits across products.
_EXPORT_FORMAT = "video/mp4"
_PLAYBACK_SPEED = 8
_RECORDING_FPS = 3
_SHOW_METADATA_FOOTER = True
_ASSET_EXPIRES_AFTER_DAYS = 90


@activity.defn
async def ensure_session_asset_activity(inputs: EnsureSessionAssetInputs) -> EnsureSessionAssetOutput:
    """Get-or-create the `is_system=True` MP4 ExportedAsset for `(team, session)`; concurrent runs may produce orphaned duplicates that the asset expiry cleans up."""
    existing = (
        await ExportedAsset.objects.filter(
            team_id=inputs.team_id,
            export_format=_EXPORT_FORMAT,
            export_context__session_recording_id=inputs.session_id,
            is_system=True,
        )
        .order_by("id")
        .afirst()
    )
    if existing is not None:
        return EnsureSessionAssetOutput(asset_id=existing.id)

    created_at = now()
    asset = await ExportedAsset.objects.acreate(
        team_id=inputs.team_id,
        export_format=_EXPORT_FORMAT,
        export_context={
            "session_recording_id": inputs.session_id,
            "playback_speed": _PLAYBACK_SPEED,
            "recording_fps": _RECORDING_FPS,
            "show_metadata_footer": _SHOW_METADATA_FOOTER,
        },
        created_at=created_at,
        expires_after=created_at + dt.timedelta(days=_ASSET_EXPIRES_AFTER_DAYS),
        is_system=True,
    )
    return EnsureSessionAssetOutput(asset_id=asset.id)
