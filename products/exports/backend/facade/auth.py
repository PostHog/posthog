from products.exports.backend.models.exported_asset import ExportedAsset


def export_asset_matches_renderer_token(*, asset_id: int, team_id: int, created_by_id: int, scope: str) -> bool:
    asset = (
        ExportedAsset.objects.only("export_context")
        .filter(id=asset_id, team_id=team_id, created_by_id=created_by_id)
        .first()
    )
    if asset is None:
        return False

    export_context = asset.export_context or {}
    if scope == "heatmap:read":
        return bool(export_context.get("heatmap_url"))
    if scope == "session_recording:read":
        return bool(export_context.get("session_recording_id"))
    return False
