import datetime as dt
from typing import Any

from django.utils.timezone import now

from temporalio import activity

from products.exports.backend.models.exported_asset import ExportedAsset
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.types import EnsureSessionAssetInputs, EnsureSessionAssetOutput

# `mouse_tail=False` for cleaner LLM input.
_EXPORT_FORMAT = "video/mp4"
_PLAYBACK_SPEED = 8
# Clips are already short, so play them slow enough for the model to see the interaction, and keep
# inactivity: a moment inside an idle gap must not collapse into a near-empty sped-up blip.
_MOMENT_PLAYBACK_SPEED = 2
_RECORDING_FPS = 3
_SHOW_METADATA_FOOTER = True
_MOUSE_TAIL = False
_ASSET_EXPIRES_AFTER_DAYS = 90


def _export_context(inputs: EnsureSessionAssetInputs) -> dict[str, Any]:
    is_moment = inputs.window_start_s is not None
    context: dict[str, Any] = {
        "session_recording_id": inputs.session_id,
        "playback_speed": _MOMENT_PLAYBACK_SPEED if is_moment else _PLAYBACK_SPEED,
        "recording_fps": _RECORDING_FPS,
        "show_metadata_footer": _SHOW_METADATA_FOOTER,
        "mouse_tail": _MOUSE_TAIL,
    }
    if is_moment:
        context["start_offset_s"] = inputs.window_start_s
        context["end_offset_s"] = inputs.window_end_s
        context["skip_inactivity"] = False
    return context


@activity.defn
@track_activity()
async def ensure_session_asset_activity(inputs: EnsureSessionAssetInputs) -> EnsureSessionAssetOutput:
    """Get-or-create the `is_system=True` MP4 ExportedAsset for `(team, session[, window])`; concurrent runs may produce orphaned duplicates that the asset expiry cleans up."""
    context = _export_context(inputs)
    # Every context key is part of the identity, so a clip lookup can't adopt a whole-recording
    # asset (or another window's clip) and vice versa.
    existing = (
        await ExportedAsset.objects.filter(
            team_id=inputs.team_id,
            export_format=_EXPORT_FORMAT,
            is_system=True,
            **{f"export_context__{key}": value for key, value in context.items()},
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
        export_context=context,
        created_at=created_at,
        expires_after=created_at + dt.timedelta(days=_ASSET_EXPIRES_AFTER_DAYS),
        is_system=True,
    )
    return EnsureSessionAssetOutput(asset_id=asset.id)
