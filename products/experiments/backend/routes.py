from posthog.api.routing import RouterRegistry
from posthog.settings import EE_AVAILABLE

from products.experiments.backend.presentation.web_experiments import WebExperimentViewSet, web_experiments

# posthog-js calls `web_experiments` at `api/web_experiments`, which is outside the `api/experiments/`
# mount that `api_urlpatterns` gets. So `posthog/urls.py` keeps that path. It imports the view from here
# because the `tach.toml` interface exposes `backend.routes` but not `backend.presentation.web_experiments`.
__all__ = ["register_routes", "web_experiments"]


def register_routes(routers: RouterRegistry) -> None:
    # The web experiments API does not need EE, so it registers before the EE gate.
    routers.projects.register(r"web_experiments", WebExperimentViewSet, "web_experiments", ["project_id"])

    # The other experiments viewsets live in `ee/clickhouse/views/` and
    # `products/experiments/backend/presentation/views.py`. Both are unavailable
    # without EE installed, so these routes are EE-gated.
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
