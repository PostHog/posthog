from posthog.api import sharing
from posthog.api.routing import RouterRegistry

from products.notebooks.backend.presentation.views.notebook import NotebookViewSet


def register_routes(routers: RouterRegistry) -> None:
    project_notebooks_router = routers.projects.register(
        r"notebooks", NotebookViewSet, "project_notebooks", ["project_id"]
    )

    # SharingConfigurationViewSet is shared (core), but the route lives under
    # notebooks/<id>/sharing — the notebooks product owns the sub-route.
    project_notebooks_router.register(
        r"sharing",
        sharing.SharingConfigurationViewSet,
        "project_notebook_sharing",
        ["project_id", "notebook_id"],
    )
