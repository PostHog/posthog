from typing import TYPE_CHECKING

from products.exports.backend.models.exported_asset import ExportedAsset

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl


def get_export_renderer_asset_context(
    *, asset_id: int, team_id: int, created_by_id: int, scope: str
) -> dict[str, object] | None:
    asset = (
        ExportedAsset.objects.only("export_context")
        .filter(id=asset_id, team_id=team_id, created_by_id=created_by_id)
        .first()
    )
    if asset is None:
        return None

    export_context = asset.export_context or {}
    if scope == "heatmap:read":
        return export_context if export_context.get("heatmap_url") else None
    if scope == "session_recording:read":
        return export_context if export_context.get("session_recording_id") else None
    return None


def can_user_view_exported_asset(
    asset: ExportedAsset, *, user_id: int | None, user_access_control: "UserAccessControl"
) -> bool:
    """Whether a user may read an asset's content. Product exports are not covered: their owner authorizes them."""
    export_context = asset.export_context or {}

    if not asset.is_session_recording_export and asset.created_by_id != user_id:
        return False

    if export_context.get("observation_id"):
        # Media a product owns and authorizes on its own endpoint. This endpoint checks the recording,
        # which is a weaker gate than the one the owner applies, and asset ids are guessable integers.
        return False

    # Both can be set on one asset, and the renderer prefers the insight, so checking only the
    # first non-null one would let an accessible dashboard authorize an inaccessible insight.
    for related in (asset.dashboard, asset.insight):
        if related is not None and not user_access_control.check_access_level_for_object(
            related, required_level="viewer"
        ):
            return False

    session_recording_id = export_context.get("session_recording_id")
    if not session_recording_id:
        return True

    # Reached even when a dashboard or insight authorized above: an asset carrying both renders
    # the recording too, so a viewable dashboard must not stand in for access to it.
    from posthog.session_recordings.models.session_recording import SessionRecording

    recording = SessionRecording.objects.filter(team_id=asset.team_id, session_id=session_recording_id).first()
    if recording is not None:
        return user_access_control.check_access_level_for_object(recording, required_level="viewer")
    if asset.created_by_id != user_id:
        # No SessionRecording row — cannot run object-level RBAC; still enforce the team's
        # session_recording resource default for other users so detail/content are not fail-open.
        # The creator is exempt from this fallback only, because _assert_may_export_session_recording
        # ran the same check when they created the export, so retrieval must not be stricter than
        # creation — otherwise a session_recording default below viewer 404s the very user who just
        # took the screenshot, surfacing as an "Export complete!" toast followed by a blank error
        # page. Explicit object-level denies (the branch above) still apply to the creator once a
        # SessionRecording row exists.
        return user_access_control.check_access_level_for_resource("session_recording", required_level="viewer")
    return True
