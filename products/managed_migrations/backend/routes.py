from posthog.api.routing import RouterRegistry

from products.managed_migrations.backend.api.batch_imports import BatchImportViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"managed_migrations",
        BatchImportViewSet,
        "project_managed_migrations",
        ["project_id"],
    )
