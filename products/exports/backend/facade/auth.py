from collections.abc import Iterable
from typing import TYPE_CHECKING

from products.exports.backend.asset_access import viewable_assets
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


def viewable_exported_asset_ids(
    asset_ids: Iterable[int], *, team_id: int, user_id: int, user_access_control: "UserAccessControl"
) -> set[int]:
    """The ids, among `asset_ids` in this team, of the exported assets the user may read.

    Uses the same rules as the exports API, with a fixed number of queries however many ids are given.
    Product exports are never included, because their owning product authorizes them on its own endpoints.
    """
    assets = (
        ExportedAsset.objects.filter(id__in=set(asset_ids), team_id=team_id)
        .select_related("dashboard", "insight")
        .defer("content")
    )
    return viewable_assets(assets, user_id=user_id, user_access_control=user_access_control)
