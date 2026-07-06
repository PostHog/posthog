from posthog.api.routing import RouterRegistry

from products.growth.backend.api.identity_matching import IdentityMatchingLinkViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"identity_matching_links", IdentityMatchingLinkViewSet, "project_identity_matching_links", ["team_id"]
    )
