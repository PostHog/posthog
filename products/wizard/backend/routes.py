from posthog.api.routing import RouterRegistry

from products.wizard.backend.presentation.artifacts.views import WizardRunArtifactViewSet
from products.wizard.backend.presentation.registry.views import WizardRegistryViewSet
from products.wizard.backend.presentation.runs.views import WizardRunViewSet
from products.wizard.backend.presentation.sessions.views import WizardSessionViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"wizard/sessions", WizardSessionViewSet, "project_wizard_sessions", ["project_id"])
    wizard_runs_router = routers.projects.register(
        r"wizard/runs", WizardRunViewSet, "project_wizard_runs", ["project_id"]
    )
    wizard_runs_router.register(
        r"artifacts",
        WizardRunArtifactViewSet,
        "project_wizard_run_artifacts",
        ["project_id", "run_id"],
    )
    routers.projects.register(r"wizard/registry", WizardRegistryViewSet, "project_wizard_registry", ["project_id"])
