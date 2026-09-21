from collections.abc import Collection

from django.db.models import QuerySet
from django.utils.timezone import now

from temporalio import activity

from products.exports.backend.models.exported_asset import ExportedAsset
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.types import EnsureSessionAssetInputs, EnsureSessionAssetOutput

# `mouse_tail=False` for cleaner LLM input.
_EXPORT_FORMAT = "video/mp4"
_PLAYBACK_SPEED = 8
_RECORDING_FPS = 3
_SHOW_METADATA_FOOTER = True
_MOUSE_TAIL = False

_RENDER_SETTINGS: dict[str, object] = {
    "playback_speed": _PLAYBACK_SPEED,
    "recording_fps": _RECORDING_FPS,
    "show_metadata_footer": _SHOW_METADATA_FOOTER,
    "mouse_tail": _MOUSE_TAIL,
}


def analysis_export_context(session_id: str) -> dict[str, object]:
    """The render settings the scan reads back off its analysis video."""
    return {"session_recording_id": session_id, **_RENDER_SETTINGS}


def _analysis_asset_filters() -> dict[str, object]:
    """What makes an MP4 the analysis video, minus which session it belongs to."""
    return {
        "export_format": _EXPORT_FORMAT,
        "is_system": True,
        **{f"export_context__{key}": value for key, value in _RENDER_SETTINGS.items()},
    }


def analysis_assets(team_id: int, session_id: str) -> "QuerySet[ExportedAsset]":
    """Every MP4 rendered for this session with the settings the scan reads back off it.

    Shared so a caller that only needs to find one cannot drift from the render parameters.
    """
    return ExportedAsset.objects.filter(
        team_id=team_id,
        export_context__session_recording_id=session_id,
        **_analysis_asset_filters(),
    )


def analysis_assets_for_sessions(team_ids: Collection[int], session_ids: Collection[str]) -> "QuerySet[ExportedAsset]":
    """The same assets for many sessions at once, so a sweep reads them in one query."""
    return ExportedAsset.objects.filter(
        team_id__in=list(team_ids),
        export_context__session_recording_id__in=list(session_ids),
        **_analysis_asset_filters(),
    )


@activity.defn
@track_activity()
async def ensure_session_asset_activity(inputs: EnsureSessionAssetInputs) -> EnsureSessionAssetOutput:
    """Get-or-create the `is_system=True` MP4 ExportedAsset for `(team, session)`; concurrent runs may produce orphaned duplicates that the asset expiry cleans up."""
    existing_id = (
        await analysis_assets(inputs.team_id, inputs.session_id).order_by("id").values_list("id", flat=True).afirst()
    )
    if existing_id is not None:
        return EnsureSessionAssetOutput(asset_id=existing_id)

    created_at = now()
    asset = await ExportedAsset.objects.acreate(
        team_id=inputs.team_id,
        export_format=_EXPORT_FORMAT,
        export_context=analysis_export_context(inputs.session_id),
        created_at=created_at,
        is_system=True,
    )
    return EnsureSessionAssetOutput(asset_id=asset.id)
