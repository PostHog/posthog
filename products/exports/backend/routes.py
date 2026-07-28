from posthog.api.routing import RouterRegistry

from products.exports.backend.api import exports


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"exports", exports.ExportedAssetViewSet, "project_exports", ["team_id"])
