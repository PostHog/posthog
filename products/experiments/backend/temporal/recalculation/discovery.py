"""Discovery of the metrics that a recalculation run calculates."""

from django.db import close_old_connections

import structlog

from posthog.models.scoping import team_scope
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.sync import database_sync_to_async_pool

from products.experiments.backend.metric_resolution import get_metrics_for_calculation
from products.experiments.backend.models.experiment import ExperimentMetricsRecalculation
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig
from products.experiments.backend.recalculation.kill_switch import recalculation_enabled
from products.experiments.backend.temporal.models import ExperimentMetricToRecalculate
from products.experiments.backend.temporal.recalculation.routing import _activity_task_queue, _calc_route, _CalcRoute

from . import run_state

logger = structlog.get_logger(__name__)


@database_sync_to_async_pool
def _discover_experiment_metrics_sync(recalculation_id: str) -> list[ExperimentMetricToRecalculate]:
    close_old_connections()
    if not recalculation_enabled():
        run_state._fail_pending_run(recalculation_id)
        raise run_state._recalculation_paused_error(recalculation_id)

    state = run_state._get_recalc_state(recalculation_id)
    with team_scope(state.team_id, canonical=True):
        recalculation = ExperimentMetricsRecalculation.objects.select_related("experiment").get(id=recalculation_id)
        experiment = recalculation.experiment

        # The same flag check as the start step, so an organization off the flag (or a failed check) keeps the
        # AUTO mode on the run's queue and pays for no routing.
        team_experiments_config = (
            get_or_create_team_extension(experiment.team, TeamExperimentsConfig)
            if _activity_task_queue(str(experiment.team.organization_id)) is not None
            else None
        )
        routes: dict[str, _CalcRoute] = {}
        metrics_to_recalculate = []
        # request_recalculation sets total_metrics from the same resolver, so the run's progress count
        # matches the metrics this activity schedules.
        for metric in get_metrics_for_calculation(experiment):
            route: _CalcRoute | None = None
            if team_experiments_config is not None:
                # Metrics that share a uuid share one definition, so they share one route.
                route = routes.get(metric.uuid)
                if route is None:
                    route = routes[metric.uuid] = _calc_route(experiment, team_experiments_config, metric.definition)
            metrics_to_recalculate.append(
                ExperimentMetricToRecalculate(
                    experiment_id=experiment.id,
                    metric_uuid=metric.uuid,
                    role=metric.role,
                    task_queue=route.task_queue if route is not None else None,
                    precomputation_mode=route.precomputation_mode if route is not None else None,
                )
            )

        recalculation.metric_uuids = [m.metric_uuid for m in metrics_to_recalculate]
        recalculation.save(update_fields=["metric_uuids"])

    logger.info(
        "Discovered experiment metrics for recalculation",
        recalculation_id=recalculation_id,
        count=len(metrics_to_recalculate),
    )
    return metrics_to_recalculate
