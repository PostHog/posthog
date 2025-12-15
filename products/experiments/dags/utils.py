"""
Shared utilities for experiment-related Dagster schedules and sensors.
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import connection
from django.db.models import Q

import dagster

from posthog.schema import ExperimentQueryResponse

from posthog.models.experiment import Experiment
from posthog.models.team import Team

# Default hour (UTC) for experiment recalculation when team has no specific time set
DEFAULT_EXPERIMENT_RECALCULATION_HOUR = 2  # 02:00 UTC


def remove_step_sessions_from_experiment_result(result: ExperimentQueryResponse) -> ExperimentQueryResponse:
    """
    Remove step_sessions values from experiment results to reduce API response size.
    """
    if result.baseline is not None:
        result.baseline.step_sessions = None

    if result.variant_results is not None:
        for variant in result.variant_results:
            variant.step_sessions = None

    return result


def _parse_partition_key(partition_key: str) -> tuple[int, str, str]:
    """
    Parse partition key to extract experiment ID, metric UUID, and fingerprint.

    The partition key format is: experiment_{id}_metric_{uuid}_{fingerprint}
    """
    parts = partition_key.split("_")
    if len(parts) < 5 or parts[0] != "experiment" or parts[2] != "metric":
        raise ValueError(f"Invalid partition key format: {partition_key}")

    try:
        experiment_id = int(parts[1])
        metric_uuid = parts[3]
        fingerprint = parts[4]
        return experiment_id, metric_uuid, fingerprint
    except ValueError as e:
        raise ValueError(f"Failed to parse partition key {partition_key}: {e}")


def schedule_experiment_metric_partitions(
    context: dagster.ScheduleEvaluationContext,
    partition_name: str,
) -> list[dagster.RunRequest] | dagster.SkipReason:
    """
    Get experiment partitions that should run at the current scheduled hour based on team settings.

    This function filters experiments by their team's configured recalculation time and returns
    RunRequests for the matching partitions.

    Args:
        context: Dagster schedule evaluation context
        partition_name: Name of the dynamic partition set (e.g., "experiment_regular_metrics")

    Returns:
        List of RunRequests for partitions to process, or SkipReason if none found
    """
    try:
        connection.close()  # Reset connection

        current_hour = context.scheduled_execution_time.hour
        target_time = time(current_hour, 0, 0)

        # Build time filter for teams
        if current_hour == DEFAULT_EXPERIMENT_RECALCULATION_HOUR:
            # At default hour, include teams with NULL (not set) or explicitly set to this hour
            time_filter = Q(experiment_recalculation_time=target_time) | Q(experiment_recalculation_time__isnull=True)
        else:
            # At other hours, only include teams explicitly set to this hour
            time_filter = Q(experiment_recalculation_time=target_time)

        # Get all experiments from teams scheduled at this hour
        target_experiment_ids = set(
            Experiment.objects.filter(
                deleted=False,
                stats_config__timeseries=True,
                start_date__isnull=False,
                start_date__gte=datetime.now(ZoneInfo("UTC")) - timedelta(days=90),
                end_date__isnull=True,
                team__in=Team.objects.filter(time_filter),
            ).values_list("id", flat=True)
        )

        if not target_experiment_ids:
            return dagster.SkipReason(f"No experiments found for teams scheduled at {current_hour}:00 UTC")

        all_partitions = list(context.instance.get_dynamic_partitions(partition_name))

        if not all_partitions:
            return dagster.SkipReason(f"No {partition_name} partitions exist")

        # Filter to only partitions for target experiments
        partitions_to_run = []
        for partition_key in all_partitions:
            try:
                experiment_id, _, _ = _parse_partition_key(partition_key)
                if experiment_id in target_experiment_ids:
                    partitions_to_run.append(partition_key)
            except ValueError:
                context.log.warning(f"Skipping partition with invalid key format: {partition_key}")
                continue

        if not partitions_to_run:
            return dagster.SkipReason(f"No partitions to process for teams at {current_hour}:00 UTC")

        context.log.info(
            f"Scheduling refresh for {len(partitions_to_run)} partitions from {partition_name} for teams at {current_hour}:00 UTC"
        )

        return [
            dagster.RunRequest(
                run_key=f"scheduled_{partition_key}_{context.scheduled_execution_time.strftime('%Y%m%d_%H')}",
                partition_key=partition_key,
            )
            for partition_key in partitions_to_run
        ]

    except Exception as e:
        context.log.exception(f"Failed to schedule refresh for {partition_name}")
        raise dagster.Failure(f"Failed to schedule refresh for {partition_name}: {e}")


def refresh_experiment_metric_partitions(
    context: dagster.SensorEvaluationContext,
    partition_name: str,
    partitions_def: dagster.DynamicPartitionsDefinition,
    get_metrics_fn,
) -> dagster.SensorResult | dagster.SkipReason:
    """
    Synchronize experiment-metric partitions with current database state.

    This function compares expected partitions (based on active experiments/metrics in the database)
    with existing Dagster partitions. It creates new partitions for newly discovered combinations
    and removes obsolete partitions for deleted or inactive experiments.

    Args:
        context: Dagster sensor evaluation context
        partition_name: Name of the dynamic partition set (e.g., "experiment_regular_metrics")
        partitions_def: Dynamic partitions definition object
        get_metrics_fn: Function to get current experiment-metric combinations

    Returns:
        SensorResult with run requests and partition requests, or SkipReason if none found
    """
    try:
        connection.close()  # Reset connection

        current_experiment_metrics = get_metrics_fn(context)
        if not current_experiment_metrics:
            context.log.debug(f"No {partition_name} found for timeseries analysis")
            return dagster.SkipReason(f"No experiments with {partition_name} found")

        # Generate expected partition keys based on database state
        # Format: experiment_{id}_metric_{uuid}_{fingerprint}
        expected_partition_keys = [
            f"experiment_{exp_id}_metric_{metric_uuid}_{fingerprint}"
            for exp_id, metric_uuid, fingerprint in current_experiment_metrics
        ]

        # Get existing partitions from Dagster
        existing_partitions = set(context.instance.get_dynamic_partitions(partition_name))

        # Find new partitions (expected but not existing)
        new_partitions = [key for key in expected_partition_keys if key not in existing_partitions]

        # Find obsolete partitions (existing but not expected)
        expected_partition_keys_set = set(expected_partition_keys)
        obsolete_partitions = [key for key in existing_partitions if key not in expected_partition_keys_set]

        # Build response
        run_requests = []
        dynamic_partitions_requests = []

        if new_partitions:
            context.log.info(
                f"Discovered {len(new_partitions)} new {partition_name} combinations for timeseries analysis"
            )
            # Add new partitions
            dynamic_partitions_requests.append(partitions_def.build_add_request(new_partitions))
            # Create run requests for new partitions only
            run_requests = [
                dagster.RunRequest(
                    run_key=f"sensor_{partition_key}_{context.cursor or 'initial'}",
                    partition_key=partition_key,
                )
                for partition_key in new_partitions
            ]

        if obsolete_partitions:
            context.log.info(f"Removing {len(obsolete_partitions)} obsolete {partition_name} partitions")
            dynamic_partitions_requests.append(partitions_def.build_delete_request(obsolete_partitions))

        if not new_partitions and not obsolete_partitions:
            context.log.debug(f"No partition changes needed for {partition_name}")
            return dagster.SkipReason(f"No partition changes needed for {partition_name}")

        return dagster.SensorResult(
            run_requests=run_requests,
            dynamic_partitions_requests=dynamic_partitions_requests,
        )

    except Exception as e:
        context.log.exception(f"Failed to discover {partition_name} experiments")
        raise dagster.Failure(f"Failed to discover {partition_name} experiments: {e}")
