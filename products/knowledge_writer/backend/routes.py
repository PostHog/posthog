from posthog.api.routing import RouterRegistry

from products.knowledge_writer.backend.presentation.views import MergePushViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"knowledge_writer/merge_pushes",
        MergePushViewSet,
        "project_knowledge_writer_merge_pushes",
        ["project_id"],
    )
