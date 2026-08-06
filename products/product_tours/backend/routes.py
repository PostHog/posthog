from posthog.api.routing import RouterRegistry

from products.product_tours.backend.api import ProductTourViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"product_tours", ProductTourViewSet, "project_product_tours", ["project_id"])
