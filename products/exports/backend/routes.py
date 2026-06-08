from posthog.api.routing import RouterRegistry

from products.exports.backend.api import chart_images, exports


def register_routes(routers: RouterRegistry) -> None:
    routers.register_legacy_dual_route(r"exports", exports.ExportedAssetViewSet, "environment_exports", ["team_id"])
    routers.projects.register(r"chart_images", chart_images.ChartImageViewSet, "project_chart_images", ["team_id"])
