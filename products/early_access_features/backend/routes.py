from posthog.api.routing import RouterRegistry

from products.early_access_features.backend.api import EarlyAccessFeatureViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"early_access_feature", EarlyAccessFeatureViewSet, "project_early_access_feature", ["project_id"]
    )
