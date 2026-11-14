from typing import Any

from django.conf import settings

from posthog.schema import ExperimentQuery, PrecomputationMode

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.metric_resolution import build_metric
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig
from products.experiments.backend.organization_flags import organization_flag_enabled

RECALCULATION_ACTIVITY_QUEUE_FEATURE_FLAG = "experiment-recalculation-activity-queue"


def _activity_task_queue(organization_id: str) -> str | None:
    # A flag error keeps the run on the workflow's queue, because a failed start would roll the row back to FAILED.
    try:
        enabled = organization_flag_enabled(RECALCULATION_ACTIVITY_QUEUE_FEATURE_FLAG, organization_id)
    except Exception as e:
        capture_exception(e)
        return None
    return settings.EXPERIMENTS_RECALCULATION_ACTIVITY_TASK_QUEUE if enabled else None


def recalculation_clickhouse_user(task_queue: str) -> ClickHouseUser | None:
    # Only the slot-capped queues run as the experiments user; a queue that collapses into the main queue keeps the default.
    capped_task_queues = {
        settings.EXPERIMENTS_RECALCULATION_ACTIVITY_TASK_QUEUE,
        settings.EXPERIMENTS_RECALCULATION_PRECOMPUTE_TASK_QUEUE,
        settings.EXPERIMENTS_RECALCULATION_BUILD_TASK_QUEUE,
        settings.EXPERIMENTS_RECALCULATION_DIRECT_HEAVY_TASK_QUEUE,
    } - {settings.EXPERIMENTS_RECALCULATION_TASK_QUEUE}
    return ClickHouseUser.EXPERIMENTS if task_queue in capped_task_queues else None


@frozen
class _CalcRoute:
    """The queue and precompute mode of one metric's calc activity, for a run on the activity queue flag."""

    task_queue: str
    precomputation_mode: PrecomputationMode | None


def _calc_route(
    experiment: Experiment, team_experiments_config: TeamExperimentsConfig, definition: dict[str, Any]
) -> _CalcRoute:
    """
    A metric that can read precomputed exposures and metric events goes to the precompute queue in the AUTO
    mode, and the runner checks the gates again when it calculates. The route does not use
    PrecomputationMode.PRECOMPUTED, which is reserved for staff tools, so for now the check runs twice. Any other
    metric goes to the activity queue and scans directly, so it never starts a precompute build there.
    """
    try:
        runner = ExperimentQueryRunner(
            query=ExperimentQuery(experiment_id=experiment.id, metric=build_metric(definition)),
            team=experiment.team,
            experiment=experiment,
            team_experiments_config=team_experiments_config,
            bypass_warehouse_access_control=True,
            user_facing=False,
            error_event_context=None,
        )
        reads_precomputed = runner._exposures_precompute_applicable() and runner._metric_events_precompute_applicable()
    except Exception as e:
        # The AUTO mode is what every run used before this routing, so a failed check falls back to it. Report
        # it, because a broken check sends every metric to the precompute queue.
        capture_exception(e, additional_properties={"tag": "experiment_recalculation_route_failed"})
        reads_precomputed = True

    if reads_precomputed:
        return _CalcRoute(task_queue=settings.EXPERIMENTS_RECALCULATION_PRECOMPUTE_TASK_QUEUE, precomputation_mode=None)
    return _CalcRoute(
        task_queue=settings.EXPERIMENTS_RECALCULATION_ACTIVITY_TASK_QUEUE,
        precomputation_mode=PrecomputationMode.DIRECT,
    )
