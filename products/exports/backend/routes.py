from posthog.api.routing import RouterRegistry

from products.exports.backend.api import exports


def register_routes(routers: RouterRegistry) -> None:
    routers.register_legacy_dual_route(r"exports", exports.ExportedAssetViewSet, "environment_exports", ["team_id"])
