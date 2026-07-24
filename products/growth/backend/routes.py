from posthog.api.routing import RouterRegistry

from products.growth.backend.api.identity_matching import IdentityMatchingLinkViewSet
from products.growth.backend.api.product_push import ProductPushCampaignViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"identity_matching_links", IdentityMatchingLinkViewSet, "project_identity_matching_links", ["team_id"]
    )
    routers.organizations.register(
        r"product_push_campaign",
        ProductPushCampaignViewSet,
        "organization_product_push_campaign",
        ["organization_id"],
    )
