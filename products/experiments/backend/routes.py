from posthog.api.routing import RouterRegistry

from products.experiments.backend.presentation.experiment_holdouts import ExperimentHoldoutViewSet
from products.experiments.backend.presentation.experiment_saved_metrics import ExperimentSavedMetricViewSet
from products.experiments.backend.presentation.views import EnterpriseExperimentsViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"experiments", EnterpriseExperimentsViewSet, "project_experiments", ["project_id"])
    routers.projects.register(
        r"experiment_holdouts", ExperimentHoldoutViewSet, "project_experiment_holdouts", ["project_id"]
    )
    routers.projects.register(
        r"experiment_saved_metrics", ExperimentSavedMetricViewSet, "project_experiment_saved_metrics", ["project_id"]
    )
