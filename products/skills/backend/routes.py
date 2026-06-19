from posthog.api.routing import RouterRegistry

from products.skills.backend.api.skills import LLMSkillViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.register_legacy_dual_route(r"llm_skills", LLMSkillViewSet, "project_llm_skills", ["team_id"])
