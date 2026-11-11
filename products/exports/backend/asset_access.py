from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, cast

from django.db.models import Model

from products.exports.backend.models.exported_asset import ExportedAsset

if TYPE_CHECKING:
    from posthog.session_recordings.models.session_recording import SessionRecording

    from products.access_control.backend.facade.user_access_control import UserAccessControl


def can_user_view_exported_asset(
    asset: ExportedAsset,
    *,
    user_id: int | None,
    user_access_control: "UserAccessControl",
    recordings: Mapping[tuple[int, str], "SessionRecording"] | None = None,
) -> bool:
    """Whether a user may read an asset's content. Product exports are not covered: their owner authorizes them.

    `recordings` maps (team_id, session_id) to the SessionRecording rows already loaded by the caller. When it is
    given, a session id missing from it means no row exists, and no query is made.
    """
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
    if recordings is not None:
        recording = recordings.get((asset.team_id, session_recording_id))
    else:
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


def viewable_assets(
    assets: Iterable[ExportedAsset], *, user_id: int | None, user_access_control: "UserAccessControl"
) -> set[int]:
    """Ids of the assets a user may read, under the rules of can_user_view_exported_asset.

    Use this instead of calling can_user_view_exported_asset in a loop: it loads the session recordings and their
    access controls once for all assets, so the cost does not grow with the number of assets. Product exports are
    never included, because their owning product authorizes them on its own endpoints.
    """
    from posthog.session_recordings.models.session_recording import SessionRecording

    from products.exports.backend.facade.exporters import is_product_export

    candidates = [
        asset for asset in assets if not is_product_export(export_format=asset.export_format, kind=asset.export_kind)
    ]

    wanted: set[tuple[int, str]] = set()
    for asset in candidates:
        session_id = (asset.export_context or {}).get("session_recording_id")
        if session_id:
            wanted.add((asset.team_id, session_id))

    recordings: dict[tuple[int, str], SessionRecording] = {}
    if wanted:
        rows = list(
            SessionRecording.objects.filter(
                team_id__in={team_id for team_id, _ in wanted},
                session_id__in={session_id for _, session_id in wanted},
            )
        )
        user_access_control.preload_object_access_controls(cast(list[Model], rows))
        recordings = {(row.team_id, row.session_id): row for row in rows}

    return {
        asset.id
        for asset in candidates
        if can_user_view_exported_asset(
            asset, user_id=user_id, user_access_control=user_access_control, recordings=recordings
        )
    }
