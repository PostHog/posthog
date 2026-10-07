from django.urls import URLPattern, path

from posthog.api import sharing
from posthog.api.routing import RouterRegistry

from products.notebooks.backend.presentation.views.notebook import NotebookViewSet
from products.notebooks.backend.presentation.views.reusable_widget import ReusableWidgetViewSet
from products.notebooks.backend.presentation.views.sandbox_heartbeat import notebook_sql_v2_data_plane_heartbeat

api_urlpatterns: list[URLPattern] = [
    path(
        "sandbox/heartbeat/",
        notebook_sql_v2_data_plane_heartbeat,
        name="notebook_sandbox_heartbeat",
    ),
]


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"notebook_widgets", ReusableWidgetViewSet, "project_reusable_widgets", ["project_id"])
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
