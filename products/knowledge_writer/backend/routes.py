from posthog.api.routing import RouterRegistry

from products.knowledge_writer.backend.presentation.views import MergeVerdictViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"knowledge_writer/merge_verdicts",
        MergeVerdictViewSet,
        "project_knowledge_writer_merge_verdicts",
        ["project_id"],
    )
