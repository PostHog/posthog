from posthog.api.routing import RouterRegistry
from posthog.settings import EE_AVAILABLE


def register_routes(routers: RouterRegistry) -> None:
    # All experiments viewsets currently live in `ee/clickhouse/views/` and
    # `products/experiments/backend/presentation/views.py` — both unavailable
    # without EE installed, so the entire surface is EE-gated.
    if not EE_AVAILABLE:
        return

    from products.experiments.backend.presentation.views import EnterpriseExperimentsViewSet

    from ee.clickhouse.views.experiment_holdouts import ExperimentHoldoutViewSet
    from ee.clickhouse.views.experiment_saved_metrics import ExperimentSavedMetricViewSet

    routers.projects.register(r"experiments", EnterpriseExperimentsViewSet, "project_experiments", ["project_id"])
    routers.projects.register(
        r"experiment_holdouts", ExperimentHoldoutViewSet, "project_experiment_holdouts", ["project_id"]
    )
    routers.projects.register(
        r"experiment_saved_metrics", ExperimentSavedMetricViewSet, "project_experiment_saved_metrics", ["project_id"]
    )
