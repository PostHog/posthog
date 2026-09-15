from posthog.models import Team, User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.exports.backend.models.exported_asset import ExportedAsset


def creator_can_query(*, user: User | None, team: Team) -> bool:
    if user is None or not team.all_users_with_access().filter(id=user.id).exists():
        return False
    return UserAccessControl(user=user, team=team).check_access_level_for_resource("query", "viewer")


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
