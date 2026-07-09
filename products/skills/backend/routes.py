from posthog.api.routing import RouterRegistry

from products.skills.backend.api.marketplace_views import LLMSkillMarketplaceViewSet
from products.skills.backend.api.skills import LLMSkillViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.register_legacy_dual_route(r"llm_skills", LLMSkillViewSet, "project_llm_skills", ["team_id"])
    # Git Smart HTTP marketplace. The prefix is the clone repo root: a client appends
    # /info/refs and /git-upload-pack, which map to the viewset's two actions. New endpoint,
    # so projects-only (no legacy environments alias).
    routers.projects.register(
        r"llm_skills/marketplace.git",
        LLMSkillMarketplaceViewSet,
        "project_llm_skills_marketplace",
        ["team_id"],
    )
