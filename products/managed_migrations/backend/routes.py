from posthog.api.routing import RouterRegistry

from products.managed_migrations.backend.api.batch_imports import BatchImportViewSet
from products.managed_migrations.backend.api.support_batch_imports import BatchImportSupportViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"managed_migrations",
        BatchImportViewSet,
        "project_managed_migrations",
        ["project_id"],
    )
    # Staff-only cross-team diagnostics: root-level so it is not team-nested.
    routers.root.register(
        r"managed_migrations_support",
        BatchImportSupportViewSet,
        "managed_migrations_support",
    )
