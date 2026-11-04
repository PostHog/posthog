from posthog.api.routing import RouterRegistry

from products.wizard.backend.presentation.artifacts.views import WizardRunArtifactViewSet
from products.wizard.backend.presentation.installs.views import WizardInstallViewSet
from products.wizard.backend.presentation.registry.views import WizardRegistryViewSet
from products.wizard.backend.presentation.runs.views import WizardRunTasksViewSet, WizardRunViewSet
from products.wizard.backend.presentation.scans.views import WizardScanViewSet
from products.wizard.backend.presentation.sessions.views import WizardSessionViewSet
from products.wizard.backend.presentation.tool_catalog.views import WizardToolCatalogViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.root.register(r"wizard/tool_catalog", WizardToolCatalogViewSet, "wizard_tool_catalog")
    routers.projects.register(r"wizard/sessions", WizardSessionViewSet, "project_wizard_sessions", ["project_id"])
    routers.projects.register(r"wizard/scans", WizardScanViewSet, "project_wizard_scans", ["project_id"])

    # Wizard Runs
    wizard_runs_router = routers.projects.register(
        r"wizard/runs", WizardRunViewSet, "project_wizard_runs", ["project_id"]
    )

    routers.projects.register(
        r"wizard/runs",
        WizardRunTasksViewSet,
        "project_wizard_run_tasks",
        ["project_id"],
    )

    # Wizard Run Artifacts
    wizard_runs_router.register(
        r"artifacts",
        WizardRunArtifactViewSet,
        "project_wizard_run_artifacts",
        ["project_id", "run_id"],
    )

    # Cloud setup runs started by agents
    routers.projects.register(r"wizard/installs", WizardInstallViewSet, "project_wizard_installs", ["project_id"])

    # Wizard Registry
    routers.projects.register(r"wizard/registry", WizardRegistryViewSet, "project_wizard_registry", ["project_id"])
