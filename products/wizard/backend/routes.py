from posthog.api.routing import RouterRegistry

from products.wizard.backend.presentation.views import RepositoryDetectionViewSet, WizardSessionViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"wizard/sessions", WizardSessionViewSet, "project_wizard_sessions", ["project_id"])
    routers.projects.register(
        r"wizard/repository_detections",
        RepositoryDetectionViewSet,
        "project_wizard_repository_detections",
        ["project_id"],
    )
