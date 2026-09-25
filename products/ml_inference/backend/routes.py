from posthog.api.routing import RouterRegistry

from products.ml_inference.backend.presentation.views import DecisionViewSet, SearchIntentViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"ml_inference/decisions", DecisionViewSet, "project_ml_inference_decisions", ["team_id"])
    routers.projects.register(
        r"ml_inference/search_intent", SearchIntentViewSet, "project_ml_inference_search_intent", ["team_id"]
    )
